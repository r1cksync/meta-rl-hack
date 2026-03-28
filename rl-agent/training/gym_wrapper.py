"""Gymnasium wrapper for IncidentCommanderEnv — SB3 compatibility."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from environment.env import IncidentCommanderEnv
from environment.models import Action, ActionType

# Discrete action list (each action has a fixed parameterization for PPO)
DISCRETE_ACTIONS: list[tuple[str, dict[str, Any]]] = [
    # Read actions (investigation)
    ("query_logs", {"service": "payments-api", "last_minutes": 5}),
    ("query_logs", {"service": "inventory-service", "last_minutes": 5}),
    ("query_logs", {"service": "order-worker", "last_minutes": 5}),
    ("query_logs", {"service": "notification-service", "last_minutes": 5}),
    ("query_logs", {"service": "payments-api", "last_minutes": 5, "filter_text": "error"}),
    ("query_logs", {"service": "inventory-service", "last_minutes": 5, "filter_text": "redis"}),
    ("query_logs", {"service": "payments-api", "last_minutes": 5, "filter_text": "OOM"}),
    ("query_logs", {"service": "payments-api", "last_minutes": 5, "filter_text": "decimal"}),
    ("query_metrics", {"promql": 'rate(http_requests_total{app="payments-api",status_code=~"5.."}[2m])'}),
    ("query_metrics", {"promql": 'rate(http_requests_total{app="inventory-service",status_code=~"5.."}[2m])'}),
    ("query_metrics", {"promql": 'container_memory_working_set_bytes{pod=~"payments-api-.*"}'}),
    ("query_metrics", {"promql": 'redis_connection_pool_size{app="inventory-service"}'}),
    ("get_service_dependencies", {"service": "payments-api"}),
    ("get_service_dependencies", {"service": "inventory-service"}),
    ("get_service_dependencies", {"service": "order-worker"}),

    # Write actions (mitigation)
    ("rollback_deployment", {"deployment": "payments-api"}),
    ("rollback_deployment", {"deployment": "inventory-service"}),
    ("restart_pods", {"deployment": "payments-api"}),
    ("restart_pods", {"deployment": "inventory-service"}),
    ("scale_deployment", {"deployment": "payments-api", "replicas": 4}),
    ("delete_chaos_experiment", {"experiment_name": "redis-latency-inject"}),
    ("delete_chaos_experiment", {"experiment_name": "payments-memory-stress"}),

    # Postmortem submissions
    ("submit_postmortem", {
        "root_cause": "redis_connection_pool_exhaustion",
        "timeline": "T+00:00 alert fired, T+00:01 investigated logs, T+00:02 found Redis pool errors, T+00:03 deleted chaos experiment",
        "mitigations": "Deleted chaos experiment redis-latency-inject to remove injected network latency",
        "affected_services": ["inventory-service"],
        "recommended_followups": "Increase Redis connection pool size from 10 to 20, add circuit breaker"
    }),
    ("submit_postmortem", {
        "root_cause": "payments_api_oom_memory_leak",
        "timeline": "T+00:00 alert fired on payments-api, T+00:01 checked logs found OOMKilled, T+00:02 inventory lag was cascade, T+00:03 rolled back payments-api",
        "mitigations": "Rolled back payments-api deployment to previous stable revision",
        "affected_services": ["payments-api", "inventory-service"],
        "recommended_followups": "Set memory resource limits on payments-api, add OOM alerting"
    }),
    ("submit_postmortem", {
        "root_cause": "payments_decimal_serialization_bug_v2_3_2",
        "timeline": "T-06:00 v2.3.2 deployed, T+00:00 postgres VACUUM alert (red herring), T+00:02 found decimal truncation in payments logs, T+00:03 rolled back to v2.3.0",
        "mitigations": "Rolled back payments-api to v2.3.0, identified NUMERIC(12,2) truncation bug in v2.3.2",
        "affected_services": ["payments-api"],
        "recommended_followups": "Data audit of all orders created during v2.3.2 window, add schema validation tests in CI"
    }),
]


class IncidentCommanderGymEnv(gym.Env):
    """Gymnasium wrapper for SB3 compatibility."""

    metadata = {"render_modes": ["ansi"]}

    def __init__(self, task_ids: list[str] | None = None):
        super().__init__()
        self._task_ids = task_ids or ["task1", "task2", "task3"]
        self._task_idx = 0
        self._env = IncidentCommanderEnv(use_mock=True)

        # Action space: discrete index into DISCRETE_ACTIONS
        self.action_space = spaces.Discrete(len(DISCRETE_ACTIONS))

        # Observation space: numeric feature vector
        # [blast_radius_pct, step_count, active_alert_count,
        #  services_in_red_count, err_rate_payments, err_rate_inventory,
        #  err_rate_order_worker, err_rate_notification, err_rate_frontend]
        self.observation_space = spaces.Box(
            low=np.array([0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            high=np.array([100, 20, 20, 5, 1, 1, 1, 1, 1], dtype=np.float32),
        )

    def _obs_to_vec(self, obs) -> np.ndarray:
        services = ["payments-api", "inventory-service", "order-worker",
                     "notification-service", "checkout-frontend"]
        err_rates = [obs.service_health.get(s, None) for s in services]
        red_count = sum(1 for s in err_rates if s and s.health.value == "red")
        rates = [s.error_rate_2m if s else 0.0 for s in err_rates]

        return np.array([
            obs.blast_radius_pct,
            obs.step_count,
            len(obs.active_alerts),
            red_count,
            *rates,
        ], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        task_id = self._task_ids[self._task_idx % len(self._task_ids)]
        self._task_idx += 1
        obs = self._env.reset(task_id)
        return self._obs_to_vec(obs), {"task_id": task_id}

    def step(self, action_idx: int):
        action_name, params = DISCRETE_ACTIONS[action_idx]
        action = Action(type=ActionType(action_name), params=params)

        result = self._env.step(action)
        vec = self._obs_to_vec(result.observation)

        return vec, result.reward, result.done, False, result.info

    def render(self):
        state = self._env.state()
        return f"Step {state['step_count']} | Blast: {state['blast_radius_pct']:.1f}% | Reward: {state['cumulative_reward']:+.3f}"
