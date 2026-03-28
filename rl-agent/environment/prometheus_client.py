"""Prometheus & Alertmanager HTTP client (async)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx


class PrometheusClient:
    """Async client for Prometheus and Alertmanager HTTP APIs."""

    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        alertmanager_url: str = "http://localhost:9093",
        timeout: float = 5.0,
        max_retries: int = 3,
    ):
        self._prom_url = prometheus_url.rstrip("/")
        self._am_url = alertmanager_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries

    # ---- helpers ----------------------------------------------------------

    async def _get(self, url: str) -> dict[str, Any]:
        last_exc: Exception | None = None
        for _ in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    r = await c.get(url)
                    r.raise_for_status()
                    return r.json()
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
        raise RuntimeError(f"Prometheus request failed after {self._max_retries} retries: {last_exc}")

    # ---- Prometheus -------------------------------------------------------

    async def query_instant(self, promql: str) -> float:
        """Execute an instant PromQL query, return scalar value."""
        data = await self._get(f"{self._prom_url}/api/v1/query?query={httpx.QueryParams({'query': promql})}")
        results = data.get("data", {}).get("result", [])
        if not results:
            return 0.0
        value = results[0].get("value", [None, "0"])
        try:
            return float(value[1])
        except (IndexError, ValueError, TypeError):
            return 0.0

    async def query_range(
        self,
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "15s",
    ) -> list[dict[str, Any]]:
        """Execute a range PromQL query."""
        params = {
            "query": promql,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": step,
        }
        url = f"{self._prom_url}/api/v1/query_range?{httpx.QueryParams(params)}"
        data = await self._get(url)
        return data.get("data", {}).get("result", [])

    # ---- Alertmanager -----------------------------------------------------

    async def get_all_active_alerts(self) -> list[dict[str, Any]]:
        """Fetch all active alerts from Alertmanager."""
        try:
            return await self._get(f"{self._am_url}/api/v2/alerts")
        except RuntimeError:
            return []
