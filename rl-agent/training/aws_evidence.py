"""Real AWS evidence recorder for training.

This is what fixes the "S3 bucket is empty / nothing actually used AWS" issue.
During every training run we:

  * Upload every snapshot file in the run dir to s3://$S3_CHECKPOINT_BUCKET/runs/<ts>/
  * Write per-task mastery rows into DynamoDB ($DYNAMODB_CURRICULUM_TABLE)
  * Publish a CloudWatch metric per update (mean_reward, reward_std, mit_rate)
  * Publish a single SNS notification per training run (when a topic is set)
  * Append an `aws_evidence.json` snapshot in the run dir summarising every
    real AWS interaction so the HF Space dashboard can render it WITHOUT
    needing AWS credentials at runtime.

If credentials are missing, every call is a recorded no-op so the dashboard
still gets a clear "we tried; no creds in this environment" line.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _have_creds() -> bool:
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.getenv("AWS_PROFILE") or os.getenv("AWS_ROLE_ARN"):
        return True
    home = os.path.expanduser("~/.aws/credentials")
    return os.path.exists(home)


def load_dotenv(path: str | Path) -> int:
    """Tiny dotenv loader — no extra dep, only sets keys not already set."""
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


class AwsEvidenceRecorder:
    """Captures every real AWS interaction during a training run."""

    def __init__(self, region: str | None = None):
        self.region = region or os.getenv("AWS_REGION") or "us-east-1"
        self.evidence: dict[str, Any] = {
            "started_at":          int(time.time()),
            "region":              self.region,
            "creds_detected":      _have_creds(),
            "account_id":          None,
            "s3":                  {"bucket": os.getenv("S3_CHECKPOINT_BUCKET"),
                                    "objects": []},
            "dynamodb":            {"table": os.getenv("DYNAMODB_CURRICULUM_TABLE"),
                                    "writes": []},
            "cloudwatch_metrics":  {"namespace": os.getenv(
                                        "CLOUDWATCH_METRIC_NAMESPACE",
                                        "IncidentCommander"),
                                    "datapoints": []},
            "cloudwatch_logs":     {"log_group": os.getenv("CLOUDWATCH_LOG_GROUP"),
                                    "events": []},
            "sns":                 {"topic_arn": os.getenv("SNS_ALERTS_TOPIC_ARN"),
                                    "messages": []},
            "sqs":                 {"queue_url": os.getenv("SQS_QUEUE_URL"),
                                    "messages": []},
            "eventbridge":         {"bus": os.getenv("EVENTBRIDGE_BUS_NAME", "default"),
                                    "events": []},
            "secrets_manager":     {"loaded": []},
            "errors":              [],
        }
        self._clients: dict[str, Any] = {}
        self.enabled = self.evidence["creds_detected"]
        if self.enabled:
            try:
                sts = self._client("sts")
                self.evidence["account_id"] = sts.get_caller_identity().get("Account")
                log.info("AWS evidence recorder: account=%s region=%s",
                         self.evidence["account_id"], self.region)
            except Exception as e:
                self._err("sts.get_caller_identity", e)

    # ------------------------------------------------------------------
    def _client(self, service: str):
        if service in self._clients:
            return self._clients[service]
        import boto3                                            # type: ignore
        from botocore.config import Config                       # type: ignore
        cfg = Config(connect_timeout=3, read_timeout=8,
                     retries={"max_attempts": 2})
        c = boto3.client(service, region_name=self.region, config=cfg)
        self._clients[service] = c
        return c

    def _err(self, op: str, e: Exception) -> None:
        msg = f"{op}: {type(e).__name__}: {str(e)[:200]}"
        log.warning("AWS recorder error %s", msg)
        self.evidence["errors"].append({"op": op, "error": msg,
                                        "ts": int(time.time())})

    # ------------------------------------------------------------------
    # S3 — upload every file in run dir under runs/<ts>/<basename>/...
    # ------------------------------------------------------------------
    def upload_run_dir(self, run_dir: Path, prefix: str | None = None) -> int:
        bucket = self.evidence["s3"]["bucket"]
        if not bucket or not self.enabled:
            return 0
        run_dir = Path(run_dir)
        if not run_dir.exists():
            return 0
        try:
            s3 = self._client("s3")
        except Exception as e:
            self._err("s3.client", e); return 0
        ts = int(time.time())
        prefix = prefix or f"runs/{ts}-{run_dir.name}"
        n = 0
        for f in run_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(run_dir).as_posix()
            key = f"{prefix}/{rel}"
            try:
                ctype = ("application/json" if f.suffix in (".json", ".jsonl")
                         else "text/plain")
                s3.upload_file(str(f), bucket, key,
                               ExtraArgs={"ContentType": ctype})
                self.evidence["s3"]["objects"].append({
                    "key": key, "bytes": f.stat().st_size,
                    "uri": f"s3://{bucket}/{key}",
                })
                n += 1
            except Exception as e:
                self._err(f"s3.upload_file:{key}", e)
        log.info("S3: uploaded %d files to s3://%s/%s/", n, bucket, prefix)
        self.evidence["s3"]["last_prefix"] = prefix
        return n

    # ------------------------------------------------------------------
    # DynamoDB — write per-task mastery rows.
    # ------------------------------------------------------------------
    def write_curriculum(self, run_id: str, mastery: dict[str, float],
                         tier: str) -> int:
        table = self.evidence["dynamodb"]["table"]
        if not table or not self.enabled:
            return 0
        try:
            ddb = self._client("dynamodb")
        except Exception as e:
            self._err("dynamodb.client", e); return 0
        n = 0
        for task_id, m in mastery.items():
            try:
                ddb.put_item(TableName=table, Item={
                    "run_id":  {"S": run_id},
                    "task_id": {"S": task_id},
                    "mastery": {"N": f"{float(m):.4f}"},
                    "tier":    {"S": tier},
                    "ts":      {"N": str(int(time.time()))},
                })
                self.evidence["dynamodb"]["writes"].append({
                    "run_id": run_id, "task_id": task_id,
                    "mastery": float(m), "tier": tier,
                })
                n += 1
            except Exception as e:
                self._err(f"dynamodb.put_item:{task_id}", e)
                # If table doesn't exist, stop trying.
                if "ResourceNotFoundException" in str(e):
                    break
        log.info("DynamoDB: wrote %d rows to %s", n, table)
        return n

    # ------------------------------------------------------------------
    # CloudWatch custom metrics.
    # ------------------------------------------------------------------
    def publish_metric(self, name: str, value: float, unit: str = "None",
                       dims: dict[str, str] | None = None) -> bool:
        if not self.enabled:
            return False
        ns = self.evidence["cloudwatch_metrics"]["namespace"]
        try:
            cw = self._client("cloudwatch")
            cw.put_metric_data(Namespace=ns, MetricData=[{
                "MetricName": name,
                "Value": float(value),
                "Unit": unit,
                "Dimensions": [{"Name": k, "Value": str(v)}
                               for k, v in (dims or {}).items()],
            }])
            self.evidence["cloudwatch_metrics"]["datapoints"].append({
                "metric": name, "value": float(value),
                "unit": unit, "dims": dims or {},
                "ts": int(time.time()),
            })
            return True
        except Exception as e:
            self._err(f"cloudwatch.put_metric_data:{name}", e)
            return False

    # ------------------------------------------------------------------
    # CloudWatch Logs — write a structured event line per training update.
    # ------------------------------------------------------------------
    def log_event(self, message: dict) -> bool:
        lg = self.evidence["cloudwatch_logs"]["log_group"]
        if not lg or not self.enabled:
            return False
        try:
            cwl = self._client("logs")
            stream = f"trainer-{int(time.time() // 3600)}"
            try:
                cwl.create_log_stream(logGroupName=lg, logStreamName=stream)
            except Exception:
                pass  # already exists
            cwl.put_log_events(
                logGroupName=lg, logStreamName=stream,
                logEvents=[{"timestamp": int(time.time() * 1000),
                            "message": json.dumps(message, default=str)}],
            )
            self.evidence["cloudwatch_logs"]["events"].append({
                "stream": stream, "msg_keys": list(message.keys()),
                "ts": int(time.time()),
            })
            return True
        except Exception as e:
            self._err("logs.put_log_events", e)
            return False

    # ------------------------------------------------------------------
    # SNS — single training-summary publish.
    # ------------------------------------------------------------------
    def publish_summary(self, summary: dict) -> bool:
        topic = self.evidence["sns"]["topic_arn"]
        if not topic or not self.enabled:
            return False
        try:
            sns = self._client("sns")
            sns.publish(
                TopicArn=topic,
                Subject=f"IC training run {summary.get('mode','?')} done",
                Message=json.dumps(summary, default=str)[:32000],
            )
            self.evidence["sns"]["messages"].append({
                "topic": topic, "ts": int(time.time()),
                "subject": summary.get("mode", "?"),
            })
            return True
        except Exception as e:
            self._err("sns.publish", e)
            return False

    # ------------------------------------------------------------------
    # SQS — push a per-update event so a side-car Lambda can consume.
    # ------------------------------------------------------------------
    def publish_sqs(self, body: dict) -> bool:
        q = self.evidence["sqs"]["queue_url"]
        if not q or not self.enabled:
            return False
        try:
            sqs = self._client("sqs")
            kwargs: dict[str, Any] = {"QueueUrl": q,
                                      "MessageBody": json.dumps(body, default=str)}
            if q.endswith(".fifo"):
                kwargs["MessageGroupId"]         = "trainer"
                kwargs["MessageDeduplicationId"] = f"t-{int(time.time()*1000)}"
            sqs.send_message(**kwargs)
            self.evidence["sqs"]["messages"].append({
                "queue": q, "ts": int(time.time()),
                "kind":  body.get("kind", "training_update"),
            })
            return True
        except Exception as e:
            self._err("sqs.send_message", e)
            return False

    # ------------------------------------------------------------------
    # EventBridge — emit a structured event for downstream automations.
    # ------------------------------------------------------------------
    def publish_event(self, detail_type: str, detail: dict) -> bool:
        if not self.enabled:
            return False
        bus = self.evidence["eventbridge"]["bus"]
        try:
            eb = self._client("events")
            eb.put_events(Entries=[{
                "Source":       os.getenv("EVENTBRIDGE_SOURCE",
                                          "incident-commander.trainer"),
                "DetailType":   detail_type,
                "Detail":       json.dumps(detail, default=str),
                "EventBusName": bus,
            }])
            self.evidence["eventbridge"]["events"].append({
                "bus": bus, "detail_type": detail_type,
                "ts": int(time.time()),
            })
            return True
        except Exception as e:
            self._err("eventbridge.put_events", e)
            return False

    # ------------------------------------------------------------------
    def write_evidence_file(self, out_dir: Path) -> Path:
        out = Path(out_dir) / "aws_evidence.json"
        self.evidence["finished_at"] = int(time.time())
        # Quick summary for the dashboard.
        self.evidence["summary"] = {
            "s3_objects":               len(self.evidence["s3"]["objects"]),
            "dynamodb_writes":          len(self.evidence["dynamodb"]["writes"]),
            "cloudwatch_datapoints":    len(self.evidence["cloudwatch_metrics"]["datapoints"]),
            "cloudwatch_log_events":    len(self.evidence["cloudwatch_logs"]["events"]),
            "sns_messages":             len(self.evidence["sns"]["messages"]),
            "sqs_messages":             len(self.evidence["sqs"]["messages"]),
            "eventbridge_events":       len(self.evidence["eventbridge"]["events"]),
            "errors":                   len(self.evidence["errors"]),
        }
        out.write_text(json.dumps(self.evidence, indent=2, default=str))
        return out
