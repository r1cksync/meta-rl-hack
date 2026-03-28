"""Kafka producer for payments-api."""

from __future__ import annotations

import json
import os
from typing import Any

_producer = None


async def get_producer():
    global _producer
    if _producer is not None:
        return _producer
    try:
        from aiokafka import AIOKafkaProducer
        _producer = AIOKafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        )
        await _producer.start()
        return _producer
    except Exception:
        return None


async def send_event(topic: str, event_type: str, data: dict[str, Any]) -> None:
    producer = await get_producer()
    if producer is None:
        return
    message = {"event_type": event_type, "data": data}
    await producer.send_and_wait(topic, value=message)
