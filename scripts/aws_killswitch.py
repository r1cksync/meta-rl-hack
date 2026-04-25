"""Targeted AWS kill-switch.

Deletes every billable resource that this project provisioned in the AWS
account. Scope is intentionally NARROW:
  * Anything tagged Project=incident-commander
  * Plus the explicit `ic-*` / `incident-commander-*` resource names from
    scripts/aws_inventory.py
  * Plus the EKS cluster `incident-commander` and its node groups

Will NOT touch anything else in the account. Always run --dry-run first,
review the planned actions, then re-run with --apply.

Usage:
    python scripts/aws_killswitch.py                 # dry-run
    python scripts/aws_killswitch.py --apply         # actually delete

Run from incident-commander/ project root (so .env.aws.local is found).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Bootstrap: load .env.aws.local for resource pointers + region.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.aws.local"
for _line in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []):
    _line = _line.strip()
    if not _line or _line.startswith("#") or "=" not in _line:
        continue
    _k, _, _v = _line.partition("=")
    os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import boto3                                            # noqa: E402
from botocore.exceptions import ClientError             # noqa: E402
from botocore.config import Config                      # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-east-1")
CFG    = Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2})
ACCOUNT = boto3.client("sts", region_name=REGION, config=CFG)\
    .get_caller_identity()["Account"]

# Names we own. Anything not in this list (or matching the patterns below)
# is left strictly alone.
OWNED_LAMBDAS = [
    "ic-cold-start-target",
    "ic-runbook-restart-pods",
    "incident-commander-alarm-hook",
]
OWNED_SQS_QUEUES = ["ic-events", "ic-orders", "ic-orders-dlq"]
OWNED_DDB_TABLES = ["ic-inventory", "incident-commander-curriculum"]
OWNED_SECRETS    = ["incident-commander/openai-api-key", "ic-stripe-api-key"]
OWNED_SSM_PARAMS = ["/ic/payments/db-pool-size", "/ic/feature-flags/enable_chaos"]
OWNED_SNS_TOPICS = [f"arn:aws:sns:{REGION}:{ACCOUNT}:incident-commander-alerts"]
OWNED_EB_BUS     = "ic-bus"
OWNED_EB_RULE    = "ic-orders-rule"
OWNED_KMS_ALIAS  = "alias/ic-data-key"
OWNED_SFN_NAME   = "ic-order-saga"
OWNED_ALARMS     = ["ic-cw-alarm-storm"]
OWNED_LOG_GROUP_PREFIXES = [
    "/aws/eks/incident-commander/",
    "/aws/lambda/ic-",
    "/aws/lambda/incident-commander-",
]
OWNED_BUCKET_PREFIXES = ["ic-checkpoints-", "ic-task15-drift-"]
OWNED_EKS_CLUSTER = "incident-commander"
OWNED_ECR_REPO    = "incident-commander"
OWNED_IAM_ROLE_PREFIXES = ["ic-", "incident-commander-"]


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

class _Plan:
    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.deleted: list[str] = []
        self.skipped: list[str] = []
        self.errored: list[tuple[str, str]] = []

    def will(self, what: str, do: Callable[[], Any]) -> None:
        prefix = "[DRY]" if self.dry else "[DEL]"
        print(f"  {prefix} {what}")
        if self.dry:
            self.deleted.append(what)
            return
        try:
            do()
            self.deleted.append(what)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "?")
            if code in ("ResourceNotFoundException", "NoSuchEntity",
                        "NoSuchBucket", "NotFoundException",
                        "AWS.SimpleQueueService.NonExistentQueue",
                        "AlarmNotFound", "ResourceNotFound"):
                print(f"     (already gone: {code})")
                self.skipped.append(what)
            else:
                print(f"     [error] {code}: {e}")
                self.errored.append((what, f"{code}: {e}"))
        except Exception as e:
            print(f"     [error] {e}")
            self.errored.append((what, str(e)))

    def skip(self, what: str, why: str = "not found") -> None:
        print(f"  [skip] {what} ({why})")
        self.skipped.append(what)


def hdr(s: str) -> None:
    print(f"\n=== {s} ===")


# ---------------------------------------------------------------------------
# Per-service teardown
# ---------------------------------------------------------------------------

def _kill_eks(plan: _Plan) -> None:
    hdr("EKS")
    eks = boto3.client("eks", region_name=REGION, config=CFG)
    try:
        eks.describe_cluster(name=OWNED_EKS_CLUSTER)
    except ClientError:
        plan.skip(f"eks/{OWNED_EKS_CLUSTER}")
        return
    # Node groups
    ngs = eks.list_nodegroups(clusterName=OWNED_EKS_CLUSTER).get("nodegroups", [])
    for ng in ngs:
        plan.will(f"eks nodegroup {OWNED_EKS_CLUSTER}/{ng}",
                  lambda ng=ng: eks.delete_nodegroup(
                      clusterName=OWNED_EKS_CLUSTER, nodegroupName=ng))
    if ngs and not plan.dry:
        # Wait for nodegroups to actually go (cluster delete fails otherwise)
        print("     waiting for nodegroups to drain...")
        for ng in ngs:
            for _ in range(60):     # up to 30 min
                try:
                    eks.describe_nodegroup(
                        clusterName=OWNED_EKS_CLUSTER, nodegroupName=ng)
                    time.sleep(30)
                except ClientError:
                    break
    # Fargate profiles (idempotent if none)
    try:
        fps = eks.list_fargate_profiles(clusterName=OWNED_EKS_CLUSTER)\
            .get("fargateProfileNames", [])
    except ClientError:
        fps = []
    for fp in fps:
        plan.will(f"eks fargate profile {OWNED_EKS_CLUSTER}/{fp}",
                  lambda fp=fp: eks.delete_fargate_profile(
                      clusterName=OWNED_EKS_CLUSTER, fargateProfileName=fp))
    # Cluster
    plan.will(f"eks cluster {OWNED_EKS_CLUSTER}",
              lambda: eks.delete_cluster(name=OWNED_EKS_CLUSTER))


def _kill_ec2(plan: _Plan) -> None:
    """Kill EC2 only if tagged Project=incident-commander.
    Won't touch anything else."""
    hdr("EC2 (project-tagged only)")
    ec2 = boto3.client("ec2", region_name=REGION, config=CFG)
    flt = [{"Name": "tag:Project", "Values": ["incident-commander"]}]
    # Instances
    instances = []
    for r in ec2.describe_instances(Filters=flt).get("Reservations", []):
        for i in r.get("Instances", []):
            if i.get("State", {}).get("Name") not in ("terminated", "shutting-down"):
                instances.append(i["InstanceId"])
    if instances:
        plan.will(f"ec2 terminate instances {instances}",
                  lambda: ec2.terminate_instances(InstanceIds=instances))
    else:
        plan.skip("ec2 instances (project tag)")
    # NAT gateways (project tagged)
    nats = ec2.describe_nat_gateways(Filter=flt).get("NatGateways", [])
    for n in nats:
        if n.get("State") not in ("deleted", "deleting"):
            plan.will(f"ec2 nat-gateway {n['NatGatewayId']}",
                      lambda nid=n["NatGatewayId"]:
                          ec2.delete_nat_gateway(NatGatewayId=nid))
    # Elastic IPs (project tagged)
    eips = ec2.describe_addresses(Filters=flt).get("Addresses", [])
    for a in eips:
        if "AllocationId" in a:
            plan.will(f"ec2 release-eip {a['AllocationId']}",
                      lambda aid=a["AllocationId"]:
                          ec2.release_address(AllocationId=aid))


