"""AWS integrations for IncidentCommander.

Every integration is gated by env vars + boto3 credential discovery — if any
piece is missing the class silently reports `enabled = False` and becomes a
no-op. Importing this module costs nothing on the HF Space (boto3 import is
lazy inside each __init__).

Integrations
------------
* `CloudWatchLogsReader`       — pod logs for the `query_logs` action.
* `S3CheckpointUploader`       — LoRA adapter + metrics.jsonl archive to S3.
* `DynamoCurriculumStore`      — durable mastery table (PITR-enabled).
* `CloudWatchMetricsPublisher` — custom `IncidentCommander` metrics namespace.
* `SNSIncidentPublisher`       — publish when the agent applies a mitigation.
* `SecretsLoader`              — load `OPENAI_API_KEY` at startup.
* `aws_status()`               — aggregate status dict for /aws/status.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


def _have_aws_credentials() -> bool:
    """Fast, non-network check for AWS credentials.

    Returns True only if env-var credentials are present OR a profile is
    configured. Avoids IMDS calls that block for seconds on a laptop / HF
    Space with no AWS access.
    """
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.getenv("AWS_PROFILE"):
        return True
    if os.getenv("AWS_ROLE_ARN") and os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE"):
        return True  # IRSA / workload identity
    # Shared credentials file
    cred_path = Path(os.path.expanduser("~/.aws/credentials"))
    return cred_path.exists()


def _client(service: str, region: Optional[str] = None):
    """Build a boto3 client with short connect/read timeouts so importing the
    module against a no-creds machine doesn't stall the HF Space."""
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore
    cfg = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1})
    return boto3.client(service, region_name=region, config=cfg)


# ---------------------------------------------------------------------------
# CloudWatch Logs
# ---------------------------------------------------------------------------

class CloudWatchLogsReader:
    """Thin wrapper around boto3 logs FilterLogEvents.

    Enabled when both `AWS_REGION` and `CLOUDWATCH_LOG_GROUP` are set AND
    boto3 can resolve credentials (env / instance profile / SSO).
    """

    def __init__(self, region: Optional[str] = None, log_group: Optional[str] = None):
        self.region    = region    or os.getenv("AWS_REGION")
        self.log_group = log_group or os.getenv("CLOUDWATCH_LOG_GROUP")
        self._client = None
        self.enabled = False
        if self.region and self.log_group and _have_aws_credentials():
            try:
                self._client = _client("logs", self.region)
                self._client.describe_log_groups(logGroupNamePrefix=self.log_group, limit=1)
                self.enabled = True
                log.info("CloudWatch logs reader enabled: %s/%s", self.region, self.log_group)
            except Exception as e:
                log.warning("CloudWatch disabled (%s)", e)

    def query(self, service: str, last_minutes: int = 5, limit: int = 50) -> list[str]:
        """Return up to `limit` log lines for pods whose name contains `service`."""
        if not self.enabled or self._client is None:
            return []
        import time as _t
        end = int(_t.time() * 1000)
        start = end - last_minutes * 60 * 1000
        try:
            resp = self._client.filter_log_events(
                logGroupName=self.log_group,
                startTime=start,
                endTime=end,
                filterPattern=f'"{service}"',
                limit=limit,
            )
            return [e.get("message", "").rstrip() for e in resp.get("events", [])]
        except Exception as e:
            log.warning("CloudWatch filter_log_events failed: %s", e)
            return []


# ---------------------------------------------------------------------------
# S3 checkpoint uploader
# ---------------------------------------------------------------------------

class S3CheckpointUploader:
    """Upload LoRA adapter dirs to S3 after each save.

    Enabled when `S3_CHECKPOINT_BUCKET` is set and boto3 creds resolve.
    """

    def __init__(self, bucket: Optional[str] = None, prefix: str = "grpo"):
        self.bucket = bucket or os.getenv("S3_CHECKPOINT_BUCKET")
        self.prefix = prefix
        self._client = None
        self.enabled = False
        if self.bucket and _have_aws_credentials():
            try:
                self._client = _client("s3")
                self._client.head_bucket(Bucket=self.bucket)
                self.enabled = True
                log.info("S3 checkpoint uploader: s3://%s/%s", self.bucket, self.prefix)
            except Exception as e:
                log.warning("S3 uploader disabled (%s)", e)

    def upload_dir(self, local_dir: str | Path, remote_subdir: str) -> int:
        if not self.enabled or self._client is None:
            return 0
        local = Path(local_dir)
        if not local.exists():
            return 0
        uploaded = 0
        for p in local.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(local).as_posix()
            key = f"{self.prefix}/{remote_subdir}/{rel}"
            try:
                self._client.upload_file(str(p), self.bucket, key)
                uploaded += 1
            except Exception as e:
                log.warning("upload %s failed: %s", key, e)
        log.info("uploaded %d files to s3://%s/%s/%s",
                 uploaded, self.bucket, self.prefix, remote_subdir)
        return uploaded


