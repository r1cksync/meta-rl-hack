"""AWS integrations for IncidentCommander.

Two optional utilities, both fully no-op when the required env vars /
credentials are missing:

* `CloudWatchLogsReader` — pulls pod logs from CloudWatch Container Insights
  so the agent's `query_logs` action returns real production-style lines
  (not the mock synthetic generator).

* `S3CheckpointUploader` — after every `save_steps` GRPO update, uploads
  the LoRA adapter directory to `s3://$S3_CHECKPOINT_BUCKET/<run>/<step>/`.

Both are gated by env vars so importing them costs nothing on the HF Space.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


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
        if self.region and self.log_group:
            try:
                import boto3  # type: ignore
                self._client = boto3.client("logs", region_name=self.region)
                # cheap probe
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
        if self.bucket:
            try:
                import boto3  # type: ignore
                self._client = boto3.client("s3")
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
