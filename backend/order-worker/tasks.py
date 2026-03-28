"""Celery tasks for order processing."""

from __future__ import annotations

import os
import time
import random

import httpx
import structlog

from worker import app

logger = structlog.get_logger(service="order-worker")

PAYMENTS_API_URL = os.getenv("PAYMENTS_API_URL", "http://localhost:4001")
INVENTORY_API_URL = os.getenv("INVENTORY_API_URL", "http://localhost:4002")
NOTIFICATION_API_URL = os.getenv("NOTIFICATION_API_URL", "http://localhost:4003")


@app.task(bind=True, name="process_order", max_retries=3)
def process_order(self, order_id: str):
    """Fetch order, reserve stock, update to PROCESSING."""
    logger.info("processing_order", order_id=order_id)

    try:
        # Fetch order details
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{PAYMENTS_API_URL}/orders/{order_id}")
            resp.raise_for_status()
            order = resp.json()

        # Reserve stock for each item (simplified: just call reserve)
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{INVENTORY_API_URL}/products/PROD-001/reserve",
                json={"quantity": 1},
            )

        logger.info("order_processing", order_id=order_id, status="PROCESSING")

        # Chain to fulfillment
        fulfill_order.apply_async(args=[order_id], countdown=2)

    except Exception as exc:
        logger.error("process_order_failed", order_id=order_id, error=str(exc))
        raise self.retry(exc=exc, countdown=5)


@app.task(bind=True, name="fulfill_order", max_retries=3)
def fulfill_order(self, order_id: str):
    """Simulate fulfillment, update status, send notification."""
    logger.info("fulfilling_order", order_id=order_id)

    # Simulate 2-5 second fulfillment
    time.sleep(random.uniform(2, 5))

    try:
        # Send notification
        with httpx.Client(timeout=10) as client:
            client.post(f"{NOTIFICATION_API_URL}/notify", json={
                "order_id": order_id,
                "customer_email": "customer@example.com",
                "customer_name": "Customer",
                "total_amount": 0.0,
            })

        logger.info("order_fulfilled", order_id=order_id, status="FULFILLED")

    except Exception as exc:
        logger.error("fulfill_order_failed", order_id=order_id, error=str(exc))
        raise self.retry(exc=exc, countdown=5)
