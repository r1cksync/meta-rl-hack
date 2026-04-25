"""Generate ~210+ simulator scenarios across easy / medium / hard buckets.

Each scenario is a JSON file in ../../scenarios/sim/<difficulty>/.
Schema matches `simulator/scenarios.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]   # rl-agent/
OUT_BASE  = ROOT / "scenarios" / "sim"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(action_id: str, **params) -> dict:
    return {"id": action_id, "params": params}


def _scn(sid: str, difficulty: str, title: str, description: str,
         preconditions: list[dict],
         scheduled_failures: list[dict],
         chain: list[dict],
         target_score: float = 0.55,
         max_steps: int = 16) -> dict:
    return {
        "id": sid, "difficulty": difficulty,
        "title": title, "description": description,
        "preconditions": preconditions,
        "scheduled_failures": scheduled_failures,
        "correct_action_chain": chain,
        "target_score": target_score,
        "max_steps": max_steps,
    }


# ---------------------------------------------------------------------------
# Easy templates — single-service incidents, ≥120 instances
# ---------------------------------------------------------------------------

EASY_PRODUCTS = ["checkout", "orders", "inventory", "payments", "search",
                 "recommendations", "auth", "billing", "shipping",
                 "notifications", "reviews", "catalog", "fulfillment",
                 "telemetry", "analytics", "userprofile", "cart", "pricing",
                 "promotions", "media"]


def _easy_lambda_throttle(idx: int, product: str) -> dict:
    fn = f"ic-{product}"
    return _scn(
        f"sim_easy_lambda_throttle_{idx:03d}",
        "easy",
        f"{product} Lambda throttling",
        f"Customers report 5xx from /{product}. CloudWatch alarm "
        f"`{product}-Throttles` is in ALARM. Fix the throttle.",
        preconditions=[{"path": f"lambda_/{fn}", "op": "set",
                        "value": {"name": fn, "state": "Active",
                                  "reserved_concurrency": 0,
                                  "invocations": 0, "errors": 0,
                                  "throttles": 5}}],
        scheduled_failures=[{"action_id": "lambda.invoke",
                             "error": "TooManyRequestsException",
                             "message": "Reserved concurrency = 0",
                             "count": 1}],
        chain=[
            _step("lambda.describe", resource_id=fn),
            _step("lambda.invoke",   resource_id=fn),  # reproduce: fails (scheduled)
            _step("lambda.scale",    resource_id=fn, capacity=25),
            _step("lambda.invoke",   resource_id=fn),  # verify: succeeds
        ],
    )


def _easy_sqs_dlq_depth(idx: int, product: str) -> dict:
    q = f"ic-{product}-dlq"
    return _scn(
        f"sim_easy_sqs_dlq_{idx:03d}",
        "easy",
        f"{product} DLQ depth growing",
        f"`{q}` ApproximateNumberOfMessagesVisible exceeded threshold. "
        f"Inspect the messages and purge stale ones.",
        preconditions=[{"path": f"sqs/{q}", "op": "set",
                        "value": {"name": q, "depth": 42, "in_flight": 0,
                                  "messages": [{"id": f"m-{i}",
                                                "body": "old"} for i in range(42)],
                                  "attrs": {"VisibilityTimeout": 30},
                                  "dlq": None}}],
        scheduled_failures=[],
        chain=[
            _step("sqs.describe", resource_id=q),
            _step("sqs.receive",  resource_id=q, limit=10),
            _step("sqs.purge",    resource_id=q),
        ],
    )


def _easy_secret_rotation(idx: int, product: str) -> dict:
    sec = f"ic-{product}-secret"
    return _scn(
        f"sim_easy_secret_rotation_{idx:03d}",
        "easy",
        f"{product} secret rotation overdue",
        f"`{sec}` was last rotated >90 days ago. Rotate it now.",
        preconditions=[{"path": f"secrets/{sec}", "op": "set",
                        "value": {"name": sec, "value": "old",
                                  "versions": ["v1"], "rotation_enabled": True,
                                  "last_rotated_s": None,
                                  "tags": {"RotationStatus": "STALE",
                                           "LastRotatedDays": "120"}}}],
        scheduled_failures=[],
        chain=[
            _step("secretsmanager.describe", resource_id=sec),
            _step("secretsmanager.rotate",   resource_id=sec),
        ],
    )


def _easy_kms_disabled(idx: int, product: str) -> dict:
    alias = f"alias/ic-{product}-key"
    return _scn(
        f"sim_easy_kms_disabled_{idx:03d}",
        "easy",
        f"{product} KMS key disabled",
        f"Encrypt calls fail with KMSInvalidStateException. Re-enable `{alias}`.",
        preconditions=[{"path": f"kms/{alias}", "op": "set",
                        "value": {"alias": alias, "state": "Disabled",
                                  "policy": "{}", "pending_deletion_days": None}}],
        scheduled_failures=[{"action_id": "kms.encrypt",
                             "error": "KMSInvalidStateException",
                             "message": "key disabled",
                             "count": 1}],
        chain=[
            _step("kms.describe", resource_id=alias),
            _step("kms.encrypt",  resource_id=alias, plaintext="hi"),  # reproduce
            _step("kms.enable",   resource_id=alias),
            _step("kms.encrypt",  resource_id=alias, plaintext="hi"),  # verify
        ],
    )


def _easy_ssm_drift(idx: int, product: str) -> dict:
    p = f"/ic/{product}/db-pool-size"
    return _scn(
        f"sim_easy_ssm_drift_{idx:03d}",
        "easy",
        f"{product} pool size dropped",
        f"`{p}` was changed from 50 to 5 — DB connection storm. Roll back.",
        preconditions=[{"path": f"ssm/{p}", "op": "set",
                        "value": {"name": p, "value": "5", "version": 2,
                                  "history": [{"v": 1, "value": "50", "ts": 0},
                                              {"v": 2, "value": "5",  "ts": 1}]}}],
        scheduled_failures=[],
        chain=[
            _step("ssm.describe",      resource_id=p),
            _step("ssm.diff_versions", resource_id=p, v1=1, v2=2),
            _step("ssm.rollback",      resource_id=p, version=1),
        ],
    )


def _easy_dynamodb_throttle(idx: int, product: str) -> dict:
    t = f"ic-{product}-table"
    return _scn(
        f"sim_easy_ddb_throttle_{idx:03d}",
        "easy",
        f"{product} DynamoDB throttling",
        f"`{t}` is throttling writes. Scale write capacity.",
        preconditions=[{"path": f"dynamodb/{t}", "op": "set",
                        "value": {"name": t, "items": {}, "throttled": True,
                                  "capacity": 5}}],
        scheduled_failures=[],
        chain=[
            _step("dynamodb.describe", resource_id=t),
            _step("dynamodb.scale",    resource_id=t, capacity=50),
        ],
    )


EASY_TEMPLATES = [
    _easy_lambda_throttle,
    _easy_sqs_dlq_depth,
    _easy_secret_rotation,
    _easy_kms_disabled,
    _easy_ssm_drift,
    _easy_dynamodb_throttle,
]


# ---------------------------------------------------------------------------
# Medium templates — 2-service incidents, ≥60 instances
# ---------------------------------------------------------------------------

MEDIUM_PRODUCTS = EASY_PRODUCTS[:15]


def _med_lambda_secret(idx: int, product: str) -> dict:
    fn  = f"ic-{product}"
    sec = f"ic-{product}-db-creds"
    return _scn(
        f"sim_med_lambda_secret_{idx:03d}",
        "medium",
        f"{product} Lambda errors spike",
        f"`{fn}` is failing on every invocation. The error mentions "
        "DecryptionFailure but the alarm is named `Lambda-Errors`. The "
        "real cause is a stale secret rotation that left an unusable version.",
        preconditions=[
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 25,
                       "invocations": 0, "errors": 7, "throttles": 0,
                       "last_error": "DecryptionFailure"}},
            {"path": f"secrets/{sec}", "op": "set",
             "value": {"name": sec, "value": "broken",
                       "versions": ["v1", "v2"], "rotation_enabled": True,
                       "last_rotated_s": None,
                       "tags": {"RotationStatus": "FAILED",
                                "LastRotatedDays": "5"}}},
        ],
        scheduled_failures=[{"action_id": "lambda.invoke",
                             "error": "KMSAccessDeniedException",
                             "message": "Lambda cannot decrypt env var",
                             "count": 1}],
        chain=[
            _step("lambda.describe",        resource_id=fn),
            _step("lambda.invoke",          resource_id=fn),  # reproduce
            _step("secretsmanager.describe", resource_id=sec),
            _step("secretsmanager.rotate",  resource_id=sec),
            _step("lambda.invoke",          resource_id=fn),  # verify
        ],
        target_score=0.60, max_steps=18,
    )


def _med_eventbridge_lambda(idx: int, product: str) -> dict:
    fn   = f"ic-{product}-handler"
    bus  = f"ic-{product}-bus"
    rule = f"ic-{product}-rule"
    return _scn(
        f"sim_med_eb_lambda_{idx:03d}",
        "medium",
        f"{product} pipeline silent",
        f"Events are being published to `{bus}` but `{fn}` is not invoked. "
        "Rule was disabled during a deploy.",
        preconditions=[
            {"path": f"events/{bus}", "op": "set",
             "value": {"name": bus,
                       "rules": {rule: {"name": rule, "state": "DISABLED",
                                        "target_arn": fn}}}},
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 10,
                       "invocations": 0, "errors": 0, "throttles": 0}},
        ],
        scheduled_failures=[],
        chain=[
            _step("events.describe", bus_name=bus, rule_name=rule),
            _step("events.enable",   bus_name=bus, rule_name=rule),
            _step("events.publish",  bus_name=bus, payload="ping"),
        ],
        target_score=0.55, max_steps=16,
    )


def _med_kms_lambda(idx: int, product: str) -> dict:
    fn    = f"ic-{product}"
    alias = f"alias/ic-{product}-data"
    return _scn(
        f"sim_med_kms_lambda_{idx:03d}",
        "medium",
        f"{product} Lambda 5xx after KMS change",
        f"`{fn}` invocations fail. Logs show KMS pending deletion on `{alias}`.",
        preconditions=[
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 10,
                       "invocations": 0, "errors": 3, "throttles": 0}},
            {"path": f"kms/{alias}", "op": "set",
             "value": {"alias": alias, "state": "PendingDeletion",
                       "policy": "{}", "pending_deletion_days": 7}},
        ],
        scheduled_failures=[{"action_id": "lambda.invoke",
                             "error": "KMSInvalidStateException",
                             "message": f"key {alias} pending deletion",
                             "count": 1}],
        chain=[
            _step("lambda.describe", resource_id=fn),
            _step("lambda.invoke",   resource_id=fn),  # reproduce
            _step("kms.describe",    resource_id=alias),
            _step("kms.enable",      resource_id=alias),
            _step("lambda.invoke",   resource_id=fn),  # verify
        ],
        target_score=0.60, max_steps=18,
    )


def _med_sfn_lambda(idx: int, product: str) -> dict:
    sm = f"ic-{product}-saga"
    fn = f"ic-{product}-step"
    return _scn(
        f"sim_med_sfn_lambda_{idx:03d}",
        "medium",
        f"{product} state machine failing",
        f"`{sm}` executions stuck in FAILED. Underlying Lambda is throttled.",
        preconditions=[
            {"path": f"stepfunctions/{sm}", "op": "set",
             "value": {"name": sm,
                       "executions": [{"id": "e0", "status": "FAILED",
                                       "error": "States.TaskFailed",
                                       "input": "{}"}],
                       "force_fail": True}},
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 0,
                       "invocations": 0, "errors": 0, "throttles": 4}},
        ],
        scheduled_failures=[],
        chain=[
            _step("stepfunctions.describe", resource_id=sm),
            _step("lambda.describe", resource_id=fn),
            _step("lambda.scale",    resource_id=fn, capacity=25),
            _step("stepfunctions.start", resource_id=sm, input="{}"),
        ],
        target_score=0.55, max_steps=18,
    )


MEDIUM_TEMPLATES = [
    _med_lambda_secret,
    _med_eventbridge_lambda,
    _med_kms_lambda,
    _med_sfn_lambda,
]


# ---------------------------------------------------------------------------
# Hard templates — 3+ services, misleading alert names, ≥30 instances
# ---------------------------------------------------------------------------

HARD_PRODUCTS = EASY_PRODUCTS[:10]


def _hard_apigw_lambda_kms(idx: int, product: str) -> dict:
    fn    = f"ic-{product}"
    alias = f"alias/ic-{product}-data"
    sec   = f"ic-{product}-config"
    return _scn(
        f"sim_hard_apigw_chain_{idx:03d}",
        "hard",
        f"{product} 5xx — alert says ApiGateway",
        "Pager fires for `ApiGateway-5xx`. Real cause: a config-change ticket "
        "rotated a secret that still references a KMS key now scheduled for "
        "deletion. Fixing only the secret won't help — the underlying KMS "
        "key must be re-enabled, the secret rotated, and the Lambda invoked "
        "to clear the cached error.",
        preconditions=[
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 10,
                       "invocations": 0, "errors": 9, "throttles": 0,
                       "last_error": "AccessDeniedException"}},
            {"path": f"kms/{alias}", "op": "set",
             "value": {"alias": alias, "state": "PendingDeletion",
                       "policy": "{}", "pending_deletion_days": 6}},
            {"path": f"secrets/{sec}", "op": "set",
             "value": {"name": sec, "value": "broken",
                       "versions": ["v1"], "rotation_enabled": True,
                       "last_rotated_s": None,
                       "tags": {"RotationStatus": "FAILED",
                                "LastRotatedDays": "10",
                                "KmsKeyAlias": alias}}},
        ],
        scheduled_failures=[
            {"action_id": "lambda.invoke",
             "error": "AccessDeniedException",
             "message": "kms decryption failed because key disabled",
             "count": 1},
        ],
        chain=[
            _step("cloudwatch.get_logs", log_group=f"/aws/lambda/{fn}",
                  filter="kms"),
            _step("lambda.invoke",     resource_id=fn),  # reproduce
            _step("kms.describe",      resource_id=alias),
            _step("kms.enable",        resource_id=alias),
            _step("secretsmanager.describe", resource_id=sec),
            _step("secretsmanager.rotate",   resource_id=sec),
            _step("lambda.invoke",     resource_id=fn),  # verify
        ],
        target_score=0.65, max_steps=22,
    )


def _hard_iam_eb_lambda(idx: int, product: str) -> dict:
    bus   = f"ic-{product}-bus"
    rule  = f"ic-{product}-rule"
    fn    = f"ic-{product}-handler"
    role  = f"arn:aws:iam::000000000000:role/{fn}-role"
    return _scn(
        f"sim_hard_iam_chain_{idx:03d}",
        "hard",
        f"{product} pipeline silent — alert says LambdaErrors",
        "Alarm name is `LambdaErrors` but Lambda has zero invocations. "
        "EventBridge rule is enabled, but the Lambda's resource policy "
        "denies events:Invoke for the bus. Need IAM simulation, then a "
        "policy fix, then re-publish.",
        preconditions=[
            {"path": f"events/{bus}", "op": "set",
             "value": {"name": bus,
                       "rules": {rule: {"name": rule, "state": "ENABLED",
                                        "target_arn": fn}}}},
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 10,
                       "invocations": 0, "errors": 0, "throttles": 0}},
            {"path": f"iam/{role}", "op": "set",
             "value": {"name": role, "denies": ["lambda:InvokeFunction"]}},
        ],
        scheduled_failures=[
            {"action_id": "events.publish",
             "error": "AccessDeniedException",
             "message": "events:Invoke denied by lambda resource policy",
             "count": 1},
        ],
        chain=[
            _step("events.describe", bus_name=bus, rule_name=rule),
            _step("events.publish",  bus_name=bus, payload="ping"),  # reproduce
            _step("lambda.describe", resource_id=fn),
            _step("iam.simulate_policy", principal=role,
                  action_name="lambda:InvokeFunction", resource=fn),
            _step("lambda.put_policy", resource_id=fn,
                  policy='{"Version":"2012-10-17","Statement":[{"Effect":"Allow"}]}'),
            _step("events.publish", bus_name=bus, payload="ping"),
            _step("lambda.invoke",  resource_id=fn),  # verify
        ],
        target_score=0.65, max_steps=22,
    )


def _hard_ddb_ssm_drift(idx: int, product: str) -> dict:
    table = f"ic-{product}-table"
    pool  = f"/ic/{product}/db-pool-size"
    fn    = f"ic-{product}-writer"
    return _scn(
        f"sim_hard_ddb_chain_{idx:03d}",
        "hard",
        f"{product} latency spike — alert says DDB throttle",
        "DynamoDB throttle alarm fires, but root cause is an SSM parameter "
        "drift that pinned a tiny pool size on the writer Lambda — which "
        "retries faster than DDB can absorb. Need to roll back SSM, then "
        "scale DDB, then verify the writer.",
        preconditions=[
            {"path": f"dynamodb/{table}", "op": "set",
             "value": {"name": table, "items": {}, "throttled": True,
                       "capacity": 5}},
            {"path": f"ssm/{pool}", "op": "set",
             "value": {"name": pool, "value": "1", "version": 3,
                       "history": [{"v": 1, "value": "50", "ts": 0},
                                   {"v": 2, "value": "10", "ts": 1},
                                   {"v": 3, "value": "1",  "ts": 2}]}},
            {"path": f"lambda_/{fn}", "op": "set",
             "value": {"name": fn, "state": "Active",
                       "reserved_concurrency": 50,
                       "invocations": 0, "errors": 6, "throttles": 0}},
        ],
        scheduled_failures=[
            {"action_id": "dynamodb.send",
             "error": "ProvisionedThroughputExceededException",
             "message": "ddb capacity exceeded",
             "count": 1},
        ],
        chain=[
            _step("cloudwatch.get_logs", log_group=f"/aws/lambda/{fn}",
                  filter="throttle"),
            _step("dynamodb.send",     resource_id=table, payload={"pk":"x"}),  # reproduce
            _step("ssm.diff_versions", resource_id=pool, v1=1, v2=3),
            _step("ssm.rollback",      resource_id=pool, version=1),
            _step("dynamodb.scale",    resource_id=table, capacity=50),
            _step("lambda.invoke",     resource_id=fn),  # verify
        ],
        target_score=0.65, max_steps=22,
    )


HARD_TEMPLATES = [
    _hard_apigw_lambda_kms,
    _hard_iam_eb_lambda,
    _hard_ddb_ssm_drift,
]


# ---------------------------------------------------------------------------
# Build & write
# ---------------------------------------------------------------------------

def build():
    counts = {"easy": 0, "medium": 0, "hard": 0}
    (OUT_BASE / "easy").mkdir(parents=True, exist_ok=True)
    (OUT_BASE / "medium").mkdir(parents=True, exist_ok=True)
    (OUT_BASE / "hard").mkdir(parents=True, exist_ok=True)

    idx = 1
    for tmpl in EASY_TEMPLATES:
        for product in EASY_PRODUCTS:               # 6 * 20 = 120 easy
            scn = tmpl(idx, product); idx += 1
            (OUT_BASE / "easy" / f"{scn['id']}.json").write_text(
                json.dumps(scn, indent=2), encoding="utf-8")
            counts["easy"] += 1

    idx = 1
    for tmpl in MEDIUM_TEMPLATES:
        for product in MEDIUM_PRODUCTS:             # 4 * 15 = 60 medium
            scn = tmpl(idx, product); idx += 1
            (OUT_BASE / "medium" / f"{scn['id']}.json").write_text(
                json.dumps(scn, indent=2), encoding="utf-8")
            counts["medium"] += 1

    idx = 1
    for tmpl in HARD_TEMPLATES:
        for product in HARD_PRODUCTS:               # 3 * 10 = 30 hard
            scn = tmpl(idx, product); idx += 1
            (OUT_BASE / "hard" / f"{scn['id']}.json").write_text(
                json.dumps(scn, indent=2), encoding="utf-8")
            counts["hard"] += 1

    total = sum(counts.values())
    print(f"easy:   {counts['easy']}")
    print(f"medium: {counts['medium']}")
    print(f"hard:   {counts['hard']}")
    print(f"total:  {total}")


if __name__ == "__main__":
    build()