def _kill_lambda(plan: _Plan) -> None:
    hdr("Lambda")
    lam = boto3.client("lambda", region_name=REGION, config=CFG)
    for fn in OWNED_LAMBDAS:
        plan.will(f"lambda function {fn}",
                  lambda fn=fn: lam.delete_function(FunctionName=fn))


def _kill_sqs(plan: _Plan) -> None:
    hdr("SQS")
    sqs = boto3.client("sqs", region_name=REGION, config=CFG)
    for q in OWNED_SQS_QUEUES:
        try:
            url = sqs.get_queue_url(QueueName=q)["QueueUrl"]
        except ClientError:
            plan.skip(f"sqs/{q}")
            continue
        plan.will(f"sqs queue {q}",
                  lambda url=url: sqs.delete_queue(QueueUrl=url))


def _kill_ddb(plan: _Plan) -> None:
    hdr("DynamoDB")
    ddb = boto3.client("dynamodb", region_name=REGION, config=CFG)
    for t in OWNED_DDB_TABLES:
        plan.will(f"ddb table {t}",
                  lambda t=t: ddb.delete_table(TableName=t))


def _empty_and_delete_bucket(s3, bucket: str) -> None:
    # Delete every object version + delete-marker, then the bucket.
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        delete_objs = []
        for v in page.get("Versions", []) or []:
            delete_objs.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for m in page.get("DeleteMarkers", []) or []:
            delete_objs.append({"Key": m["Key"], "VersionId": m["VersionId"]})
        if delete_objs:
            for i in range(0, len(delete_objs), 1000):
                s3.delete_objects(Bucket=bucket,
                                  Delete={"Objects": delete_objs[i:i+1000],
                                          "Quiet": True})
    s3.delete_bucket(Bucket=bucket)


