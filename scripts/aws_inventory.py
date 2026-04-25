"""Inventory + provisioner for every AWS resource the RL env needs.

Replaces the broken bundled AWS CLI on this machine. Reads .env.aws.local,
then either lists existing resources (default) or provisions whatever is
missing (`--provision`). Idempotent — safe to re-run.

Usage:
    python scripts/aws_inventory.py                # list only (no writes)
    python scripts/aws_inventory.py --provision    # create whatever is missing
    python scripts/aws_inventory.py --teardown-extras   # delete only the extras we added (NOT EKS/S3 etc.)

Resources we care about
-----------------------
Existing (managed by Terraform):
  * S3 bucket            ic-checkpoints-<acct>-<region>
  * DynamoDB table       incident-commander-curriculum
  * CloudWatch log group /aws/eks/incident-commander/application
  * SNS topic            incident-commander-alerts
  * Secrets Manager      incident-commander/openai-api-key
  * Lambda               incident-commander-alarm-hook
  * EKS cluster          incident-commander
  * ECR repo             incident-commander

Extras for the new tasks (provisioned here, not in main.tf):
  * SQS queue                ic-events
  * SQS DLQ + main queue     ic-orders, ic-orders-dlq        (task12)
  * DynamoDB table           ic-inventory                    (task13)
  * Secrets Manager secret   ic-stripe-api-key               (task14)
  * S3 bucket                ic-task15-drift-bucket-<acct>   (task15)
  * Lambda function          ic-cold-start-target            (task16)
  * RDS-like SSM param       /ic/payments/db-pool-size       (task17)
  * Bedrock IAM probe        (no resource — verified via list)
  * CloudWatch alarm         ic-cw-alarm-storm               (task19)
  * EventBridge bus + rule   ic-bus / ic-orders-rule         (task20)
  * KMS key alias            alias/ic-data-key
  * SSM Parameter            /ic/feature-flags/enable_chaos
  * Lambda runbook           ic-runbook-restart-pods
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: read .env.aws.local (parent dir) into os.environ before boto3.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.aws.local"
for line in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    v = v.strip().strip('"').strip("'")
    os.environ.setdefault(k.strip(), v)

REGION = os.environ.get("AWS_REGION", "us-east-1")

import boto3                        # noqa: E402
from botocore.exceptions import ClientError, EndpointConnectionError  # noqa: E402

ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
TAGS = [
    {"Key": "Project",   "Value": "incident-commander"},
    {"Key": "ManagedBy", "Value": "scripts/aws_inventory.py"},
    {"Key": "Purpose",   "Value": "rl-env"},
]


# ---------------------------------------------------------------------------
# Pretty status helpers
# ---------------------------------------------------------------------------

def _ok(msg: str)   -> None: print(f"  [OK]      {msg}")
def _miss(msg: str) -> None: print(f"  [MISSING] {msg}")
def _act(msg: str)  -> None: print(f"  [+]       {msg}")
def _warn(msg: str) -> None: print(f"  [warn]    {msg}")
def _err(msg: str)  -> None: print(f"  [error]   {msg}")
def hdr(s: str)     -> None: print(f"\n=== {s} ===")


# ---------------------------------------------------------------------------
# Resource desired-state spec — "extras" only; main TF handles the rest.
# ---------------------------------------------------------------------------

EXTRAS: dict[str, dict] = {
    "sqs_main":      {"name": "ic-events"},
    "sqs_orders":    {"name": "ic-orders"},
    "sqs_orders_dlq":{"name": "ic-orders-dlq"},
    "ddb_inventory": {"table": "ic-inventory"},
    "secret_stripe": {"name": "ic-stripe-api-key"},
    "s3_drift":      {"bucket": f"ic-task15-drift-{ACCOUNT}-{REGION}"},
    "lambda_cold":   {"name": "ic-cold-start-target"},
    "lambda_runbook":{"name": "ic-runbook-restart-pods"},
    "ssm_pool":      {"name": "/ic/payments/db-pool-size"},
    "ssm_flag":      {"name": "/ic/feature-flags/enable_chaos"},
    "alarm_storm":   {"name": "ic-cw-alarm-storm"},
    "eb_bus":        {"name": "ic-bus"},
    "eb_rule":       {"name": "ic-orders-rule"},
    "kms_alias":     {"alias": "alias/ic-data-key"},
    "sfn_saga":      {"name": "ic-order-saga"},
}


# ---------------------------------------------------------------------------
# Inventory + provisioning
# ---------------------------------------------------------------------------

def inventory(provision: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"account": ACCOUNT, "region": REGION,
                           "existing": {}, "created": [], "errors": []}

    # ---- S3 bucket (Terraform-managed) ----------------------------------
    hdr("S3 — checkpoint bucket")
    s3 = boto3.client("s3", region_name=REGION)
    bucket = os.environ.get("S3_CHECKPOINT_BUCKET",
                            f"ic-checkpoints-{ACCOUNT}-{REGION}")
    try:
        s3.head_bucket(Bucket=bucket)
        out["existing"]["s3_checkpoints"] = bucket
        _ok(f"s3://{bucket}")
    except ClientError as e:
        _miss(f"s3://{bucket} ({e.response['Error']['Code']})")
        out["errors"].append(f"s3 missing: {bucket}")

    # ---- DynamoDB curriculum (Terraform) --------------------------------
    hdr("DynamoDB — curriculum table")
    ddb = boto3.client("dynamodb", region_name=REGION)
    try:
        ddb.describe_table(TableName="incident-commander-curriculum")
        _ok("incident-commander-curriculum")
        out["existing"]["ddb_curriculum"] = "incident-commander-curriculum"
    except ClientError:
        _miss("incident-commander-curriculum")
        if provision:
            ddb.create_table(
                TableName="incident-commander-curriculum",
                BillingMode="PAY_PER_REQUEST",
                KeySchema=[
                    {"AttributeName": "run_id",  "KeyType": "HASH"},
                    {"AttributeName": "task_id", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "run_id",  "AttributeType": "S"},
                    {"AttributeName": "task_id", "AttributeType": "S"},
                ],
                Tags=TAGS,
            )
            _act("created incident-commander-curriculum (PPR)")
            out["created"].append("incident-commander-curriculum")

    # ---- CloudWatch log group (Terraform) -------------------------------
    hdr("CloudWatch Logs")
    cwl = boto3.client("logs", region_name=REGION)
    lg = os.environ.get("CLOUDWATCH_LOG_GROUP",
                        "/aws/eks/incident-commander/application")
    try:
        resp = cwl.describe_log_groups(logGroupNamePrefix=lg, limit=1)
        if resp.get("logGroups"):
            _ok(lg)
            out["existing"]["log_group"] = lg
        else:
            _miss(lg)
            if provision:
                cwl.create_log_group(logGroupName=lg)
                _act(f"created {lg}")
                out["created"].append(lg)
    except ClientError as e:
        _err(f"logs: {e}")

    # ---- SNS alerts (Terraform) -----------------------------------------
    hdr("SNS")
    sns = boto3.client("sns", region_name=REGION)
    topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT}:incident-commander-alerts"
    try:
        sns.get_topic_attributes(TopicArn=topic_arn)
        _ok(topic_arn)
        out["existing"]["sns_alerts"] = topic_arn
    except ClientError:
        _miss(topic_arn)
        if provision:
            r = sns.create_topic(Name="incident-commander-alerts",
                                 Tags=TAGS)
            _act(r["TopicArn"]); out["created"].append(r["TopicArn"])

    # ---- Secrets Manager (Terraform openai + extras stripe) -------------
    hdr("Secrets Manager")
    sm = boto3.client("secretsmanager", region_name=REGION)
    for sname in ("incident-commander/openai-api-key",
                  EXTRAS["secret_stripe"]["name"]):
        try:
            sm.describe_secret(SecretId=sname)
            _ok(sname); out["existing"].setdefault("secrets", []).append(sname)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                _err(f"{sname}: {e}"); continue
            _miss(sname)
            if provision:
                # The openai key value is set out-of-band; we just create the secret container.
                r = sm.create_secret(
                    Name=sname,
                    Description="RL env scenario credential (rotated by RotationLambda)",
                    SecretString=json.dumps({"api_key": "sk_test_dummy_v1"}),
                    Tags=TAGS,
                )
                _act(r["ARN"]); out["created"].append(r["ARN"])

    # ---- Lambda (Terraform alarm-hook + extras) -------------------------
    hdr("Lambda")
    lam = boto3.client("lambda", region_name=REGION)
    for fname in ("incident-commander-alarm-hook",
                  EXTRAS["lambda_cold"]["name"],
                  EXTRAS["lambda_runbook"]["name"]):
        try:
            lam.get_function(FunctionName=fname)
            _ok(fname); out["existing"].setdefault("lambdas", []).append(fname)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                _err(f"{fname}: {e}"); continue
            _miss(fname)
            if provision:
                _create_minimal_lambda(lam, fname, out)

    # ---- SQS queues -----------------------------------------------------
    hdr("SQS")
    sqs = boto3.client("sqs", region_name=REGION)
    existing_qs = {q.split("/")[-1]: q for q in
                   sqs.list_queues().get("QueueUrls", [])}
    desired = ["ic-events", "ic-orders", "ic-orders-dlq"]
    for q in desired:
        if q in existing_qs:
            _ok(existing_qs[q]); out["existing"].setdefault("sqs", []).append(existing_qs[q])
        else:
            _miss(q)
            if provision:
                url = sqs.create_queue(QueueName=q)["QueueUrl"]
                sqs.tag_queue(QueueUrl=url,
                              Tags={t["Key"]: t["Value"] for t in TAGS})
                _act(url); out["created"].append(url)
                existing_qs[q] = url
    # Wire DLQ redrive policy ic-orders -> ic-orders-dlq
    if provision and "ic-orders" in existing_qs and "ic-orders-dlq" in existing_qs:
        try:
            dlq_arn = sqs.get_queue_attributes(
                QueueUrl=existing_qs["ic-orders-dlq"],
                AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            sqs.set_queue_attributes(
                QueueUrl=existing_qs["ic-orders"],
                Attributes={"RedrivePolicy": json.dumps({
                    "deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"})})
            _act("redrive policy ic-orders -> ic-orders-dlq")
        except ClientError as e:
            _err(f"redrive: {e}")

    # ---- DynamoDB inventory table (task13) ------------------------------
    hdr("DynamoDB — inventory (task13)")
    inv_table = EXTRAS["ddb_inventory"]["table"]
    try:
        ddb.describe_table(TableName=inv_table)
        _ok(inv_table); out["existing"]["ddb_inventory"] = inv_table
    except ClientError:
        _miss(inv_table)
        if provision:
            ddb.create_table(
                TableName=inv_table,
                BillingMode="PROVISIONED",
                ProvisionedThroughput={"ReadCapacityUnits": 1,
                                       "WriteCapacityUnits": 1},  # tiny — easy to throttle
                KeySchema=[{"AttributeName": "sku", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "sku",
                                       "AttributeType": "S"}],
                Tags=TAGS,
            )
            _act(f"created {inv_table} (RCU/WCU=1 — throttle-prone)")
            out["created"].append(inv_table)

    # ---- S3 task15 drift bucket -----------------------------------------
    hdr("S3 — task15 drift bucket")
    drift_bucket = EXTRAS["s3_drift"]["bucket"]
    try:
        s3.head_bucket(Bucket=drift_bucket)
        _ok(drift_bucket); out["existing"]["s3_drift"] = drift_bucket
    except ClientError:
        _miss(drift_bucket)
        if provision:
            try:
                if REGION == "us-east-1":
                    s3.create_bucket(Bucket=drift_bucket)
                else:
                    s3.create_bucket(Bucket=drift_bucket,
                        CreateBucketConfiguration={"LocationConstraint": REGION})
                s3.put_bucket_tagging(Bucket=drift_bucket,
                                      Tagging={"TagSet": TAGS})
                _act(drift_bucket); out["created"].append(drift_bucket)
            except ClientError as e:
                _err(f"create bucket: {e}")

    # ---- SSM parameters -------------------------------------------------
    hdr("SSM Parameter Store")
    ssm = boto3.client("ssm", region_name=REGION)
    for pname, default in [
        (EXTRAS["ssm_pool"]["name"],  "20"),
        (EXTRAS["ssm_flag"]["name"], "false"),
    ]:
        try:
            ssm.get_parameter(Name=pname)
            _ok(pname); out["existing"].setdefault("ssm", []).append(pname)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ParameterNotFound":
                _err(f"{pname}: {e}"); continue
            _miss(pname)
            if provision:
                ssm.put_parameter(Name=pname, Value=default,
                                  Type="String", Overwrite=False,
                                  Tags=TAGS)
                _act(f"{pname} = {default}"); out["created"].append(pname)

    # ---- KMS data-key alias ---------------------------------------------
    hdr("KMS")
    kms = boto3.client("kms", region_name=REGION)
    alias = EXTRAS["kms_alias"]["alias"]
    aliases = {a["AliasName"]: a for a in
               kms.list_aliases().get("Aliases", [])}
    if alias in aliases:
        _ok(alias); out["existing"]["kms_alias"] = alias
    else:
        _miss(alias)
        if provision:
            key = kms.create_key(Description="ic-data-key",
                                 KeyUsage="ENCRYPT_DECRYPT",
                                 Tags=[{"TagKey": t["Key"], "TagValue": t["Value"]}
                                       for t in TAGS])["KeyMetadata"]["KeyId"]
            kms.create_alias(AliasName=alias, TargetKeyId=key)
            _act(f"{alias} -> {key}"); out["created"].append(alias)

    # ---- EventBridge ----------------------------------------------------
    hdr("EventBridge")
    eb = boto3.client("events", region_name=REGION)
    bus = EXTRAS["eb_bus"]["name"]
    try:
        eb.describe_event_bus(Name=bus)
        _ok(bus); out["existing"]["eb_bus"] = bus
    except ClientError:
        _miss(bus)
        if provision:
            eb.create_event_bus(Name=bus, Tags=TAGS)
            _act(bus); out["created"].append(bus)

    rule = EXTRAS["eb_rule"]["name"]
    try:
        eb.describe_rule(Name=rule, EventBusName=bus)
        _ok(f"{bus}/{rule}"); out["existing"]["eb_rule"] = rule
    except ClientError:
        _miss(f"{bus}/{rule}")
        if provision:
            try:
                eb.put_rule(
                    Name=rule, EventBusName=bus,
                    EventPattern=json.dumps({"source":
                                             ["incident-commander.agent"]}),
                    State="ENABLED", Tags=TAGS,
                    Description="Catch-all for agent events")
                _act(f"{bus}/{rule}"); out["created"].append(rule)
            except ClientError as e:
                _err(f"put_rule: {e}")

    # ---- CloudWatch alarm storm (task19) --------------------------------
    hdr("CloudWatch alarm")
    cw = boto3.client("cloudwatch", region_name=REGION)
    alarm = EXTRAS["alarm_storm"]["name"]
    existing_alarms = {a["AlarmName"] for a in
                       cw.describe_alarms(AlarmNames=[alarm])
                         .get("MetricAlarms", [])}
    if alarm in existing_alarms:
        _ok(alarm); out["existing"]["alarm_storm"] = alarm
    else:
        _miss(alarm)
        if provision:
            cw.put_metric_alarm(
                AlarmName=alarm,
                MetricName="StormCounter",
                Namespace="IncidentCommander",
                Statistic="Sum",
                Period=60, EvaluationPeriods=1, Threshold=1,
                ComparisonOperator="GreaterThanOrEqualToThreshold",
                AlarmActions=[
                    f"arn:aws:sns:{REGION}:{ACCOUNT}:incident-commander-alerts"],
                Tags=TAGS,
                TreatMissingData="notBreaching",
                AlarmDescription="Synthetic storm alarm for task19")
            _act(alarm); out["created"].append(alarm)

    # ---- Bedrock probe (no provision) -----------------------------------
    hdr("Bedrock (model access)")
    try:
        br = boto3.client("bedrock", region_name=REGION)
        models = br.list_foundation_models()["modelSummaries"][:3]
        _ok(f"{len(models)} models reachable (e.g. {models[0]['modelId']})")
        out["existing"]["bedrock"] = True
    except (ClientError, EndpointConnectionError) as e:
        _warn(f"bedrock: {e}")

    # ---- Step Functions (task21) ----------------------------------------
    hdr("Step Functions — ic-order-saga")
    sfn = boto3.client("stepfunctions", region_name=REGION)
    sm_name = EXTRAS["sfn_saga"]["name"]
    sm_arn = f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:{sm_name}"
    try:
        sfn.describe_state_machine(stateMachineArn=sm_arn)
        _ok(sm_arn); out["existing"]["sfn_saga"] = sm_arn
    except ClientError:
        _miss(sm_arn)
        if provision:
            iam = boto3.client("iam")
            role_name = "ic-sfn-role"
            try:
                role = iam.get_role(RoleName=role_name)
                role_arn = role["Role"]["Arn"]
            except ClientError:
                role = iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps({
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Effect": "Allow",
                            "Principal": {"Service": "states.amazonaws.com"},
                            "Action": "sts:AssumeRole"}]}),
                    Tags=TAGS)
                role_arn = role["Role"]["Arn"]
                _act(f"created IAM role {role_name}")
                time.sleep(8)
            definition = {
                "Comment": "Toy saga: any input.kind != 'happy' lands in Fail.",
                "StartAt": "Decide",
                "States": {
                    "Decide": {
                        "Type": "Choice",
                        "Choices": [{"Variable": "$.kind",
                                     "StringEquals": "happy",
                                     "Next": "Done"}],
                        "Default": "Boom"},
                    "Done": {"Type": "Pass", "End": True},
                    "Boom": {"Type": "Fail", "Error": "InducedFailure",
                             "Cause": "chaos_aws.py task21"}}}
            try:
                r = sfn.create_state_machine(
                    name=sm_name,
                    definition=json.dumps(definition),
                    roleArn=role_arn,
                    type="STANDARD",
                    tags=[{"key": t["Key"], "value": t["Value"]} for t in TAGS])
                _act(r["stateMachineArn"])
                out["created"].append(r["stateMachineArn"])
            except ClientError as e:
                _err(f"sfn create: {e}")

    return out


def _create_minimal_lambda(lam, name: str, out: dict) -> None:
    """Create a tiny no-op Lambda using a fresh basic-execution role."""
    iam = boto3.client("iam")
    role_name = f"{name}-role"
    role_arn: str | None = None
    try:
        role = iam.get_role(RoleName=role_name)
        role_arn = role["Role"]["Arn"]
    except ClientError:
        try:
            role = iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole"}]}),
                Tags=TAGS,
            )
            role_arn = role["Role"]["Arn"]
            iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            )
            _act(f"created IAM role {role_name}")
            time.sleep(8)  # IAM eventual consistency
        except ClientError as e:
            _err(f"role create: {e}"); return

    # Inline source — bytes-zip via in-memory zipfile.
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("handler.py",
            "def handler(event, ctx):\n"
            f"    return {{'ok': True, 'fn': '{name}'}}\n")
    try:
        lam.create_function(
            FunctionName=name,
            Runtime="python3.11",
            Role=role_arn,
            Handler="handler.handler",
            Code={"ZipFile": buf.getvalue()},
            Timeout=10, MemorySize=128,
            Tags={t["Key"]: t["Value"] for t in TAGS},
        )
        _act(f"created Lambda {name}")
        out["created"].append(name)
    except ClientError as e:
        _err(f"lambda create {name}: {e}")


# ---------------------------------------------------------------------------
# Optional teardown for just the extras (preserves Terraform-managed stuff).
# ---------------------------------------------------------------------------

def teardown_extras() -> None:
    print(f"\nTearing down extras in account {ACCOUNT} region {REGION}\n")
    sqs = boto3.client("sqs", region_name=REGION)
    for q in ("ic-events", "ic-orders", "ic-orders-dlq"):
        urls = sqs.list_queues(QueueNamePrefix=q).get("QueueUrls", [])
        for u in urls:
            try: sqs.delete_queue(QueueUrl=u); _act(f"deleted SQS {u}")
            except ClientError as e: _err(f"sqs {u}: {e}")
    ddb = boto3.client("dynamodb", region_name=REGION)
    try: ddb.delete_table(TableName=EXTRAS["ddb_inventory"]["table"]); _act("deleted ic-inventory")
    except ClientError: pass
    s3 = boto3.client("s3", region_name=REGION)
    try:
        b = EXTRAS["s3_drift"]["bucket"]
        objs = s3.list_objects_v2(Bucket=b).get("Contents", []) or []
        for o in objs: s3.delete_object(Bucket=b, Key=o["Key"])
        s3.delete_bucket(Bucket=b); _act(f"deleted s3 {b}")
    except ClientError: pass
    sm = boto3.client("secretsmanager", region_name=REGION)
    try: sm.delete_secret(SecretId=EXTRAS["secret_stripe"]["name"],
                          ForceDeleteWithoutRecovery=True); _act("deleted ic-stripe-api-key")
    except ClientError: pass
    lam = boto3.client("lambda", region_name=REGION)
    for f in (EXTRAS["lambda_cold"]["name"], EXTRAS["lambda_runbook"]["name"]):
        try: lam.delete_function(FunctionName=f); _act(f"deleted lambda {f}")
        except ClientError: pass
    ssm = boto3.client("ssm", region_name=REGION)
    for p in (EXTRAS["ssm_pool"]["name"], EXTRAS["ssm_flag"]["name"]):
        try: ssm.delete_parameter(Name=p); _act(f"deleted ssm {p}")
        except ClientError: pass
    eb = boto3.client("events", region_name=REGION)
    try: eb.delete_rule(Name=EXTRAS["eb_rule"]["name"],
                        EventBusName=EXTRAS["eb_bus"]["name"], Force=True); _act("deleted eb rule")
    except ClientError: pass
    try: eb.delete_event_bus(Name=EXTRAS["eb_bus"]["name"]); _act("deleted eb bus")
    except ClientError: pass
    cw = boto3.client("cloudwatch", region_name=REGION)
    try: cw.delete_alarms(AlarmNames=[EXTRAS["alarm_storm"]["name"]]); _act("deleted alarm")
    except ClientError: pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--provision", action="store_true",
                   help="create missing resources")
    p.add_argument("--teardown-extras", action="store_true",
                   help="delete only extras (keeps Terraform-managed)")
    p.add_argument("--json", action="store_true",
                   help="emit final inventory as JSON")
    args = p.parse_args()
    if args.teardown_extras:
        teardown_extras(); return
    out = inventory(provision=args.provision)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    print(f"\nDone. created={len(out['created'])} errors={len(out['errors'])}")
    if out["errors"]:
        sys.exit(2)


if __name__ == "__main__":
    if os.getenv("IC_USE_LIVE_AWS", "false").lower() not in ("1", "true", "yes"):
        print("aws_inventory.py: live AWS disabled (mentor 2026-04-25). "
              "Set IC_USE_LIVE_AWS=true to re-enable.")
        sys.exit(0)
    main()
