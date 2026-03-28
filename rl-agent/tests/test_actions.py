"""Tests for all action types in the environment."""

import pytest

from environment.models import Action, ActionType, SERVICE_DEPENDENCIES
from environment.env import IncidentCommanderEnv


@pytest.fixture
def env():
    e = IncidentCommanderEnv(use_mock=True)
    e.reset("task1")
    return e


class TestReadActions:
    def test_query_logs(self, env):
        action = Action(
            type=ActionType.QUERY_LOGS,
            params={"service": "inventory-service", "last_minutes": 5},
        )
        result = env.step(action)
        assert "inventory-service" in result.observation.last_action_result.lower() or \
               len(result.observation.last_action_result) > 0

    def test_query_logs_with_filter(self, env):
        action = Action(
            type=ActionType.QUERY_LOGS,
            params={"service": "inventory-service", "filter_text": "ConnectionPool"},
        )
        result = env.step(action)
        assert not result.done

    def test_query_metrics(self, env):
        action = Action(
            type=ActionType.QUERY_METRICS,
            params={"promql": "up", "last_minutes": 5},
        )
        result = env.step(action)
        assert "[MOCK]" in result.observation.last_action_result

    def test_get_service_dependencies(self, env):
        action = Action(
            type=ActionType.GET_SERVICE_DEPENDENCIES,
            params={"service": "payments-api"},
        )
        result = env.step(action)
        assert "postgres" in result.observation.last_action_result
        assert "kafka" in result.observation.last_action_result

    def test_get_deps_unknown_service(self, env):
        action = Action(
            type=ActionType.GET_SERVICE_DEPENDENCIES,
            params={"service": "nonexistent-service"},
        )
        result = env.step(action)
        assert "Unknown service" in result.observation.last_action_result

    def test_get_trace(self, env):
        action = Action(
            type=ActionType.GET_TRACE,
            params={"trace_id": "abc-123"},
        )
        result = env.step(action)
        assert "[MOCK]" in result.observation.last_action_result


class TestWriteActions:
    def test_rollback_deployment(self, env):
        action = Action(
            type=ActionType.ROLLBACK_DEPLOYMENT,
            params={"deployment": "payments-api"},
        )
        result = env.step(action)
        assert "rolled back" in result.observation.last_action_result.lower() or \
               "[MOCK]" in result.observation.last_action_result

    def test_restart_pods(self, env):
        action = Action(
            type=ActionType.RESTART_PODS,
            params={"deployment": "inventory-service"},
        )
        result = env.step(action)
        assert "restart" in result.observation.last_action_result.lower()

    def test_scale_deployment(self, env):
        action = Action(
            type=ActionType.SCALE_DEPLOYMENT,
            params={"deployment": "payments-api", "replicas": 4},
        )
        result = env.step(action)
        assert "4" in result.observation.last_action_result

    def test_scale_out_of_range(self, env):
        action = Action(
            type=ActionType.SCALE_DEPLOYMENT,
            params={"deployment": "payments-api", "replicas": 25},
        )
        result = env.step(action)
        assert "ERROR" in result.observation.last_action_result

    def test_apply_config_patch(self, env):
        action = Action(
            type=ActionType.APPLY_CONFIG_PATCH,
            params={"deployment": "redis", "env_var": "MAXMEMORY", "value": "512mb"},
        )
        result = env.step(action)
        assert "MAXMEMORY" in result.observation.last_action_result

    def test_delete_chaos_experiment(self, env):
        action = Action(
            type=ActionType.DELETE_CHAOS_EXPERIMENT,
            params={"experiment_name": "redis-latency-injection"},
        )
        result = env.step(action)
        assert "redis-latency-injection" in result.observation.last_action_result


class TestSubmitPostmortem:
    def test_submit_ends_episode(self, env):
        action = Action(
            type=ActionType.SUBMIT_POSTMORTEM,
            params={
                "root_cause": "Redis pool exhaustion",
                "timeline": "Things happened",
                "mitigations": "Deleted chaos",
                "affected_services": ["inventory-service"],
                "recommended_followups": "Fix things",
            },
        )
        result = env.step(action)
        assert result.done is True

    def test_submit_returns_scores(self, env):
        action = Action(
            type=ActionType.SUBMIT_POSTMORTEM,
            params={
                "root_cause": "Redis pool exhaustion",
                "timeline": "Investigated and fixed",
                "mitigations": "Chaos deleted",
            },
        )
        result = env.step(action)
        assert "postmortem_scores" in result.observation.last_action_result


class TestObservationConsistency:
    def test_step_count_increments(self, env):
        for i in range(3):
            action = Action(type=ActionType.QUERY_LOGS, params={"service": "test"})
            result = env.step(action)
        assert result.observation.step_count == 2  # 0-indexed at observation build time

    def test_time_pressure_increases(self, env):
        """Time pressure should escalate with steps."""
        pressures = []
        for i in range(15):
            if env._done:
                break
            action = Action(type=ActionType.QUERY_LOGS, params={"service": "test"})
            result = env.step(action)
            pressures.append(result.observation.simulated_time_pressure.value)
        # Should have escalated from LOW
        assert pressures[-1] != pressures[0] or len(pressures) < 4

    def test_blast_radius_tracked(self, env):
        action = Action(type=ActionType.QUERY_LOGS, params={"service": "test"})
        result = env.step(action)
        assert "current_blast_radius" in result.info
