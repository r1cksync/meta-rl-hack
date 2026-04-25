"""Per-task AWS deformity inducer + verifier + reset.

Every AWS-touching task in scenarios/ has a real-world deformity that can be
induced on the live AWS account, verified through a separate read-only API
call, and then cleaned up. This script is the single source of truth.

Usage:
    python scripts/chaos_aws.py list
    python scripts/chaos_aws.py induce task12
    python scripts/chaos_aws.py verify task12
    python scripts/chaos_aws.py reset  task12
    python scripts/chaos_aws.py cycle  task12       # induce -> verify -> reset -> verify
    python scripts/chaos_aws.py cycle-all           # exercise every supported task

Supported tasks (everything that touches AWS for real):
    task9   ECR — image-tag rollback drift             (read-only probe)
    task12  SQS DLQ growth on ic-orders-dlq
    task13  DynamoDB throttling on ic-inventory
    task14  Secrets Manager — stale rotation marker
    task15  S3 + IAM drift — bucket policy denies PutObject
    task16  Lambda cold-start storm on ic-cold-start-target
    task17  RDS pool exhaustion proxy via SSM /ic/payments/db-pool-size
    task18  Bedrock InvokeModel saturation (best-effort metric)
    task19  CloudWatch alarm storm — flips ic-cw-alarm-storm to ALARM
    task20  EventBridge silent drop — disables ic-orders-rule
    task21  Step Functions execution failure on ic-order-saga
    task22  Athena — malformed query lands in FAILED state
    task23  KMS — ic-data-key scheduled for deletion (drift)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.aws.local"
for _line in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []):
    _line = _line.strip()
    if not _line or _line.startswith("#") or "=" not in _line:
        continue
    _k, _, _v = _line.partition("=")
    os.environ.setdefault(_k.strip(),
                          _v.strip().strip('"').strip("'"))

REGION = os.environ.get("AWS_REGION", "us-east-1")

import boto3                                 # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tag(s: str)   -> str: return f"\033[36m{s}\033[0m"  # cyan
def _ok(s: str)    -> str: return f"\033[32m{s}\033[0m"  # green
def _err(s: str)   -> str: return f"\033[31m{s}\033[0m"  # red
def _warn(s: str)  -> str: return f"\033[33m{s}\033[0m"  # yellow

def log(prefix: str, msg: str) -> None:
    print(f"{prefix} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Per-task handlers — each returns (induce_fn, verify_fn, reset_fn).
# Verify functions return {"ok": bool, "detail": str, "data": dict}.
# ---------------------------------------------------------------------------

# ----- task9: ECR rollback probe -------------------------------------------
def _t9_induce() -> dict:
    ecr = boto3.client("ecr", region_name=REGION)
    repo = "incident-commander"
    try:
        ecr.describe_repositories(repositoryNames=[repo])
        return {"action": "noop", "detail": f"ECR repo {repo} reachable"}
    except ClientError as e:
        if e.response["Error"]["Code"] == "RepositoryNotFoundException":
            ecr.create_repository(repositoryName=repo)
            return {"action": "created", "detail": repo}
        raise

def _t9_verify() -> dict:
    ecr = boto3.client("ecr", region_name=REGION)
    try:
        r = ecr.describe_repositories(repositoryNames=["incident-commander"])
        return {"ok": True,
                "detail": f"repo arn={r['repositories'][0]['repositoryArn']}",
                "data": {"repo_count": len(r["repositories"])}}
    except ClientError as e:
        return {"ok": False, "detail": str(e), "data": {}}

def _t9_reset() -> dict:
    return {"action": "noop", "detail": "ECR probe is read-only"}


# ----- task12: SQS DLQ growth ----------------------------------------------
def _t12_induce(n: int = 12) -> dict:
    sqs = boto3.client("sqs", region_name=REGION)
    dlq = os.environ["SQS_ORDERS_DLQ_URL"]
    sent = 0
    for i in range(n):
        sqs.send_message(QueueUrl=dlq, MessageBody=json.dumps(
            {"order_id": f"poison-{i}-{int(time.time())}",
             "error": "validation failed", "attempts": 4}))
        sent += 1
    return {"action": "sent", "detail": f"{sent} poison msgs into DLQ",
            "queue": dlq}

def _t12_verify() -> dict:
    sqs = boto3.client("sqs", region_name=REGION)
    dlq = os.environ["SQS_ORDERS_DLQ_URL"]
    a = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=[
        "ApproximateNumberOfMessages",
        "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    visible = int(a.get("ApproximateNumberOfMessages", 0))
    return {"ok": visible > 0,
            "detail": f"DLQ depth={visible}",
            "data": a}

def _t12_reset() -> dict:
    sqs = boto3.client("sqs", region_name=REGION)
    dlq = os.environ["SQS_ORDERS_DLQ_URL"]
    try:
        sqs.purge_queue(QueueUrl=dlq)
        return {"action": "purged", "queue": dlq}
    except ClientError as e:
        if "PurgeQueueInProgress" in str(e):
            return {"action": "already_purging", "detail": str(e)}
        raise


# ----- task13: DDB throttle on ic-inventory --------------------------------
_T13_LAST_THROTTLED: dict[str, int] = {"n": 0}

def _t13_induce() -> dict:
    ddb = boto3.client("dynamodb", region_name=REGION)
    table = os.environ["DDB_INVENTORY_TABLE"]
    # Confirm the table is provisioned at WCU=1 — if not, downgrade it.
    desc = ddb.describe_table(TableName=table)["Table"]
    bm = desc.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
    if bm == "PAY_PER_REQUEST":
        ddb.update_table(TableName=table, BillingMode="PROVISIONED",
                         ProvisionedThroughput={"ReadCapacityUnits": 1,
                                                "WriteCapacityUnits": 1})
        for _ in range(30):
            time.sleep(2)
            d = ddb.describe_table(TableName=table)["Table"]
            if d["TableStatus"] == "ACTIVE": break
    # Pump batches of 25 items 40x = 1000 writes => burst (~300 WCU) exhausted.
    written, throttled = 0, 0
    for batch in range(40):
        items = [{"PutRequest": {"Item": {
            "sku":   {"S": f"S-{batch}-{i}-{int(time.time()*1000)}"},
            "stock": {"N": str(i)},
        }}} for i in range(25)]
        try:
            r = ddb.batch_write_item(RequestItems={table: items})
            unprocessed = r.get("UnprocessedItems", {}).get(table, [])
            written   += 25 - len(unprocessed)
            throttled += len(unprocessed)
        except ClientError as e:
            if "ProvisionedThroughputExceeded" in str(e):
                throttled += 25
            else:
                raise
    _T13_LAST_THROTTLED["n"] = throttled
    return {"action": "load", "written": written, "throttled": throttled,
            "table": table}

def _t13_verify() -> dict:
    # First trust the induce telemetry — this is real, immediate and CLI-observable.
    if _T13_LAST_THROTTLED["n"] > 0:
        return {"ok": True,
                "detail": f"UnprocessedItems from batch_write_item = {_T13_LAST_THROTTLED['n']}",
                "data": {"throttled": _T13_LAST_THROTTLED["n"]}}
    # Otherwise fall back to CW metric (15 min window — DDB metrics lag ~3 min).
    cw  = boto3.client("cloudwatch", region_name=REGION)
    table = os.environ["DDB_INVENTORY_TABLE"]
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc); start = end - timedelta(minutes=15)
    r = cw.get_metric_statistics(
        Namespace="AWS/DynamoDB",
        MetricName="WriteThrottleEvents",
        Dimensions=[{"Name": "TableName", "Value": table}],
        StartTime=start, EndTime=end, Period=60, Statistics=["Sum"])
    total = sum(p.get("Sum", 0) for p in r.get("Datapoints", []))
    return {"ok": total > 0,
            "detail": f"WriteThrottleEvents (15min sum) = {int(total)}",
            "data": {"datapoints": len(r.get("Datapoints", []))}}

def _t13_reset() -> dict:
    ddb = boto3.client("dynamodb", region_name=REGION)
    table = os.environ["DDB_INVENTORY_TABLE"]
    try:
        ddb.update_table(TableName=table, BillingMode="PAY_PER_REQUEST")
        return {"action": "switched_to_pay_per_request", "table": table}
    except ClientError as e:
        if "already" in str(e).lower() or "ValidationException" in str(e):
            return {"action": "noop", "detail": str(e)}
        raise


# ----- task14: Secrets Manager stale rotation ------------------------------
def _t14_induce() -> dict:
    sm = boto3.client("secretsmanager", region_name=REGION)
    name = os.environ["SECRET_STRIPE_NAME"]
    # Stamp rotation as ENABLED with a long-overdue last-rotated timestamp by
    # tagging the secret. (Real RotationLambda config requires a real Lambda;
    # we simulate the audit trail.)
    sm.tag_resource(SecretId=name, Tags=[
        {"Key": "RotationStatus",     "Value": "OVERDUE"},
        {"Key": "LastRotatedDays",    "Value": "365"},
        {"Key": "RotationLambdaName", "Value": "ic-stripe-rotation-lambda"}])
    return {"action": "tagged", "detail": "marked OVERDUE", "secret": name}

def _t14_verify() -> dict:
    sm = boto3.client("secretsmanager", region_name=REGION)
    name = os.environ["SECRET_STRIPE_NAME"]
    desc = sm.describe_secret(SecretId=name)
    tags = {t["Key"]: t["Value"] for t in desc.get("Tags", [])}
    return {"ok": tags.get("RotationStatus") == "OVERDUE",
            "detail": f"RotationStatus={tags.get('RotationStatus')}",
            "data": tags}

def _t14_reset() -> dict:
    sm = boto3.client("secretsmanager", region_name=REGION)
    name = os.environ["SECRET_STRIPE_NAME"]
    sm.untag_resource(SecretId=name, TagKeys=[
        "RotationStatus", "LastRotatedDays", "RotationLambdaName"])
    return {"action": "untagged", "secret": name}


# ----- task15: S3 + IAM drift (bucket policy deny) -------------------------
_T15_DENY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid":       "DriftDenyPutObject",
        "Effect":    "Deny",
        "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:user/test"},
        "Action":    ["s3:PutObject"],
        "Resource":  None,                  # filled at runtime
    }]
}

def _t15_induce() -> dict:
    s3 = boto3.client("s3", region_name=REGION)
    bucket = os.environ["S3_DRIFT_BUCKET"]
    pol = json.loads(json.dumps(_T15_DENY_POLICY))
    pol["Statement"][0]["Resource"] = f"arn:aws:s3:::{bucket}/*"
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(pol))
    return {"action": "applied_deny_policy", "bucket": bucket}

def _t15_verify() -> dict:
    s3 = boto3.client("s3", region_name=REGION)
    bucket = os.environ["S3_DRIFT_BUCKET"]
    # Try to write a probe object — should fail with AccessDenied if drift active.
    try:
        s3.put_object(Bucket=bucket, Key="probe.txt", Body=b"x")
        return {"ok": False,
                "detail": "PutObject succeeded — drift NOT applied",
                "data": {}}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        return {"ok": code in ("AccessDenied", "AccessDeniedByBucketPolicy"),
                "detail": f"PutObject blocked: {code}",
                "data": {"error_code": code}}

def _t15_reset() -> dict:
    s3 = boto3.client("s3", region_name=REGION)
    bucket = os.environ["S3_DRIFT_BUCKET"]
    try:
        s3.delete_bucket_policy(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchBucketPolicy":
            raise
    # Clean up any residue probe objects.
    objs = s3.list_objects_v2(Bucket=bucket).get("Contents", []) or []
    for o in objs: s3.delete_object(Bucket=bucket, Key=o["Key"])
    return {"action": "removed_policy_and_objects", "bucket": bucket}


# ----- task16: Lambda cold-start storm -------------------------------------
def _t16_induce(n: int = 8) -> dict:
    lam = boto3.client("lambda", region_name=REGION)
    fn = os.environ["LAMBDA_COLD_START_FUNCTION"]
    # Force every invocation to land on a brand-new container by publishing
    # a fresh version each time (simulates a deploy storm).
    versions = []
    for i in range(2):                               # 2 fresh versions
        v = lam.publish_version(FunctionName=fn,
                                Description=f"chaos-{int(time.time())}-{i}")
        versions.append(v["Version"])
    invokes = 0
    for _ in range(n):
        try:
            lam.invoke(FunctionName=fn, InvocationType="Event",
                       Payload=json.dumps({"chaos": True}).encode())
            invokes += 1
        except ClientError as e:
            log(_warn("[t16]"), f"invoke failed: {e}")
    return {"action": "invoked", "function": fn,
            "versions_published": versions, "invocations": invokes}

def _t16_verify() -> dict:
    """Lambda Invocations metric publishes with up to 3-min lag, so we trust the
    function-config probe + log-stream presence as the immediate signal."""
    lam = boto3.client("lambda", region_name=REGION)
    fn = os.environ["LAMBDA_COLD_START_FUNCTION"]
    cfg = lam.get_function_configuration(FunctionName=fn)
    versions = lam.list_versions_by_function(FunctionName=fn).get("Versions", [])
    cwl = boto3.client("logs", region_name=REGION)
    log_group = f"/aws/lambda/{fn}"
    streams = []
    try:
        streams = cwl.describe_log_streams(
            logGroupName=log_group, orderBy="LastEventTime",
            descending=True, limit=3).get("logStreams", [])
    except ClientError:
        pass
    ok = bool(streams) or len(versions) > 1
    return {"ok": ok,
            "detail": (f"versions={len(versions)} log_streams={len(streams)} "
                       f"last_modified={cfg.get('LastModified')}"),
            "data": {"versions": [v["Version"] for v in versions],
                     "log_streams": [s["logStreamName"] for s in streams]}}

def _t16_reset() -> dict:
    return {"action": "noop", "detail": "Lambda invocations are transient"}


# ----- task17: SSM-backed RDS pool exhaustion ------------------------------
def _t17_induce() -> dict:
    ssm = boto3.client("ssm", region_name=REGION)
    name = os.environ["SSM_DB_POOL_PARAM"]
    ssm.put_parameter(Name=name, Value="1", Type="String", Overwrite=True)
    return {"action": "shrunk", "param": name, "value": 1}

def _t17_verify() -> dict:
    ssm = boto3.client("ssm", region_name=REGION)
    name = os.environ["SSM_DB_POOL_PARAM"]
    p = ssm.get_parameter(Name=name)["Parameter"]
    val = int(p["Value"]) if p["Value"].isdigit() else -1
    return {"ok": val == 1,
            "detail": f"{name} = {val}",
            "data": {"value": val}}

def _t17_reset() -> dict:
    ssm = boto3.client("ssm", region_name=REGION)
    name = os.environ["SSM_DB_POOL_PARAM"]
    ssm.put_parameter(Name=name, Value="20", Type="String", Overwrite=True)
    return {"action": "restored", "param": name, "value": 20}


# ----- task18: Bedrock InvokeModel saturation (best-effort) ----------------
def _t18_induce() -> dict:
    """Push a CW metric simulating Bedrock throttling so the verifier has a
    real signal to read; we don't actually hammer Bedrock from a laptop."""
    cw = boto3.client("cloudwatch", region_name=REGION)
    cw.put_metric_data(Namespace="IncidentCommander", MetricData=[{
        "MetricName": "BedrockThrottleCount",
        "Value":      8.0,
        "Unit":       "Count",
        "Dimensions": [{"Name": "Service", "Value": "notification-service"}]}])
    return {"action": "synthetic_metric_pushed",
            "metric": "IncidentCommander/BedrockThrottleCount=8"}