# ---------------------------------------------------------------------------
# DynamoDB — durable curriculum mastery store
# ---------------------------------------------------------------------------

class DynamoCurriculumStore:
    """Persist per-task mastery in DynamoDB so curriculum state survives Space
    restarts. Hash: `run_id`, Range: `task_id`.

    Enabled when `DYNAMODB_CURRICULUM_TABLE` is set and boto3 creds resolve.
    """

    def __init__(self, table: Optional[str] = None, region: Optional[str] = None):
        self.table_name = table  or os.getenv("DYNAMODB_CURRICULUM_TABLE")
        self.region     = region or os.getenv("AWS_REGION")
        self._table = None
        self.enabled = False
        if self.table_name and _have_aws_credentials():
            try:
                import boto3  # type: ignore
                from botocore.config import Config  # type: ignore
                cfg = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1})
                ddb = boto3.resource("dynamodb", region_name=self.region, config=cfg)
                self._table = ddb.Table(self.table_name)
                self._table.load()
                self.enabled = True
                log.info("Dynamo curriculum store: %s", self.table_name)
            except Exception as e:
                log.warning("Dynamo disabled (%s)", e)

    def put_outcome(self, run_id: str, task_id: str, mastery: float, score: float,
                    tier: str) -> bool:
        if not self.enabled or self._table is None:
            return False
        try:
            self._table.put_item(Item={
                "run_id":   run_id,
                "task_id":  task_id,
                "mastery":  str(mastery),
                "score":    str(score),
                "tier":     tier,
                "ts":       int(time.time()),
            })
            return True
        except Exception as e:
            log.warning("dynamo put_item failed: %s", e)
            return False

    def load_run(self, run_id: str) -> dict:
        if not self.enabled or self._table is None:
            return {}
        try:
            resp = self._table.query(
                KeyConditionExpression="run_id = :r",
                ExpressionAttributeValues={":r": run_id},
            )
            return {i["task_id"]: {
                "mastery": float(i.get("mastery", 0)),
                "score":   float(i.get("score", 0)),
                "tier":    i.get("tier", "warmup"),
                "ts":      int(i.get("ts", 0)),
            } for i in resp.get("Items", [])}
        except Exception as e:
            log.warning("dynamo query failed: %s", e)
            return {}


# ---------------------------------------------------------------------------
# CloudWatch custom metrics
# ---------------------------------------------------------------------------

class CloudWatchMetricsPublisher:
    """Publish training / episode metrics to the `IncidentCommander` CW namespace.

    Enabled when `CLOUDWATCH_METRIC_NAMESPACE` is set and boto3 creds resolve.
    """

    def __init__(self, namespace: Optional[str] = None, region: Optional[str] = None):
        self.namespace = namespace or os.getenv("CLOUDWATCH_METRIC_NAMESPACE",
                                                "IncidentCommander")
        self.region    = region    or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if _have_aws_credentials():
            try:
                self._client = _client("cloudwatch", self.region)
                self._client.list_metrics(Namespace=self.namespace, MaxRecords=1)
                self.enabled = True
                log.info("CloudWatch metrics: namespace=%s", self.namespace)
            except Exception as e:
                log.warning("CW metrics disabled (%s)", e)

    def publish(self, name: str, value: float, unit: str = "None",
                dims: Optional[dict] = None) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            self._client.put_metric_data(
                Namespace=self.namespace,
                MetricData=[{
                    "MetricName": name,
                    "Value":      float(value),
                    "Unit":       unit,
                    "Dimensions": [{"Name": k, "Value": str(v)}
                                   for k, v in (dims or {}).items()],
                }],
            )
            return True
        except Exception as e:
            log.warning("put_metric_data failed: %s", e)
            return False


# ---------------------------------------------------------------------------
# SNS — incident alert publisher
# ---------------------------------------------------------------------------

