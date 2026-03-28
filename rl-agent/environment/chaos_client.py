"""Chaos Mesh HTTP API client (async)."""

from __future__ import annotations

from typing import Any

import httpx


class ChaosMeshClient:
    """Async client for Chaos Mesh HTTP API."""

    def __init__(
        self,
        chaos_url: str = "http://localhost:2333",
        timeout: float = 5.0,
    ):
        self._url = chaos_url.rstrip("/")
        self._timeout = timeout

    async def create_experiment(self, experiment_yaml: dict[str, Any]) -> str:
        """Create a new Chaos Mesh experiment. Returns experiment_id."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(f"{self._url}/api/v1/experiments", json=experiment_yaml)
            r.raise_for_status()
            data = r.json()
            return data.get("uid", data.get("id", ""))

    async def delete_experiment(self, experiment_id: str) -> None:
        """Delete a Chaos Mesh experiment by ID or name."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.delete(f"{self._url}/api/v1/experiments/{experiment_id}")
            r.raise_for_status()

    async def list_experiments(self) -> list[dict[str, Any]]:
        """List all Chaos Mesh experiments."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(f"{self._url}/api/v1/experiments")
            r.raise_for_status()
            return r.json()

    async def get_experiment_status(self, experiment_id: str) -> str:
        """Get experiment status: Running, Paused, Finished, Error."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(f"{self._url}/api/v1/experiments/{experiment_id}")
            r.raise_for_status()
            data = r.json()
            return data.get("status", "Unknown")