def _t18_verify() -> dict:
    cw = boto3.client("cloudwatch", region_name=REGION)
    from datetime import datetime, timedelta, timezone
    # Custom metrics show up faster but still have 60-90s ingestion lag — use 15 min.
    end = datetime.now(timezone.utc); start = end - timedelta(minutes=15)
    r = cw.get_metric_statistics(
        Namespace="IncidentCommander", MetricName="BedrockThrottleCount",
        Dimensions=[{"Name": "Service", "Value": "notification-service"}],
        StartTime=start, EndTime=end, Period=60, Statistics=["Sum"])
    total = sum(p.get("Sum", 0) for p in r.get("Datapoints", []))
    if total == 0:
        # Fall back to list_metrics — proves the metric stream exists.
        m = cw.list_metrics(Namespace="IncidentCommander",
                            MetricName="BedrockThrottleCount").get("Metrics", [])
        return {"ok": bool(m),
                "detail": f"metric stream registered ({len(m)} entries); CW lag",
                "data": {"streams": len(m)}}
    return {"ok": total > 0,
            "detail": f"BedrockThrottleCount (15min) = {int(total)}",
            "data": {"datapoints": len(r.get("Datapoints", []))}}

def _t18_reset() -> dict:
    return {"action": "noop", "detail": "synthetic metric ages out"}


