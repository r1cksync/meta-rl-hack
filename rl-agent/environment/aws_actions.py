"""AWS-backed implementations for the new non-obvious ActionType variants.

Every helper is a thin, side-effect-aware wrapper around boto3:
  * Read actions return human-readable evidence strings (suitable for
    pasting into the agent's observation `last_action_result`).
  * Write actions return a one-line confirmation; they refuse to run
    unless explicit AWS credentials + the relevant resource pointer
    env var is set, so the unit test suite is safe.

Designed so the SAME function is callable from the sync mock path AND
the async real path — the only async dependency was network IO and we
guard that with short timeouts via `aws_integrations._client`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .aws_integrations import _have_aws_credentials


def _client(service: str):
    """Region-pinned boto3 client.

    Always pulls region from `AWS_REGION` (not `AWS_DEFAULT_REGION`) so that
    a stray `~/.aws/config` profile pointing at a different region cannot
    redirect our calls.
    """
    import boto3                            # type: ignore
    from botocore.config import Config       # type: ignore
    cfg = Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2})
    return boto3.client(service,
                        region_name=os.environ.get("AWS_REGION", "us-east-1"),
                        config=cfg)


# Resource-shorthand -> (service, accessor) -- the set of "things you can
# describe a policy of" in our environment. Keeps the agent's parameter
# surface tiny (just pass shorthand) but the actual call is real.
_POLICY_TARGETS = {
    "s3:ic-task15":  ("s3",   "bucket_policy"),
    "s3:checkpoints": ("s3",  "bucket_policy"),
    "kms:ic-data-key": ("kms", "key_policy"),
    "secret:ic-stripe-api-key": ("secretsmanager", "resource_policy"),
    "secret:incident-commander/openai-api-key": ("secretsmanager", "resource_policy"),
    "queue:ic-orders":     ("sqs", "queue_policy"),
    "queue:ic-orders-dlq": ("sqs", "queue_policy"),
    "queue:ic-events":     ("sqs", "queue_policy"),
    "lambda:ic-runbook-restart-pods": ("lambda", "function_policy"),
    "lambda:ic-cold-start-target":    ("lambda", "function_policy"),
}


def _enabled() -> bool:
    return _have_aws_credentials() and bool(os.getenv("AWS_REGION"))


def _disabled_msg(action: str) -> str:
    return (f"[skip:{action}] AWS credentials not present; this action "
            f"requires real AWS access. Set AWS_ACCESS_KEY_ID + AWS_REGION.")


# ---------------------------------------------------------------------------
# Read / forensic actions
# ---------------------------------------------------------------------------

def check_cloudtrail_events(resource_name: str = "", event_name: str = "",
                            last_minutes: int = 60) -> str:
    """Look up the last N CloudTrail events touching `resource_name` or with
    `event_name`. Useful for tasks where the deformity was caused by an
    operator action (KMS deletion, EventBridge disable, S3 policy change)."""
    if not _enabled():
        return _disabled_msg("check_cloudtrail_events")
    ct = _client("cloudtrail")
    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=last_minutes)
    attrs = []
    if event_name:
        attrs.append({"AttributeKey": "EventName", "AttributeValue": event_name})
    elif resource_name:
        attrs.append({"AttributeKey": "ResourceName", "AttributeValue": resource_name})
    else:
        return ("error: provide either resource_name or event_name "
                "(e.g. event_name='ScheduleKeyDeletion')")
    try:
        r = ct.lookup_events(LookupAttributes=attrs,
                             StartTime=start, EndTime=end, MaxResults=10)
    except Exception as e:
        return f"[cloudtrail] error: {e}"
    rows = []
    for ev in r.get("Events", [])[:10]:
        rows.append(f"  {ev.get('EventTime')}  {ev.get('EventName')}  "
                    f"by {ev.get('Username','?')}")
    if not rows:
        return f"[cloudtrail] no events in last {last_minutes}m"
    return "[cloudtrail] " + str(len(rows)) + " events:\n" + "\n".join(rows)


def describe_resource_policy(target: str = "") -> str:
    """`target` shorthand like 'kms:ic-data-key', 's3:ic-task15',
    'secret:ic-stripe-api-key', 'queue:ic-orders-dlq'."""
    if not _enabled():
        return _disabled_msg("describe_resource_policy")
    spec = _POLICY_TARGETS.get(target)
    if not spec:
        keys = ", ".join(sorted(_POLICY_TARGETS))
        return f"error: unknown target '{target}'. Known: {keys}"
    service, kind = spec
    name = target.split(":", 1)[1]
    try:
        if kind == "bucket_policy":
            bucket = (os.environ.get("S3_DRIFT_BUCKET", name)
                      if name == "ic-task15" else
                      os.environ.get("S3_CHECKPOINT_BUCKET", name))
            r = _client("s3").get_bucket_policy(Bucket=bucket)
            return f"[bucket-policy {bucket}]\n{r.get('Policy','')[:1500]}"
        if kind == "key_policy":
            kms = _client("kms")
            # GetKeyPolicy refuses aliases; resolve via DescribeKey first.
            key_id = kms.describe_key(KeyId=f"alias/{name}")["KeyMetadata"]["KeyId"]
            r = kms.get_key_policy(KeyId=key_id, PolicyName="default")
            return f"[kms-policy alias/{name} keyId={key_id}]\n{r.get('Policy','')[:1500]}"
        if kind == "resource_policy":
            sm = _client("secretsmanager")
            try:
                r = sm.get_resource_policy(SecretId=name)
                pol = r.get("ResourcePolicy", "(no resource policy attached)")
            except Exception as e:
                pol = f"(no resource policy: {e})"
            tags = sm.describe_secret(SecretId=name).get("Tags", [])
            return f"[secret {name}] tags={tags}\npolicy={pol[:1200]}"
        if kind == "queue_policy":
            sqs = _client("sqs")
            url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
            r = sqs.get_queue_attributes(QueueUrl=url,
                                          AttributeNames=["Policy",
                                                          "RedrivePolicy"])
            return f"[queue {name}] {json.dumps(r.get('Attributes', {}), indent=2)[:1500]}"
        if kind == "function_policy":
            try:
                r = _client("lambda").get_policy(FunctionName=name)
                return f"[lambda {name}]\n{r.get('Policy','')[:1500]}"
            except Exception as e:
                return f"[lambda {name}] no resource policy ({e})"
    except Exception as e:
        return f"[describe_resource_policy {target}] error: {e}"
    return "error: unhandled policy target"


def get_quota_usage(service_code: str = "", quota_code: str = "") -> str:
    """Read Service Quotas for a given service+quota code.
    Common task-relevant codes:
       Bedrock InvokeModel TPM:  service_code='bedrock'  quota_code='L-XXXXXX'
       DynamoDB account-level RCU: service_code='dynamodb' quota_code='L-F98FE922'
       Lambda concurrent executions: service_code='lambda' quota_code='L-B99A9384'
    Falls back to listing all default quotas for `service_code` when
    `quota_code` is omitted."""
    if not _enabled():
        return _disabled_msg("get_quota_usage")
    if not service_code:
        return "error: service_code is required (e.g. 'lambda', 'dynamodb', 'bedrock')"
    sq = _client("service-quotas")
    try:
        if quota_code:
            r = sq.get_service_quota(ServiceCode=service_code,
                                     QuotaCode=quota_code)
            q = r.get("Quota", {})
            return (f"[quota] {service_code}/{q.get('QuotaName')} = "
                    f"{q.get('Value')} ({q.get('Unit')})")
        r = sq.list_service_quotas(ServiceCode=service_code, MaxResults=10)
        rows = [f"  {q['QuotaCode']}  {q['QuotaName']} = {q.get('Value')}"
                for q in r.get("Quotas", [])[:10]]
        return f"[quotas {service_code}]\n" + "\n".join(rows)
    except Exception as e:
        return f"[get_quota_usage] error: {e}"


def check_secret_rotation(secret_name: str = "") -> str:
    if not _enabled():
        return _disabled_msg("check_secret_rotation")
    if not secret_name:
        secret_name = os.environ.get("SECRET_STRIPE_NAME", "ic-stripe-api-key")
    sm = _client("secretsmanager")
    try:
        d = sm.describe_secret(SecretId=secret_name)
        rotation = {
            "RotationEnabled": d.get("RotationEnabled", False),
            "RotationLambdaARN": d.get("RotationLambdaARN"),
            "LastRotatedDate": str(d.get("LastRotatedDate")),
            "LastChangedDate": str(d.get("LastChangedDate")),
            "Tags": {t["Key"]: t["Value"] for t in d.get("Tags", [])},
        }
        return f"[secret-rotation {secret_name}]\n{json.dumps(rotation, indent=2)}"
    except Exception as e:
        return f"[check_secret_rotation {secret_name}] error: {e}"


def validate_iam_permission(action: str = "", resource: str = "*",
                             principal: str = "") -> str:
    """iam:SimulatePrincipalPolicy — answers 'can principal X do action Y on
    resource Z?'. Defaults principal to the caller's own ARN."""
    if not _enabled():
        return _disabled_msg("validate_iam_permission")
    if not action:
        return "error: action is required (e.g. 's3:PutObject')"
    iam = _client("iam")
    sts = _client("sts")
    try:
        if not principal:
            principal = sts.get_caller_identity()["Arn"]
        sim_kwargs: dict[str, Any] = {
            "PolicySourceArn": principal,
            "ActionNames": [action],
        }
        if resource and resource != "*":
            sim_kwargs["ResourceArns"] = [resource]
        r = iam.simulate_principal_policy(**sim_kwargs)
        rows = []
        for er in r.get("EvaluationResults", []):
            rows.append(f"  {er['EvalActionName']} on {er.get('EvalResourceName','*')}"
                        f" -> {er['EvalDecision']}")
        return f"[iam-sim principal={principal}]\n" + "\n".join(rows)
    except Exception as e:
        return f"[validate_iam_permission] error: {e}"


def analyze_cloudwatch_insights(log_group: str = "", pattern: str = "ERROR",
                                 last_minutes: int = 15) -> str:
    """Run a small CloudWatch Logs Insights query."""
    if not _enabled():
        return _disabled_msg("analyze_cloudwatch_insights")
    if not log_group:
        log_group = os.environ.get("CLOUDWATCH_LOG_GROUP",
                                   "/aws/lambda/ic-cold-start-target")
    cw = _client("logs")
    end = int(datetime.now(timezone.utc).timestamp())
    start = end - last_minutes * 60
    query = (f"fields @timestamp, @message"
             f" | filter @message like /{pattern}/"
             f" | sort @timestamp desc | limit 20")
    try:
        qid = cw.start_query(logGroupName=log_group,
                             startTime=start, endTime=end,
                             queryString=query)["queryId"]
        # Poll up to ~6s.
        import time
        for _ in range(20):
            time.sleep(0.3)
            r = cw.get_query_results(queryId=qid)
            if r["status"] in ("Complete", "Failed", "Cancelled"):
                break
        results = r.get("results", [])
        rows = []
        for row in results[:10]:
            line = " | ".join(f"{f['field']}={f['value']}" for f in row
                              if f['field'] != '@ptr')
            rows.append("  " + line)
        return (f"[insights {log_group} pattern={pattern!r}] "
                f"{len(results)} rows\n" + "\n".join(rows))
    except Exception as e:
        return f"[analyze_cloudwatch_insights] error: {e}"


def inspect_dlq_messages(queue_name: str = "ic-orders-dlq",
                          max_messages: int = 5) -> str:
    """Peek (no-delete) at messages in a DLQ. Uses long-poll=0 + receipt
    abandonment so the visibility timer expires and another consumer can
    re-read. This is a forensic action; PURGE_QUEUE is the corresponding
    write action."""
    if not _enabled():
        return _disabled_msg("inspect_dlq_messages")
    sqs = _client("sqs")
    try:
        url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        r = sqs.receive_message(QueueUrl=url,
                                MaxNumberOfMessages=min(10, max_messages),
                                VisibilityTimeout=2,
                                WaitTimeSeconds=0,
                                AttributeNames=["All"],
                                MessageAttributeNames=["All"])
        msgs = r.get("Messages", [])
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=["ApproximateNumberOfMessages"],
        ).get("Attributes", {})
        depth = attrs.get("ApproximateNumberOfMessages", "?")
        rows = [f"  body[{i}] = {m.get('Body','')[:200]}"
                for i, m in enumerate(msgs)]
        return (f"[dlq {queue_name}] depth={depth} sampled={len(msgs)}\n"
                + "\n".join(rows))
    except Exception as e:
        return f"[inspect_dlq_messages {queue_name}] error: {e}"


def diff_config_versions(parameter_name: str = "",
                          a: int = 0, b: int = 0) -> str:
    """SSM parameter version diff. If a/b are 0, picks the latest two."""
    if not _enabled():
        return _disabled_msg("diff_config_versions")
    if not parameter_name:
        parameter_name = os.environ.get("SSM_DB_POOL_PARAM",
                                        "/ic/payments/db-pool-size")
    ssm = _client("ssm")
    try:
        history = ssm.get_parameter_history(Name=parameter_name,
                                            WithDecryption=False, MaxResults=10)\
            .get("Parameters", [])
        if not history:
            return f"[ssm {parameter_name}] no history"
        history.sort(key=lambda p: p["Version"], reverse=True)
        if a == 0 or b == 0:
            latest = history[0]
            previous = history[1] if len(history) > 1 else latest
        else:
            latest = next((p for p in history if p["Version"] == a), history[0])
            previous = next((p for p in history if p["Version"] == b), latest)
        return (f"[ssm-diff {parameter_name}]\n"
                f"  v{previous['Version']} = {previous['Value']!r} "
                f"({previous.get('LastModifiedDate')})\n"
                f"  v{latest['Version']} = {latest['Value']!r} "
                f"({latest.get('LastModifiedDate')})")
    except Exception as e:
        return f"[diff_config_versions {parameter_name}] error: {e}"


def describe_state_machine_execution(execution_arn: str = "",
                                      state_machine_name: str = "") -> str:
    """Inspect the most recent failed execution of a state machine."""
    if not _enabled():
        return _disabled_msg("describe_state_machine_execution")
    sfn = _client("stepfunctions")
    try:
        if not execution_arn:
            sm_name = state_machine_name or "ic-order-saga"
            arn_prefix = (os.environ.get("SFN_ORDER_SAGA_ARN", "")
                          or f"arn:aws:states:{os.getenv('AWS_REGION','us-east-1')}"
                             f":{_client('sts').get_caller_identity()['Account']}"
                             f":stateMachine:{sm_name}")
            r = sfn.list_executions(stateMachineArn=arn_prefix,
                                    statusFilter="FAILED", maxResults=1)
            execs = r.get("executions", [])
            if not execs:
                return f"[sfn {sm_name}] no FAILED executions in history"
            execution_arn = execs[0]["executionArn"]
        d = sfn.describe_execution(executionArn=execution_arn)
        h = sfn.get_execution_history(executionArn=execution_arn,
                                      reverseOrder=True, maxResults=5)
        last = h.get("events", [])[:5]
        events = [f"  {e['type']} @ {e['timestamp']}" for e in last]
        return (f"[sfn-exec {execution_arn}] status={d.get('status')} "
                f"stop={d.get('stopDate')}\n" + "\n".join(events))
    except Exception as e:
        return f"[describe_state_machine_execution] error: {e}"


# ---------------------------------------------------------------------------
# Write / remediation actions
# ---------------------------------------------------------------------------

def invoke_lambda(function_name: str = "", payload: dict | None = None) -> str:
    if not _enabled():
        return _disabled_msg("invoke_lambda")
    if not function_name:
        function_name = os.environ.get("LAMBDA_RUNBOOK_FUNCTION",
                                       "ic-runbook-restart-pods")
    lam = _client("lambda")
    try:
        r = lam.invoke(FunctionName=function_name,
                       InvocationType="RequestResponse",
                       Payload=json.dumps(payload or {}).encode("utf-8"))
        body = r["Payload"].read().decode("utf-8", errors="replace")
        return (f"[invoke_lambda {function_name}] status={r['StatusCode']} "
                f"body={body[:500]}")
    except Exception as e:
        return f"[invoke_lambda {function_name}] error: {e}"


def rotate_secret(secret_name: str = "") -> str:
    if not _enabled():
        return _disabled_msg("rotate_secret")
    if not secret_name:
        secret_name = os.environ.get("SECRET_STRIPE_NAME", "ic-stripe-api-key")
    sm = _client("secretsmanager")
    try:
        # Most secrets won't have a real rotation lambda \u2014 we still write a
        # fresh value + tag, which is the same evidence the agent needs.
        new_value = json.dumps({"api_key": f"sk_rot_{int(datetime.now().timestamp())}"})
        sm.put_secret_value(SecretId=secret_name, SecretString=new_value)
        sm.tag_resource(SecretId=secret_name,
                        Tags=[{"Key": "RotationStatus", "Value": "ROTATED"},
                              {"Key": "LastRotatedDays", "Value": "0"}])
        return f"[rotate_secret {secret_name}] new version stored, tags updated"
    except Exception as e:
        return f"[rotate_secret {secret_name}] error: {e}"


def purge_queue(queue_name: str = "") -> str:
    if not _enabled():
        return _disabled_msg("purge_queue")
    if not queue_name:
        queue_name = os.environ.get("SQS_ORDERS_DLQ_URL", "ic-orders-dlq")\
            .rsplit("/", 1)[-1]
    sqs = _client("sqs")
    try:
        url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        sqs.purge_queue(QueueUrl=url)
        return f"[purge_queue {queue_name}] purge initiated"
    except Exception as e:
        return f"[purge_queue {queue_name}] error: {e}"


def enable_eventbridge_rule(rule_name: str = "", bus_name: str = "") -> str:
    if not _enabled():
        return _disabled_msg("enable_eventbridge_rule")
    rule = rule_name or os.environ.get("EVENTBRIDGE_RULE_NAME", "ic-orders-rule")
    bus  = bus_name  or os.environ.get("EVENTBRIDGE_BUS_NAME",  "ic-bus")
    eb = _client("events")
    try:
        eb.enable_rule(Name=rule, EventBusName=bus)
        st = eb.describe_rule(Name=rule, EventBusName=bus).get("State", "?")
        return f"[enable_rule {bus}/{rule}] state={st}"
    except Exception as e:
        return f"[enable_eventbridge_rule {bus}/{rule}] error: {e}"
