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


# Mentor 2026-04-25: live AWS is OFF by default. Set IC_USE_LIVE_AWS=true to
# re-enable. When False, every helper in this module reports enabled=False
# and `_client` raises so that no boto3 call can leak through.
USE_LIVE_AWS = os.getenv("IC_USE_LIVE_AWS", "false").lower() in ("1", "true", "yes")


def _have_aws_credentials() -> bool:
    """Fast, non-network check for AWS credentials.

    Returns False unconditionally when IC_USE_LIVE_AWS is off. Otherwise
    returns True only if env-var credentials are present OR a profile is
    configured. Avoids IMDS calls that block for seconds on a laptop / HF
    Space with no AWS access.
    """
    if not USE_LIVE_AWS:
        return False
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
    module against a no-creds machine doesn't stall the HF Space.

    Refuses to construct a client when IC_USE_LIVE_AWS is off (mentor cost
    cutoff 2026-04-25). Set IC_USE_LIVE_AWS=true to re-enable.
    """
    if not USE_LIVE_AWS:
        raise RuntimeError(
            "live AWS disabled (set IC_USE_LIVE_AWS=true to re-enable)")
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
                self._client.list_metrics(Namespace=self.namespace)
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
# SQS — incident events queue
# ---------------------------------------------------------------------------

class SQSEventPublisher:
    """Push every agent action onto an SQS queue so a side-car Lambda or the
    next training run can replay them.

    Enabled when `SQS_QUEUE_URL` is set and boto3 creds resolve.
    """

    def __init__(self, queue_url: Optional[str] = None, region: Optional[str] = None):
        self.queue_url = queue_url or os.getenv("SQS_QUEUE_URL")
        self.region    = region    or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if self.queue_url and _have_aws_credentials():
            try:
                self._client = _client("sqs", self.region)
                self._client.get_queue_attributes(
                    QueueUrl=self.queue_url, AttributeNames=["QueueArn"])
                self.enabled = True
                log.info("SQS publisher: %s", self.queue_url)
            except Exception as e:
                log.warning("SQS disabled (%s)", e)

    def publish(self, body: dict, group_id: Optional[str] = None) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            kwargs: dict[str, Any] = {
                "QueueUrl":    self.queue_url,
                "MessageBody": json.dumps(body, default=str),
            }
            if self.queue_url and self.queue_url.endswith(".fifo"):
                kwargs["MessageGroupId"]         = group_id or "default"
                kwargs["MessageDeduplicationId"] = f"{group_id or 'd'}-{int(time.time()*1000)}"
            self._client.send_message(**kwargs)
            return True
        except Exception as e:
            log.warning("sqs publish failed: %s", e)
            return False


# ---------------------------------------------------------------------------
# Lambda invoker — call a runbook lambda
# ---------------------------------------------------------------------------

class LambdaInvoker:
    """Synchronously invoke a Lambda function (e.g. a remediation runbook).

    Enabled when `LAMBDA_RUNBOOK_FUNCTION` is set and boto3 creds resolve.
    """

    def __init__(self, function_name: Optional[str] = None, region: Optional[str] = None):
        self.function_name = function_name or os.getenv("LAMBDA_RUNBOOK_FUNCTION")
        self.region        = region        or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if self.function_name and _have_aws_credentials():
            try:
                self._client = _client("lambda", self.region)
                self._client.get_function(FunctionName=self.function_name)
                self.enabled = True
                log.info("Lambda invoker: %s", self.function_name)
            except Exception as e:
                log.warning("Lambda disabled (%s)", e)

    def invoke(self, payload: dict) -> dict:
        if not self.enabled or self._client is None:
            return {"ok": False, "error": "lambda not configured"}
        try:
            resp = self._client.invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload, default=str).encode("utf-8"),
            )
            body = resp.get("Payload")
            return {
                "ok":          resp.get("StatusCode", 500) < 300,
                "status":      resp.get("StatusCode"),
                "body":        body.read().decode("utf-8", errors="replace") if body else "",
                "function_error": resp.get("FunctionError"),
            }
        except Exception as e:
            log.warning("lambda invoke failed: %s", e)
            return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# EventBridge publisher
# ---------------------------------------------------------------------------

class EventBridgePublisher:
    """Publish a structured event to an EventBridge bus so other workloads
    (e.g. PagerDuty integration) can react.

    Enabled when `EVENTBRIDGE_BUS_NAME` is set and boto3 creds resolve.
    """

    def __init__(self, bus_name: Optional[str] = None, region: Optional[str] = None):
        self.bus_name = bus_name or os.getenv("EVENTBRIDGE_BUS_NAME", "default")
        self.source   = os.getenv("EVENTBRIDGE_SOURCE", "incident-commander.agent")
        self.region   = region or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if _have_aws_credentials():
            try:
                self._client = _client("events", self.region)
                self._client.describe_event_bus(Name=self.bus_name)
                self.enabled = True
                log.info("EventBridge publisher: bus=%s source=%s",
                         self.bus_name, self.source)
            except Exception as e:
                log.warning("EventBridge disabled (%s)", e)

    def publish(self, detail_type: str, detail: dict) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            self._client.put_events(Entries=[{
                "Source":       self.source,
                "DetailType":   detail_type,
                "Detail":       json.dumps(detail, default=str),
                "EventBusName": self.bus_name,
            }])
            return True
        except Exception as e:
            log.warning("eventbridge put_events failed: %s", e)
            return False


# ---------------------------------------------------------------------------
# X-Ray trace reader (read-only)
# ---------------------------------------------------------------------------

class XRayTraceReader:
    """List recent X-Ray trace summaries so the agent can correlate latency
    spikes with downstream calls.

    Enabled when `XRAY_ENABLED` is truthy and boto3 creds resolve.
    """

    def __init__(self, region: Optional[str] = None):
        self.region = region or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if os.getenv("XRAY_ENABLED", "").lower() in ("1", "true", "yes") \
                and _have_aws_credentials():
            try:
                self._client = _client("xray", self.region)
                # cheap probe — list_groups is always allowed if xray:* granted
                self._client.get_groups()
                self.enabled = True
                log.info("X-Ray reader enabled")
            except Exception as e:
                log.warning("X-Ray disabled (%s)", e)

    def recent_traces(self, last_minutes: int = 5, limit: int = 20) -> list[dict]:
        if not self.enabled or self._client is None:
            return []
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        end   = _dt.now(_tz.utc)
        start = end - _td(minutes=last_minutes)
        try:
            resp = self._client.get_trace_summaries(StartTime=start, EndTime=end)
            out: list[dict] = []
            for s in resp.get("TraceSummaries", [])[:limit]:
                out.append({
                    "id":       s.get("Id"),
                    "duration": s.get("Duration"),
                    "has_error": bool(s.get("HasError")),
                    "has_fault": bool(s.get("HasFault")),
                    "http":     s.get("Http", {}),
                })
            return out
        except Exception as e:
            log.warning("xray get_trace_summaries failed: %s", e)
            return []


# ---------------------------------------------------------------------------
# SSM Parameter Store reader
# ---------------------------------------------------------------------------

class SSMParameterReader:
    """Read SSM parameters used as runtime feature flags / config values.

    Enabled when boto3 creds resolve. Fails closed (returns None) on errors.
    """

    def __init__(self, region: Optional[str] = None):
        self.region = region or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if _have_aws_credentials():
            try:
                self._client = _client("ssm", self.region)
                self.enabled = True
                log.info("SSM parameter reader enabled")
            except Exception as e:
                log.warning("SSM disabled (%s)", e)

    def get(self, name: str, with_decryption: bool = True) -> Optional[str]:
        if not self.enabled or self._client is None:
            return None
        try:
            resp = self._client.get_parameter(Name=name, WithDecryption=with_decryption)
            return (resp.get("Parameter") or {}).get("Value")
        except Exception as e:
            log.warning("ssm get_parameter(%s) failed: %s", name, e)
            return None


# ---------------------------------------------------------------------------
# KMS — small data-key generator for envelope encryption tests
# ---------------------------------------------------------------------------

class KMSDataKeyClient:
    """Generate data keys to verify the agent's KMS permissions are wired up.

    Enabled when `KMS_KEY_ID` is set and boto3 creds resolve.
    """

    def __init__(self, key_id: Optional[str] = None, region: Optional[str] = None):
        self.key_id = key_id or os.getenv("KMS_KEY_ID")
        self.region = region or os.getenv("AWS_REGION")
        self._client = None
        self.enabled = False
        if self.key_id and _have_aws_credentials():
            try:
                self._client = _client("kms", self.region)
                self._client.describe_key(KeyId=self.key_id)
                self.enabled = True
                log.info("KMS data-key client: %s", self.key_id)
            except Exception as e:
                log.warning("KMS disabled (%s)", e)

    def generate_data_key(self, spec: str = "AES_256") -> Optional[dict]:
        if not self.enabled or self._client is None:
            return None
        try:
            resp = self._client.generate_data_key(KeyId=self.key_id, KeySpec=spec)
            return {
                "ciphertext_b64_len": len(resp.get("CiphertextBlob", b"")),
                "plaintext_bytes":    len(resp.get("Plaintext", b"")),
                "key_id":             resp.get("KeyId"),
            }
        except Exception as e:
            log.warning("kms generate_data_key failed: %s", e)
            return None


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
    sqs  = SQSEventPublisher()
    lam  = LambdaInvoker()
    eb   = EventBridgePublisher()
    xr   = XRayTraceReader()
    ssm  = SSMParameterReader()
    kms  = KMSDataKeyClient()

    _svc("CloudWatch Logs",   cw.enabled,   {"log_group": cw.log_group})
    _svc("S3",                s3.enabled,   {"bucket": s3.bucket, "prefix": s3.prefix})
    _svc("DynamoDB",          dyn.enabled,  {"table": dyn.table_name})
    _svc("CloudWatch Metrics",cwm.enabled,  {"namespace": cwm.namespace})
    _svc("SNS",               sns.enabled,  {"topic": sns.topic_arn})
    _svc("Secrets Manager",   sec.enabled,  {"configured_secret": os.getenv("OPENAI_SECRET_ARN")})
    _svc("SQS",               sqs.enabled,  {"queue": sqs.queue_url})
    _svc("Lambda",            lam.enabled,  {"function": lam.function_name})
    _svc("EventBridge",       eb.enabled,   {"bus": eb.bus_name, "source": eb.source})
    _svc("X-Ray",             xr.enabled,   {"note": "set XRAY_ENABLED=1 to probe"})
    _svc("SSM",               ssm.enabled,  {"note": "GetParameter access"})
    _svc("KMS",               kms.enabled,  {"key_id": kms.key_id})
    _svc("EKS",               bool(os.getenv("EKS_CLUSTER_NAME")),
                                             {"cluster": os.getenv("EKS_CLUSTER_NAME")})
    _svc("ECR",               bool(os.getenv("ECR_REPOSITORY_URL")),
                                             {"repo": os.getenv("ECR_REPOSITORY_URL")})
    _svc("Bedrock",           bool(status["region"]),
                                             {"note": "IAM policy grants bedrock:InvokeModel"})

    return status