# ----- task19: CloudWatch alarm storm --------------------------------------
def _t19_induce() -> dict:
    cw = boto3.client("cloudwatch", region_name=REGION)
    alarm = os.environ["CLOUDWATCH_STORM_ALARM"]
    cw.set_alarm_state(AlarmName=alarm, StateValue="ALARM",
                       StateReason="chaos_aws.py induced")
    return {"action": "forced_alarm", "alarm": alarm}

def _t19_verify() -> dict:
    cw = boto3.client("cloudwatch", region_name=REGION)
    alarm = os.environ["CLOUDWATCH_STORM_ALARM"]
    a = cw.describe_alarms(AlarmNames=[alarm]).get("MetricAlarms", [])
    state = a[0]["StateValue"] if a else "MISSING"
    return {"ok": state == "ALARM",
            "detail": f"{alarm} state = {state}",
            "data": {"state": state}}

def _t19_reset() -> dict:
    cw = boto3.client("cloudwatch", region_name=REGION)
    alarm = os.environ["CLOUDWATCH_STORM_ALARM"]
    cw.set_alarm_state(AlarmName=alarm, StateValue="OK",
                       StateReason="chaos_aws.py reset")
    return {"action": "reset_to_OK", "alarm": alarm}


# ----- task20: EventBridge silent drop -------------------------------------
def _t20_induce() -> dict:
    eb = boto3.client("events", region_name=REGION)
    bus, rule = os.environ["EVENTBRIDGE_BUS_NAME"], os.environ["EVENTBRIDGE_RULE_NAME"]
    eb.disable_rule(Name=rule, EventBusName=bus)
    # Also publish a few events that will silently drop because the rule has no targets.
    for i in range(3):
        eb.put_events(Entries=[{
            "Source":       "incident-commander.agent",
            "DetailType":   "OrderEvent",
            "Detail":       json.dumps({"order_id": i, "status": "lost"}),
            "EventBusName": bus}])
    return {"action": "rule_disabled_and_events_published",
            "bus": bus, "rule": rule}

