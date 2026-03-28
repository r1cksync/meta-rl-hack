"""Loki HTTP client (async)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from .models import LogLine


class LokiClient:
    """Async client for Grafana Loki HTTP API."""

    def __init__(
        self,
        loki_url: str = "http://localhost:3100",
        timeout: float = 5.0,
        max_retries: int = 3,
    ):
        self._url = loki_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_exc: Exception | None = None
        for _ in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    r = await c.get(url, params=params)
                    r.raise_for_status()
                    return r.json()
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
        raise RuntimeError(f"Loki request failed after {self._max_retries} retries: {last_exc}")

    async def query_logs(
        self,
        logql: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[LogLine]:
        """Query Loki for log lines in a time range."""
        params = {
            "query": logql,
            "start": str(int(start.timestamp() * 1e9)),
            "end": str(int(end.timestamp() * 1e9)),
            "limit": str(limit),
            "direction": "backward",
        }
        data = await self._get(f"{self._url}/loki/api/v1/query_range", params=params)
        return self._parse_response(data)

    async def tail_logs(
        self,
        logql: str,
        delay_for: int = 0,
    ) -> AsyncIterator[LogLine]:
        """Tail logs from Loki via WebSocket (simplified: polls query_range)."""
        now = datetime.now(timezone.utc)
        start = datetime.fromtimestamp(now.timestamp() - 60, tz=timezone.utc)
        lines = await self.query_logs(logql, start, now, limit=50)
        for line in lines:
            yield line

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> list[LogLine]:
        """Parse Loki's response format (streams array with values)."""
        lines: list[LogLine] = []
        results = data.get("data", {}).get("result", [])
        for stream in results:
            labels = stream.get("stream", {})
            service = labels.get("app", labels.get("container", "unknown"))
            for value in stream.get("values", []):
                ts_ns, msg = value[0], value[1]
                ts = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)

                # Try to parse structured JSON log
                level = "INFO"
                request_id = None
                extra: dict[str, Any] = {}
                try:
                    import json
                    parsed = json.loads(msg)
                    level = parsed.get("level", "INFO").upper()
                    msg = parsed.get("message", msg)
                    request_id = parsed.get("request_id")
                    extra = {k: v for k, v in parsed.items()
                             if k not in ("level", "message", "request_id", "timestamp", "service")}
                except (json.JSONDecodeError, TypeError):
                    # Not JSON, try to guess level from text
                    for lvl in ("ERROR", "WARN", "WARNING", "DEBUG"):
                        if lvl in msg.upper()[:30]:
                            level = "WARN" if lvl == "WARNING" else lvl
                            break

                lines.append(LogLine(
                    timestamp=ts,
                    service=service,
                    level=level,
                    message=msg,
                    request_id=request_id,
                    extra=extra,
                ))
        return lines
