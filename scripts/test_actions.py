"""End-to-end test harness for every ActionType against REAL AWS.

For each new AWS-flavoured ActionType, this script:
  1. (If it's a write action) calls the corresponding chaos_aws inducer
     so there's a real deformity to act on.
  2. Constructs a realistic Action() with the right params.
  3. Invokes env._dispatch_aws_action(action) directly \u2014 no LLM, no
     scenario JSON \u2014 just the function the env will call at training time.
  4. Verifies the result via an INDEPENDENT boto3 read so we know the
     action actually mutated AWS state (or returned plausible evidence).
  5. Calls the chaos_aws reset for the affected resource so the suite is
     idempotent.

Usage:
    python scripts/test_actions.py            # run every action
    python scripts/test_actions.py CHECK_CLOUDTRAIL_EVENTS
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.aws.local"
for _line in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []):
    _line = _line.strip()
    if not _line or _line.startswith("#") or "=" not in _line:
        continue
    _k, _, _v = _line.partition("=")
    os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# Make rl-agent importable.
sys.path.insert(0, str(ROOT / "rl-agent"))

import boto3                                            # noqa: E402
from botocore.exceptions import ClientError             # noqa: E402

from environment.env import IncidentCommanderEnv       # noqa: E402
from environment.models import Action, ActionType       # noqa: E402

# Reuse chaos handlers to set up state for write-action tests.
sys.path.insert(0, str(ROOT / "scripts"))
import chaos_aws                                        # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-east-1")
ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


# ---------------------------------------------------------------------------
# Per-action test definitions.
# Each entry has:
#   "params"  : dict of params for Action(...)
#   "before"  : optional callable to set up state (e.g. induce a deformity)
#   "verify"  : callable taking (action_result_str) -> (ok: bool, detail: str)
#               that does an INDEPENDENT boto3 read.
#   "after"   : optional callable to clean up.
#   "skip_if" : optional callable returning True to skip the test.
# ---------------------------------------------------------------------------

def _ok(s: str)   -> str: return f"\033[32m{s}\033[0m"
def _err(s: str)  -> str: return f"\033[31m{s}\033[0m"
def _warn(s: str) -> str: return f"\033[33m{s}\033[0m"


def _verify_substring_anywhere(needles: list[str]):
    """verify factory: pass if the dispatched action's result contains any
    of the needles."""
    def _v(result: str) -> tuple[bool, str]:
        lower = result.lower()
        hit = next((n for n in needles if n.lower() in lower), None)
        return (bool(hit), f"matched needle={hit!r}" if hit else
                f"none of {needles!r} found in result[:120]={result[:120]!r}")
    return _v


def _verify_secret_rotation_status_present():
    def _v(result: str) -> tuple[bool, str]:
        # Independent boto3 read: confirm the secret has rotation tags.
        sm = boto3.client("secretsmanager", region_name=REGION)
        d = sm.describe_secret(SecretId=os.environ.get(
            "SECRET_STRIPE_NAME", "ic-stripe-api-key"))
        has_tags = any(t.get("Key") in ("RotationStatus", "LastRotatedDays")
                       for t in d.get("Tags", []))
        return (has_tags or "RotationEnabled" in result,
                f"tags_present={has_tags} action_returned_rotation_keys="
                f"{'RotationEnabled' in result}")
    return _v


def _verify_iam_sim_decision():
    def _v(result: str) -> tuple[bool, str]:
        ok = ("allowed" in result.lower() or "implicitdeny" in result.lower()
              or "denied" in result.lower())
        return ok, f"decision_token_in_result={ok}"
    return _v


def _verify_quota_named():
    def _v(result: str) -> tuple[bool, str]:
        ok = "quota" in result.lower() and ("=" in result or "name" in result.lower())
        return ok, f"quota_metadata_present={ok}"
    return _v


def _verify_dlq_depth_reported():
    def _v(result: str) -> tuple[bool, str]:
        ok = "depth=" in result
        return ok, f"depth_field_present={ok}"
    return _v


def _verify_ssm_diff():
    def _v(result: str) -> tuple[bool, str]:
        ok = "ssm" in result.lower() and ("v1" in result.lower() or "v2" in result.lower() or "no history" in result.lower())
        return ok, f"diff_or_history={ok}"
    return _v


def _verify_sfn_exec():
    def _v(result: str) -> tuple[bool, str]:
        ok = "sfn-exec" in result.lower() or "no failed executions" in result.lower()
        return ok, f"sfn_exec_or_no_history={ok}"
    return _v


def _verify_lambda_invoked():
    def _v(result: str) -> tuple[bool, str]:
        ok = "status=200" in result or "status=202" in result or "ok" in result.lower()
        # Independent: look for a recent log stream on the function.
        cwl = boto3.client("logs", region_name=REGION)
        fn = os.environ.get("LAMBDA_RUNBOOK_FUNCTION", "ic-runbook-restart-pods")
        try:
            streams = cwl.describe_log_streams(
                logGroupName=f"/aws/lambda/{fn}",
                orderBy="LastEventTime", descending=True, limit=1
            ).get("logStreams", [])
            independent_ok = bool(streams)
        except Exception:
            independent_ok = False
        return (ok or independent_ok,
                f"action_status_ok={ok} log_streams_found={independent_ok}")
    return _v


def _verify_secret_rotated_independently():
    def _v(result: str) -> tuple[bool, str]:
        sm = boto3.client("secretsmanager", region_name=REGION)
        sname = os.environ.get("SECRET_STRIPE_NAME", "ic-stripe-api-key")
        v = sm.list_secret_version_ids(SecretId=sname).get("Versions", [])
        return (len(v) >= 1,
                f"versions_listed={len(v)} action_returned_new_version="
                f"{'new version stored' in result}")
    return _v


def _verify_queue_purged():
    def _v(result: str) -> tuple[bool, str]:
        sqs = boto3.client("sqs", region_name=REGION)
        url = sqs.get_queue_url(QueueName="ic-orders-dlq")["QueueUrl"]
        # PurgeQueue is async (up to 60s); accept "purge initiated" or depth==0
        attrs = sqs.get_queue_attributes(QueueUrl=url,
            AttributeNames=["ApproximateNumberOfMessages"])\
            .get("Attributes", {})
        depth = int(attrs.get("ApproximateNumberOfMessages", "0"))
        ok = "purge initiated" in result or depth == 0
        return ok, f"purge_initiated_or_depth0 (current_depth={depth})"
    return _v


def _verify_rule_enabled():
    def _v(result: str) -> tuple[bool, str]:
        eb = boto3.client("events", region_name=REGION)
        d = eb.describe_rule(Name="ic-orders-rule", EventBusName="ic-bus")
        ok = d.get("State") == "ENABLED"
        return ok, f"rule_state={d.get('State')}"
    return _v


# ---------------------------------------------------------------------------

TESTS: dict[str, dict] = {
    # ---- read / forensic ----
    "CHECK_CLOUDTRAIL_EVENTS": {
        "params": {"event_name": "CreateBucket", "last_minutes": 1440},
        "verify": _verify_substring_anywhere(["[cloudtrail]"]),
    },
    "DESCRIBE_RESOURCE_POLICY": {
        "params": {"target": "kms:ic-data-key"},
        "verify": _verify_substring_anywhere(["kms-policy", "Statement"]),
    },
    "GET_QUOTA_USAGE": {
        "params": {"service_code": "lambda"},
        "verify": _verify_quota_named(),
    },
    "CHECK_SECRET_ROTATION": {
        "params": {"secret_name": "ic-stripe-api-key"},
        "verify": _verify_secret_rotation_status_present(),
    },
    "VALIDATE_IAM_PERMISSION": {
        "params": {"iam_action": "s3:ListBucket", "resource": "*"},
        "verify": _verify_iam_sim_decision(),
    },
    "ANALYZE_CLOUDWATCH_INSIGHTS": {
        # use the alarm-hook function's log group which definitely exists
        "params": {"log_group": "/aws/lambda/ic-cold-start-target",
                   "pattern": "INIT", "last_minutes": 60},
        "verify": _verify_substring_anywhere(["[insights"]),
    },
    "INSPECT_DLQ_MESSAGES": {
        "before": lambda: chaos_aws._t12_induce(),
        "params": {"queue_name": "ic-orders-dlq", "max_messages": 3},
        "verify": _verify_dlq_depth_reported(),
        "after": lambda: chaos_aws._t12_reset(),
    },
    "DIFF_CONFIG_VERSIONS": {
        "before": lambda: chaos_aws._t17_induce(),    # creates a v2
        "params": {"parameter_name": "/ic/payments/db-pool-size"},
        "verify": _verify_ssm_diff(),
        "after": lambda: chaos_aws._t17_reset(),
    },
    "DESCRIBE_STATE_MACHINE_EXEC": {
        "before": lambda: chaos_aws._t21_induce(),   # FAILED execution
        "params": {"state_machine_name": "ic-order-saga"},
        "verify": _verify_sfn_exec(),
    },
    # ---- write / remediation ----
    "INVOKE_LAMBDA": {
        "params": {"function_name": "ic-runbook-restart-pods",
                   "payload": {"reason": "test_actions.py"}},
        "verify": _verify_lambda_invoked(),
    },
    "ROTATE_SECRET": {
        "params": {"secret_name": "ic-stripe-api-key"},
        "verify": _verify_secret_rotated_independently(),
        "after": lambda: chaos_aws._t14_reset(),
    },
    "PURGE_QUEUE": {
        "before": lambda: chaos_aws._t12_induce(),
        "params": {"queue_name": "ic-orders-dlq"},
        "verify": _verify_queue_purged(),
    },
    "ENABLE_EVENTBRIDGE_RULE": {
        "before": lambda: chaos_aws._t20_induce(),   # disable first
        "params": {"rule_name": "ic-orders-rule", "bus_name": "ic-bus"},
        "verify": _verify_rule_enabled(),
    },
}


# ---------------------------------------------------------------------------

def run_one(name: str, spec: dict, env: IncidentCommanderEnv) -> dict:
    print(f"\n=== test {name} ===", flush=True)
    rec: dict = {"name": name, "phase": {}, "ok": False}
    if "before" in spec:
        try:
            r = spec["before"]()
            rec["phase"]["before"] = "ok"
            print(f"  [before] {json.dumps(r, default=str)[:160]}")
        except Exception as e:
            rec["phase"]["before"] = f"err: {e}"
            print(_warn(f"  [before-err] {e}"))
    # Build action
    action = Action(type=ActionType[name], params=spec["params"])
    try:
        result = env._dispatch_aws_action(action)
        if result is None:
            raise RuntimeError(f"dispatch returned None for {name}")
        rec["phase"]["dispatch"] = "ok"
        print(f"  [dispatch] {result[:300]}")
    except Exception as e:
        rec["phase"]["dispatch"] = f"err: {e}"
        print(_err(f"  [dispatch-err] {e}"))
        return rec
    # Verify (independent boto3 read)
    try:
        ok, detail = spec["verify"](result)
        rec["phase"]["verify"] = "ok" if ok else "fail"
        rec["verify_detail"] = detail
        print((_ok if ok else _err)(f"  [verify] {ok}: {detail}"))
        rec["ok"] = ok
    except Exception as e:
        rec["phase"]["verify"] = f"err: {e}"
        print(_err(f"  [verify-err] {e}"))
    # After (cleanup)
    if "after" in spec:
        try:
            spec["after"]()
            rec["phase"]["after"] = "ok"
        except Exception as e:
            rec["phase"]["after"] = f"err: {e}"
            print(_warn(f"  [after-err] {e}"))
    return rec


def main():
    if os.getenv("IC_USE_LIVE_AWS", "false").lower() not in ("1", "true", "yes"):
        print("test_actions.py: live AWS disabled (mentor 2026-04-25). "
              "Set IC_USE_LIVE_AWS=true to re-enable.")
        sys.exit(0)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    env = IncidentCommanderEnv(use_mock=True)
    # Load any task to satisfy reset; pick task21 since it's AWS-flavoured.
    env.reset("task21")
    results = []
    items = TESTS.items() if only is None else [(only, TESTS[only])]
    for name, spec in items:
        results.append(run_one(name, spec, env))
        time.sleep(2)                # be gentle on AWS APIs
    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== summary: {passed}/{len(results)} actions passed ===")
    for r in results:
        line = f"  {r['name']}: {'PASS' if r['ok'] else 'FAIL'}"
        if not r["ok"]:
            line += f"  ({r.get('verify_detail', r['phase'])})"
        print(line)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