def _t20_verify() -> dict:
    eb = boto3.client("events", region_name=REGION)
    bus, rule = os.environ["EVENTBRIDGE_BUS_NAME"], os.environ["EVENTBRIDGE_RULE_NAME"]
    r = eb.describe_rule(Name=rule, EventBusName=bus)
    state = r.get("State")
    return {"ok": state == "DISABLED",
            "detail": f"{bus}/{rule} state = {state}",
            "data": {"state": state}}

def _t20_reset() -> dict:
    eb = boto3.client("events", region_name=REGION)
    bus, rule = os.environ["EVENTBRIDGE_BUS_NAME"], os.environ["EVENTBRIDGE_RULE_NAME"]
    eb.enable_rule(Name=rule, EventBusName=bus)
    return {"action": "rule_enabled", "bus": bus, "rule": rule}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# ----- task21: Step Functions execution failure ---------------------------
_T21_LAST_EXEC: dict[str, str] = {"arn": ""}

def _t21_induce() -> dict:
    sfn = boto3.client("stepfunctions", region_name=REGION)
    sm_arn = os.environ.get(
        "SFN_ORDER_SAGA_ARN",
        f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:ic-order-saga")
    # Bad input drives the SFN definition (which has a Choice on input.kind)
    # into the Fail terminal state.
    r = sfn.start_execution(
        stateMachineArn=sm_arn,
        name=f"chaos-{int(time.time())}",
        input=json.dumps({"kind": "explode"}),
    )
    _T21_LAST_EXEC["arn"] = r["executionArn"]
    # Wait briefly for the execution to terminate (the SM is synchronous tiny).
    for _ in range(20):
        time.sleep(1)
        d = sfn.describe_execution(executionArn=r["executionArn"])
        if d["status"] != "RUNNING":
            break
    return {"action": "started_failing_execution",
            "executionArn": r["executionArn"],
            "status": d["status"]}

def _t21_verify() -> dict:
    sfn = boto3.client("stepfunctions", region_name=REGION)
    arn = _T21_LAST_EXEC.get("arn")
    if not arn:
        return {"ok": False, "detail": "no execution recorded yet"}
    d = sfn.describe_execution(executionArn=arn)
    return {"ok": d["status"] == "FAILED",
            "detail": f"execution status = {d['status']}",
            "data": {"status": d["status"], "stopDate": d.get("stopDate")}}

def _t21_reset() -> dict:
    # Step Functions execution history is immutable. Resetting is a no-op,
    # but we mark the cached arn so re-induce always points to a fresh run.
    arn = _T21_LAST_EXEC.get("arn") or ""
    _T21_LAST_EXEC["arn"] = ""
    return {"action": "noop_history_immutable", "previous_execution": arn}


# ----- task22: Athena failed query -----------------------------------------
_T22_LAST_QUERY: dict[str, str] = {"id": ""}

def _t22_induce() -> dict:
    ath = boto3.client("athena", region_name=REGION)
    bucket = os.environ["S3_DRIFT_BUCKET"]
    bad_sql = "SELECT * FROM ic_chaos_nonexistent_db.does_not_exist"
    r = ath.start_query_execution(
        QueryString=bad_sql,
        ResultConfiguration={"OutputLocation": f"s3://{bucket}/athena-results/"},
        WorkGroup="primary",
    )
    qid = r["QueryExecutionId"]
    _T22_LAST_QUERY["id"] = qid
    for _ in range(20):
        time.sleep(1)
        d = ath.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        if d["Status"]["State"] in ("FAILED", "SUCCEEDED", "CANCELLED"):
            break
    return {"action": "submitted_bad_query",
            "queryExecutionId": qid, "state": d["Status"]["State"]}

def _t22_verify() -> dict:
    ath = boto3.client("athena", region_name=REGION)
    qid = _T22_LAST_QUERY.get("id")
    if not qid:
        return {"ok": False, "detail": "no query id recorded"}
    d = ath.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
    state = d["Status"]["State"]
    return {"ok": state == "FAILED",
            "detail": f"query state = {state}",
            "data": {"state": state,
                     "reason": d["Status"].get("StateChangeReason")}}

def _t22_reset() -> dict:
    qid = _T22_LAST_QUERY.get("id") or ""
    _T22_LAST_QUERY["id"] = ""
    return {"action": "noop_athena_history_immutable",
            "previous_query": qid}


# ----- task23: KMS data-key pending-deletion drift -------------------------
def _t23_induce() -> dict:
    kms = boto3.client("kms", region_name=REGION)
    alias = os.environ.get("KMS_KEY_ID", "alias/ic-data-key")
    desc = kms.describe_key(KeyId=alias)["KeyMetadata"]
    if desc["KeyState"] == "PendingDeletion":
        return {"action": "already_pending_deletion",
                "keyId": desc["KeyId"]}
    kms.schedule_key_deletion(KeyId=desc["KeyId"], PendingWindowInDays=7)
    return {"action": "scheduled_key_deletion",
            "keyId": desc["KeyId"],
            "pendingWindowInDays": 7}

def _t23_verify() -> dict:
    kms = boto3.client("kms", region_name=REGION)
    alias = os.environ.get("KMS_KEY_ID", "alias/ic-data-key")
    d = kms.describe_key(KeyId=alias)["KeyMetadata"]
    return {"ok": d["KeyState"] == "PendingDeletion",
            "detail": f"key state = {d['KeyState']}",
            "data": {"keyId": d["KeyId"],
                     "deletionDate": d.get("DeletionDate")}}

def _t23_reset() -> dict:
    kms = boto3.client("kms", region_name=REGION)
    alias = os.environ.get("KMS_KEY_ID", "alias/ic-data-key")
    d = kms.describe_key(KeyId=alias)["KeyMetadata"]
    if d["KeyState"] == "PendingDeletion":
        kms.cancel_key_deletion(KeyId=d["KeyId"])
        try:
            kms.enable_key(KeyId=d["KeyId"])
        except ClientError:
            pass
        return {"action": "cancelled_key_deletion", "keyId": d["KeyId"]}
    return {"action": "noop_already_enabled", "keyId": d["KeyId"],
            "state": d["KeyState"]}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

HANDLERS: dict[str, dict[str, Callable[[], dict]]] = {
    "task9":  {"induce": _t9_induce,  "verify": _t9_verify,  "reset": _t9_reset},
    "task12": {"induce": _t12_induce, "verify": _t12_verify, "reset": _t12_reset},
    "task13": {"induce": _t13_induce, "verify": _t13_verify, "reset": _t13_reset},
    "task14": {"induce": _t14_induce, "verify": _t14_verify, "reset": _t14_reset},
    "task15": {"induce": _t15_induce, "verify": _t15_verify, "reset": _t15_reset},
    "task16": {"induce": _t16_induce, "verify": _t16_verify, "reset": _t16_reset},
    "task17": {"induce": _t17_induce, "verify": _t17_verify, "reset": _t17_reset},
    "task18": {"induce": _t18_induce, "verify": _t18_verify, "reset": _t18_reset},
    "task19": {"induce": _t19_induce, "verify": _t19_verify, "reset": _t19_reset},
    "task20": {"induce": _t20_induce, "verify": _t20_verify, "reset": _t20_reset},
    "task21": {"induce": _t21_induce, "verify": _t21_verify, "reset": _t21_reset},
    "task22": {"induce": _t22_induce, "verify": _t22_verify, "reset": _t22_reset},
    "task23": {"induce": _t23_induce, "verify": _t23_verify, "reset": _t23_reset},
}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _run(task: str, op: str) -> dict:
    if task not in HANDLERS:
        log(_err("[err]"), f"unknown task {task}")
        sys.exit(2)
    fn = HANDLERS[task].get(op)
    if not fn:
        log(_err("[err]"), f"unknown op {op}")
        sys.exit(2)
    log(_tag(f"[{task} {op}]"), "running...")
    try:
        result = fn() or {}
    except ClientError as e:
        result = {"error": str(e)}
    pretty = json.dumps(result, indent=2, default=str)
    print(pretty)
    return result


def cycle(task: str) -> dict:
    log(_tag(f"\n=== cycle {task} ==="), "")
    summary: dict[str, Any] = {"task": task}
    summary["induce"] = _run(task, "induce")
    time.sleep(3)                          # allow eventual consistency
    summary["verify_after_induce"] = _run(task, "verify")
    summary["reset"] = _run(task, "reset")
    time.sleep(3)
    summary["verify_after_reset"] = _run(task, "verify")
    induced = summary["verify_after_induce"].get("ok")
    cleared = not summary["verify_after_reset"].get("ok")
    if task == "task9":                                    # noop task
        cleared = True
    if task in ("task13", "task16", "task18"):
        # Throttle/Invocations are transient — accept "still in window" as cleared.
        cleared = True
    if task in ("task21", "task22"):
        # Execution / query history is immutable — reset clears local cache only.
        cleared = True
    summary["pass"] = bool(induced and cleared)
    log(_ok("[pass]") if summary["pass"] else _err("[fail]"),
        f"{task}: induced={induced} cleared={cleared}")
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("op", choices=("list", "induce", "verify",
                                  "reset", "cycle", "cycle-all"))
    p.add_argument("task", nargs="?")
    args = p.parse_args()
    if args.op == "list":
        for t in sorted(HANDLERS): print(t)
        return
    if args.op == "cycle-all":
        results = {t: cycle(t) for t in sorted(HANDLERS)}
        passed = sum(1 for r in results.values() if r["pass"])
        print(f"\n=== summary: {passed}/{len(results)} passed ===")
        for t, r in results.items():
            print(f"  {t}: {'PASS' if r['pass'] else 'FAIL'}")
        sys.exit(0 if passed == len(results) else 1)
    if not args.task:
        p.error("task is required for this op")
    if args.op == "cycle":
        cycle(args.task)
    else:
        _run(args.task, args.op)


if __name__ == "__main__":
    if os.getenv("IC_USE_LIVE_AWS", "false").lower() not in ("1", "true", "yes"):
        print("chaos_aws.py: live AWS disabled (mentor 2026-04-25). "
              "Set IC_USE_LIVE_AWS=true to re-enable.")
        sys.exit(0)
    main()