def _kill_s3(plan: _Plan) -> None:
    hdr("S3 buckets")
    s3 = boto3.client("s3", region_name=REGION, config=CFG)
    buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    matches = [b for b in buckets
               if any(b.startswith(p) for p in OWNED_BUCKET_PREFIXES)]
    if not matches:
        plan.skip("s3 (no ic-* buckets)")
        return
    for b in matches:
        plan.will(f"s3 bucket {b} (empty + delete)",
                  lambda b=b: _empty_and_delete_bucket(s3, b))


def _kill_secrets(plan: _Plan) -> None:
    hdr("Secrets Manager")
    sm = boto3.client("secretsmanager", region_name=REGION, config=CFG)
    for s in OWNED_SECRETS:
        plan.will(f"secret {s}",
                  lambda s=s: sm.delete_secret(SecretId=s,
                                               ForceDeleteWithoutRecovery=True))


def _kill_kms(plan: _Plan) -> None:
    hdr("KMS")
    kms = boto3.client("kms", region_name=REGION, config=CFG)
    try:
        meta = kms.describe_key(KeyId=OWNED_KMS_ALIAS)["KeyMetadata"]
        key_id = meta["KeyId"]
    except ClientError:
        plan.skip(f"kms {OWNED_KMS_ALIAS}")
        return
    plan.will(f"kms alias {OWNED_KMS_ALIAS}",
              lambda: kms.delete_alias(AliasName=OWNED_KMS_ALIAS))
    if meta.get("KeyState") != "PendingDeletion":
        plan.will(f"kms schedule_key_deletion {key_id} (7d window)",
                  lambda: kms.schedule_key_deletion(
                      KeyId=key_id, PendingWindowInDays=7))


def _kill_eventbridge(plan: _Plan) -> None:
    hdr("EventBridge")
    eb = boto3.client("events", region_name=REGION, config=CFG)
    # Targets first
    try:
        ts = eb.list_targets_by_rule(Rule=OWNED_EB_RULE,
                                     EventBusName=OWNED_EB_BUS)\
            .get("Targets", [])
        if ts:
            plan.will(f"eb rule targets {OWNED_EB_RULE}",
                      lambda: eb.remove_targets(
                          Rule=OWNED_EB_RULE, EventBusName=OWNED_EB_BUS,
                          Ids=[t["Id"] for t in ts], Force=True))
    except ClientError:
        pass
    plan.will(f"eb rule {OWNED_EB_RULE}",
              lambda: eb.delete_rule(Name=OWNED_EB_RULE,
                                     EventBusName=OWNED_EB_BUS, Force=True))
    plan.will(f"eb bus {OWNED_EB_BUS}",
              lambda: eb.delete_event_bus(Name=OWNED_EB_BUS))


def _kill_cloudwatch(plan: _Plan) -> None:
    hdr("CloudWatch")
    cw  = boto3.client("cloudwatch", region_name=REGION, config=CFG)
    cwl = boto3.client("logs",       region_name=REGION, config=CFG)
    for a in OWNED_ALARMS:
        plan.will(f"cw alarm {a}",
                  lambda a=a: cw.delete_alarms(AlarmNames=[a]))
    # Log groups by prefix
    for prefix in OWNED_LOG_GROUP_PREFIXES:
        try:
            paginator = cwl.get_paginator("describe_log_groups")
            for page in paginator.paginate(logGroupNamePrefix=prefix):
                for lg in page.get("logGroups", []):
                    name = lg["logGroupName"]
                    plan.will(f"cw log group {name}",
                              lambda n=name: cwl.delete_log_group(logGroupName=n))
        except ClientError:
            pass


def _kill_sns(plan: _Plan) -> None:
    hdr("SNS")
    sns = boto3.client("sns", region_name=REGION, config=CFG)
    for arn in OWNED_SNS_TOPICS:
        plan.will(f"sns topic {arn}",
                  lambda arn=arn: sns.delete_topic(TopicArn=arn))


