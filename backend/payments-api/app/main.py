"""Payments API — FastAPI app for processing orders."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

from .database import engine, async_session, init_db
from .models import Order, OrderItem
from .kafka_producer import get_producer, send_event

# ---------------------------------------------------------------------------
# Structured Logging
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)
logger = structlog.get_logger(service="payments-api")

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)
DB_POOL_SIZE = Gauge("db_connection_pool_size", "Database connection pool size")
ORDERS_CREATED = Counter("orders_created_total", "Total orders created")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    DB_POOL_SIZE.set(int(os.getenv("DB_POOL_SIZE", "10")))
    yield
    await engine.dispose()


app = FastAPI(
    title="Payments API",
    version=os.getenv("SERVICE_VERSION", "2.3.0"),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware — request ID + metrics
# ---------------------------------------------------------------------------

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    import time
    start = time.perf_counter()

    response: Response = await call_next(request)

    duration = time.perf_counter() - start
    endpoint = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=response.status_code,
    ).inc()
    REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(duration)

    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class OrderItemIn(BaseModel):
    product_id: str
    quantity: int
    unit_price: float


class CreateOrderRequest(BaseModel):
    customer_name: str
    customer_email: str
    items: list[OrderItemIn]


class OrderResponse(BaseModel):
    order_id: str
    status: str
    total_amount: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/orders", response_model=OrderResponse)
async def create_order(req: CreateOrderRequest):
    order_id = str(uuid.uuid4())

    # Compute total with 4-decimal precision
    total = sum(Decimal(str(item.unit_price)) * item.quantity for item in req.items)
    total_amount = float(total.quantize(Decimal("0.0001")))

    async with async_session() as session:
        order = Order(
            order_id=order_id,
            customer_name=req.customer_name,
            customer_email=req.customer_email,
            status="PENDING",
            total_amount=total_amount,
        )
        session.add(order)

        for item in req.items:
            session.add(OrderItem(
                order_id=order_id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
            ))

        await session.commit()

    logger.info("order_created", order_id=order_id, total_amount=total_amount)
    ORDERS_CREATED.inc()

    # Publish Kafka event
    try:
        await send_event("orders", "order.created", {
            "order_id": order_id,
            "customer_name": req.customer_name,
            "customer_email": req.customer_email,
            "total_amount": total_amount,
            "items": [i.model_dump() for i in req.items],
        })
    except Exception as e:
        logger.warning("kafka_publish_failed", order_id=order_id, error=str(e))

    return OrderResponse(order_id=order_id, status="PENDING", total_amount=total_amount)


@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str):
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.order_id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return OrderResponse(
            order_id=order.order_id,
            status=order.status,
            total_amount=float(order.total_amount),
        )


@app.get("/health")
async def health():
    db_ok = True
    kafka_ok = True

    try:
        async with async_session() as session:
            await session.execute("SELECT 1")
    except Exception:
        db_ok = False

    try:
        producer = await get_producer()
        kafka_ok = producer is not None
    except Exception:
        kafka_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "kafka": "ok" if kafka_ok else "error",
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
