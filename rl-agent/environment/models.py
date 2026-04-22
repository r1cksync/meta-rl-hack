"""IncidentCommander RL Environment — Pydantic Models

Typed observation, action, and reward models for the OpenEnv spec.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class HealthStatus(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class TimePressure(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionType(str, Enum):
    QUERY_LOGS = "query_logs"
    QUERY_METRICS = "query_metrics"
    GET_SERVICE_DEPENDENCIES = "get_service_dependencies"
    GET_TRACE = "get_trace"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    RESTART_PODS = "restart_pods"
    SCALE_DEPLOYMENT = "scale_deployment"
    APPLY_CONFIG_PATCH = "apply_config_patch"
    DELETE_CHAOS_EXPERIMENT = "delete_chaos_experiment"
    SUBMIT_POSTMORTEM = "submit_postmortem"
    EXEC_KUBECTL = "exec_kubectl"


WRITE_ACTIONS = {
    ActionType.ROLLBACK_DEPLOYMENT,
    ActionType.RESTART_PODS,
    ActionType.SCALE_DEPLOYMENT,
    ActionType.APPLY_CONFIG_PATCH,
    ActionType.DELETE_CHAOS_EXPERIMENT,
}

READ_ACTIONS = {
    ActionType.QUERY_LOGS,
    ActionType.QUERY_METRICS,
    ActionType.GET_SERVICE_DEPENDENCIES,
    ActionType.GET_TRACE,
}

# ---------------------------------------------------------------------------
# Observation Components
# ---------------------------------------------------------------------------

class Alert(BaseModel):
    alert_name: str
    severity: Severity
    service: str
    firing_since: datetime
    annotations: dict[str, str] = Field(default_factory=dict)


class LogLine(BaseModel):
    timestamp: datetime
    service: str
    level: str  # ERROR, WARN, INFO, DEBUG
    message: str
    request_id: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ServiceStatus(BaseModel):
    name: str
    health: HealthStatus
    error_rate_2m: float
    p99_latency_ms: float
    replica_count: int
    ready_replicas: int


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class Observation(BaseModel):
    timestamp: datetime
    active_alerts: list[Alert] = Field(default_factory=list)
    recent_logs: list[LogLine] = Field(default_factory=list)
    service_health: dict[str, ServiceStatus] = Field(default_factory=dict)
    blast_radius_pct: float = 0.0
    step_count: int = 0
    last_action_result: str = ""
    available_actions: list[str] = Field(default_factory=list)
    simulated_time_pressure: TimePressure = TimePressure.LOW


class Action(BaseModel):
    type: ActionType
    params: dict[str, Any] = Field(default_factory=dict)


class Reward(BaseModel):
    total: float
    breakdown: dict[str, float] = Field(default_factory=dict)


class StepResult(BaseModel):
    observation: Observation
    reward: float
    done: bool
    info: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Task Scenario Definition
# ---------------------------------------------------------------------------

class TaskScenario(BaseModel):
    task_id: str
    difficulty: str
    target_score: float
    fault_type: str
    chaos_experiment_name: Optional[str] = None
    ground_truth_root_cause: str
    correct_mitigation_action: str
    correct_mitigation_target: str
    wrong_mitigation_penalty_services: list[str] = Field(default_factory=list)
    useful_log_keywords: list[str] = Field(default_factory=list)
    red_herrings: list[str] = Field(default_factory=list)
    reference_postmortem: str = ""


# ---------------------------------------------------------------------------
# Dependency Graph (Static)
# ---------------------------------------------------------------------------

SERVICE_DEPENDENCIES: dict[str, list[str]] = {
    "payments-api": ["postgres", "kafka"],
    "inventory-service": ["redis", "postgres", "kafka"],
    "order-worker": ["redis", "kafka", "payments-api", "inventory-service", "notification-service"],
    "notification-service": ["smtp"],
    "checkout-frontend": ["payments-api", "inventory-service"],
}
