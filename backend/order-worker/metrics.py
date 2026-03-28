"""Prometheus metrics server for order-worker (side-thread)."""

from __future__ import annotations

import os
import threading

from prometheus_client import Counter, Histogram, Gauge, start_http_server

CELERY_TASKS_TOTAL = Counter(
    "celery_tasks_total",
    "Total Celery tasks",
    ["task_name", "status"],
)
CELERY_TASK_DURATION = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration",
    ["task_name"],
)
CELERY_ACTIVE_TASKS = Gauge("celery_active_tasks", "Number of active Celery tasks")

METRICS_PORT = int(os.getenv("METRICS_PORT", "4004"))


def start_metrics_server():
    """Start Prometheus metrics HTTP server in a background thread."""
    thread = threading.Thread(
        target=start_http_server,
        args=(METRICS_PORT,),
        daemon=True,
    )
    thread.start()


# Auto-start when imported
start_metrics_server()
