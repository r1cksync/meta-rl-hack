"""Tests for the Loki client."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from environment.loki_client import LokiClient


@pytest.fixture
def client():
    return LokiClient(loki_url="http://localhost:3100")


class TestLokiClient:
    def test_init(self, client):
        assert client._base_url == "http://localhost:3100"

    @pytest.mark.asyncio
    async def test_query_logs_returns_list(self, client):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "result": [
                    {
                        "stream": {"service": "payments-api"},
                        "values": [
                            ["1700000000000000000", '{"level":"ERROR","message":"test error"}'],
                            ["1700000001000000000", '{"level":"INFO","message":"test info"}'],
                        ],
                    }
                ]
            }
        }
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            now = datetime.now(timezone.utc)
            logs = await client.query_logs(
                '{service="payments-api"}',
                now - timedelta(minutes=5),
                now,
            )
            assert isinstance(logs, list)

    @pytest.mark.asyncio
    async def test_query_logs_empty_result(self, client):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"result": []}}
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            now = datetime.now(timezone.utc)
            logs = await client.query_logs(
                '{service="nonexistent"}',
                now - timedelta(minutes=5),
                now,
            )
            assert logs == []