class SNSIncidentPublisher:
    """Publish a structured event to the `-alerts` SNS topic whenever the agent
    applies a mitigation or submits a postmortem.

    Enabled when `SNS_ALERTS_TOPIC_ARN` is set and boto3 creds resolve.
    """

    def __init__(self, topic_arn: Optional[str] = None, region: Optional[str] = None):
        self.topic_arn = topic_arn or os.getenv("SNS_ALERTS_TOPIC_ARN")
        self.region    = region    or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if self.topic_arn and _have_aws_credentials():
            try:
                self._client = _client("sns", self.region)
                self._client.get_topic_attributes(TopicArn=self.topic_arn)
                self.enabled = True
                log.info("SNS publisher: %s", self.topic_arn)
            except Exception as e:
                log.warning("SNS disabled (%s)", e)

    def publish(self, subject: str, payload: dict) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            self._client.publish(
                TopicArn=self.topic_arn,
                Subject=subject[:99],
                Message=json.dumps(payload, default=str),
            )
            return True
        except Exception as e:
            log.warning("sns publish failed: %s", e)
            return False


# ---------------------------------------------------------------------------
# Secrets Manager loader
# ---------------------------------------------------------------------------

class SecretsLoader:
    """Load secret strings by ARN. Used to hydrate `OPENAI_API_KEY` at startup
    so we don't have to bake keys into the image.

    Enabled when boto3 creds resolve; call `.load(arn)` at startup.
    """

    def __init__(self, region: Optional[str] = None):
        self.region = region or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if _have_aws_credentials():
            try:
                self._client = _client("secretsmanager", self.region)
                self.enabled = True
            except Exception as e:
                log.warning("Secrets Manager client disabled (%s)", e)

    def load(self, arn: Optional[str] = None) -> Optional[str]:
        arn = arn or os.getenv("OPENAI_SECRET_ARN")
        if not arn or not self.enabled or self._client is None:
            return None
        try:
            resp = self._client.get_secret_value(SecretId=arn)
            value = resp.get("SecretString")
            if value:
                log.info("loaded secret from %s", arn)
            return value
        except Exception as e:
            log.warning("secret load failed: %s", e)
            return None

    def hydrate_openai_env(self) -> bool:
        if os.getenv("OPENAI_API_KEY"):
            return False  # already set — don't overwrite
        key = self.load()
        if key:
            os.environ["OPENAI_API_KEY"] = key
            return True
        return False


# ---------------------------------------------------------------------------
# Aggregate status for /aws/status + /dashboard/aws
# ---------------------------------------------------------------------------

def aws_status() -> dict[str, Any]:
    """Return which AWS services are reachable from this process.

    Called from server.py at startup and exposed via GET /aws/status so the
    dashboard can render a live "AWS wiring" page.
    """
    status: dict[str, Any] = {
        "region":        os.getenv("AWS_REGION"),
        "account_id":    None,
        "services":      {},
    }
    if _have_aws_credentials():
        try:
            sts = _client("sts", status["region"])
            status["account_id"] = sts.get_caller_identity().get("Account")
        except Exception:
            pass

    def _svc(name: str, enabled: bool, detail: dict) -> None:
        status["services"][name] = {"enabled": enabled, **detail}

    cw   = CloudWatchLogsReader()
    s3   = S3CheckpointUploader()
    dyn  = DynamoCurriculumStore()
    cwm  = CloudWatchMetricsPublisher()
    sns  = SNSIncidentPublisher()
    sec  = SecretsLoader()

    _svc("CloudWatch Logs",   cw.enabled,   {"log_group": cw.log_group})
    _svc("S3",                s3.enabled,   {"bucket": s3.bucket, "prefix": s3.prefix})
    _svc("DynamoDB",          dyn.enabled,  {"table": dyn.table_name})
    _svc("CloudWatch Metrics",cwm.enabled,  {"namespace": cwm.namespace})
    _svc("SNS",               sns.enabled,  {"topic": sns.topic_arn})
    _svc("Secrets Manager",   sec.enabled,  {"configured_secret": os.getenv("OPENAI_SECRET_ARN")})
    _svc("EKS",               bool(os.getenv("EKS_CLUSTER_NAME")),
                                             {"cluster": os.getenv("EKS_CLUSTER_NAME")})
    _svc("ECR",               bool(os.getenv("ECR_REPOSITORY_URL")),
                                             {"repo": os.getenv("ECR_REPOSITORY_URL")})
    _svc("Bedrock",           bool(status["region"]),
                                             {"note": "IAM policy grants bedrock:InvokeModel"})

    return status
