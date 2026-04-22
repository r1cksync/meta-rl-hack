"""HEALTHY_STATE for IncidentCommander's sample_app.

Used by :class:`K8sBackend.reset_to_healthy` to restore deployments to a known
good spec after each episode. Mirrors kube-sre-gym's approach but spans three
namespaces (payments/frontend/auth) with more deployments per namespace.
"""

from __future__ import annotations

APP_NAMESPACES = ["ic-payments", "ic-frontend", "ic-auth"]

HEALTHY_STATE: dict[str, dict[str, dict]] = {
    "ic-payments": {
        "payments-api": {
            "container_name": "payments-api",
            "image": "python:3.11-slim",
            "replicas": 2,
            "memory_limit": "256Mi",
            "env": {
                "PORT": "8080",
                "DATABASE_URL": "postgres://payments-db.ic-payments.svc.cluster.local:5432/payments",
            },
            "liveness_probe": {"path": "/", "port": 8080},
        },
        "payments-worker": {
            "container_name": "payments-worker",
            "image": "python:3.11-slim",
            "replicas": 2,
            "memory_limit": "256Mi",
            "env": {
                "DATABASE_URL": "postgres://payments-db.ic-payments.svc.cluster.local:5432/payments",
            },
            "liveness_probe": None,
        },
    },
    "ic-frontend": {
        "checkout-frontend": {
            "container_name": "checkout-frontend",
            "image": "nginxinc/nginx-unprivileged:1.27-alpine",
            "replicas": 2,
            "memory_limit": "128Mi",
            "env": {},
            "liveness_probe": {"path": "/", "port": 8080},
        },
        "inventory-service": {
            "container_name": "inventory-service",
            "image": "python:3.11-slim",
            "replicas": 2,
            "memory_limit": "256Mi",
            "env": {
                "REDIS_HOST": "redis.ic-frontend.svc.cluster.local",
            },
            "liveness_probe": {"path": "/", "port": 8080},
        },
    },
    "ic-auth": {
        "auth-service": {
            "container_name": "auth-service",
            "image": "python:3.11-slim",
            "replicas": 2,
            "memory_limit": "256Mi",
            "env": {"JWT_SECRET": "prod-secret-please-rotate"},
            "liveness_probe": {"path": "/", "port": 8080},
        },
    },
}


# Failure types — one more than kube-sre-gym's catalogue.
SUPPORTED_FAULTS = (
    "oom_kill",         # set memory limit to 4Mi → real OOMKill
    "crashloop",        # container command = exit 1 → real CrashLoopBackOff
    "image_pull",       # image = nonexistent tag → real ImagePullBackOff
    "bad_config",       # corrupt env var (e.g. DATABASE_URL) → real app errors
    "scale_zero",       # replicas = 0 → no pods
    "liveness_probe",   # probe path = /nonexistent → liveness failures
    "resource_quota",   # tight ResourceQuota blocks new pods
    "secret_mismatch",  # JWT_SECRET rotation not rolled through
    "wrong_image_tag",  # valid registry but wrong app version
)

# Map each fault to the default namespace/deployment used for single-fault mode.
FAULT_DEFAULT_TARGETS = {
    "oom_kill":        ("ic-payments", "payments-api"),
    "crashloop":       ("ic-payments", "payments-worker"),
    "image_pull":      ("ic-frontend", "checkout-frontend"),
    "bad_config":      ("ic-payments", "payments-worker"),
    "scale_zero":      ("ic-frontend", "checkout-frontend"),
    "liveness_probe":  ("ic-frontend", "inventory-service"),
    "resource_quota":  ("ic-payments", "payments-api"),
    "secret_mismatch": ("ic-auth", "auth-service"),
    "wrong_image_tag": ("ic-frontend", "checkout-frontend"),
}

RESET_POLL_INTERVAL = 2  # seconds between pod-health polls during reset
RESET_MAX_POLLS = 30     # ~60s cap
INJECT_WAIT_DEFAULT = 4  # seconds after injecting before returning
INJECT_VISIBILITY_MAX_POLLS = 15
INJECT_VISIBILITY_INTERVAL = 2