def _kill_ssm(plan: _Plan) -> None:
    hdr("SSM Parameter Store")
    ssm = boto3.client("ssm", region_name=REGION, config=CFG)
    for p in OWNED_SSM_PARAMS:
        plan.will(f"ssm param {p}",
                  lambda p=p: ssm.delete_parameter(Name=p))


def _kill_sfn(plan: _Plan) -> None:
    hdr("Step Functions")
    sfn = boto3.client("stepfunctions", region_name=REGION, config=CFG)
    arn = f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:{OWNED_SFN_NAME}"
    plan.will(f"sfn state machine {OWNED_SFN_NAME}",
              lambda: sfn.delete_state_machine(stateMachineArn=arn))


def _kill_iam(plan: _Plan) -> None:
    hdr("IAM (project-prefixed roles only)")
    iam = boto3.client("iam", region_name=REGION, config=CFG)
    paginator = iam.get_paginator("list_roles")
    targets: list[str] = []
    for page in paginator.paginate():
        for r in page.get("Roles", []):
            n = r["RoleName"]
            if any(n.startswith(p) for p in OWNED_IAM_ROLE_PREFIXES):
                targets.append(n)
    for name in targets:
        # Detach managed policies
        try:
            for pol in iam.list_attached_role_policies(RoleName=name)\
                    .get("AttachedPolicies", []):
                plan.will(
                    f"iam detach {pol['PolicyArn']} from {name}",
                    lambda n=name, arn=pol["PolicyArn"]:
                        iam.detach_role_policy(RoleName=n, PolicyArn=arn))
        except ClientError:
            pass
        # Delete inline policies
        try:
            for pn in iam.list_role_policies(RoleName=name)\
                    .get("PolicyNames", []):
                plan.will(
                    f"iam inline-policy {name}/{pn}",
                    lambda n=name, p=pn:
                        iam.delete_role_policy(RoleName=n, PolicyName=p))
        except ClientError:
            pass
        # Remove from instance profiles
        try:
            for ipf in iam.list_instance_profiles_for_role(RoleName=name)\
                    .get("InstanceProfiles", []):
                plan.will(
                    f"iam remove role {name} from instance-profile {ipf['InstanceProfileName']}",
                    lambda n=name, ip=ipf["InstanceProfileName"]:
                        iam.remove_role_from_instance_profile(
                            InstanceProfileName=ip, RoleName=n))
        except ClientError:
            pass
        plan.will(f"iam role {name}",
                  lambda n=name: iam.delete_role(RoleName=n))


def _kill_ecr(plan: _Plan) -> None:
    hdr("ECR")
    ecr = boto3.client("ecr", region_name=REGION, config=CFG)
    plan.will(f"ecr repo {OWNED_ECR_REPO}",
              lambda: ecr.delete_repository(repositoryName=OWNED_ECR_REPO,
                                            force=True))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

PHASES: list[tuple[str, Callable[[_Plan], None]]] = [
    # Order matters: dependents first.
    ("eks",          _kill_eks),
    ("lambda",       _kill_lambda),
    ("eventbridge",  _kill_eventbridge),
    ("sfn",          _kill_sfn),
    ("ec2",          _kill_ec2),
    ("sqs",          _kill_sqs),
    ("ddb",          _kill_ddb),
    ("s3",           _kill_s3),
    ("secrets",      _kill_secrets),
    ("kms",          _kill_kms),
    ("cloudwatch",   _kill_cloudwatch),
    ("sns",          _kill_sns),
    ("ssm",          _kill_ssm),
    ("ecr",          _kill_ecr),
    ("iam",          _kill_iam),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete (default is dry-run)")
    ap.add_argument("--only", action="append", default=[],
                    help="Only run these phases (repeatable)")
    args = ap.parse_args()
    plan = _Plan(dry=not args.apply)
    print(f"\nAccount: {ACCOUNT}   Region: {REGION}   Mode: "
          f"{'APPLY (will delete)' if args.apply else 'DRY-RUN'}\n")
    for name, fn in PHASES:
        if args.only and name not in args.only:
            continue
        try:
            fn(plan)
        except Exception as e:
            print(f"  [phase-error] {name}: {e}")
            plan.errored.append((name, str(e)))
    print(f"\n=== summary ===")
    print(f"  planned/deleted: {len(plan.deleted)}")
    print(f"  skipped (gone):  {len(plan.skipped)}")
    print(f"  errored:         {len(plan.errored)}")
    for what, why in plan.errored:
        print(f"   - {what}  =>  {why}")
    return 0 if not plan.errored else 1


if __name__ == "__main__":
    sys.exit(main())
