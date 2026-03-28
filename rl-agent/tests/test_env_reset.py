"""Tests for environment reset and state management."""

import pytest

from environment.models import Action, ActionType, Observation
from environment.env import IncidentCommanderEnv


@pytest.fixture
def env():
    return IncidentCommanderEnv(use_mock=True)


class TestReset:
    def test_reset_returns_observation(self, env):
        obs = env.reset("task1")
        assert isinstance(obs, Observation)

    def test_reset_sets_step_count_zero(self, env):
        env.reset("task1")
        state = env.state()
        assert state["step_count"] == 0

    def test_reset_sets_done_false(self, env):
        env.reset("task1")
        state = env.state()
        assert state["done"] is False

    def test_reset_clears_action_history(self, env):
        env.reset("task1")
        env.step(Action(type=ActionType.QUERY_LOGS, params={"service": "test"}))
        env.reset("task1")
        state = env.state()
        assert len(state["action_history"]) == 0

    def test_reset_all_tasks(self, env):
        """All three tasks should reset successfully."""
        for task_id in ["task1", "task2", "task3"]:
            obs = env.reset(task_id)
            assert isinstance(obs, Observation)
            assert obs.step_count == 0

    def test_reset_invalid_task(self, env):
        with pytest.raises(ValueError, match="Unknown task_id"):
            env.reset("task99")

    def test_reset_loads_alerts(self, env):
        """Task1 mock should produce alerts."""
        obs = env.reset("task1")
        assert len(obs.active_alerts) > 0

    def test_reset_loads_service_health(self, env):
        obs = env.reset("task1")
        assert len(obs.service_health) > 0

    def test_reset_available_actions(self, env):
        obs = env.reset("task1")
        assert len(obs.available_actions) == 10


class TestState:
    def test_state_before_reset(self, env):
        state = env.state()
        assert state["task_id"] is None
        assert state["done"] is False

    def test_state_reflects_task(self, env):
        env.reset("task2")
        state = env.state()
        assert state["task_id"] == "task2"

    def test_state_tracks_cumulative_reward(self, env):
        env.reset("task1")
        env.step(Action(type=ActionType.QUERY_LOGS, params={"service": "inventory-service"}))
        state = env.state()
        assert "cumulative_reward" in state

    def test_step_increments_count(self, env):
        env.reset("task1")
        env.step(Action(type=ActionType.QUERY_LOGS, params={"service": "test"}))
        state = env.state()
        assert state["step_count"] == 1

    def test_done_after_20_steps(self, env):
        """Episode should terminate after 20 steps."""
        env.reset("task1")
        for i in range(20):
            if env._done:
                break
            env.step(Action(type=ActionType.QUERY_LOGS, params={"service": "test"}))
        assert env._done is True


class TestDoneGuard:
    def test_step_after_done_raises(self, env):
        env.reset("task1")
        # Submit postmortem to end episode
        env.step(Action(
            type=ActionType.SUBMIT_POSTMORTEM,
            params={"root_cause": "test", "timeline": "test", "mitigations": "test"},
        ))
        with pytest.raises(RuntimeError, match="Episode is done"):
            env.step(Action(type=ActionType.QUERY_LOGS, params={"service": "test"}))

    def test_step_before_reset_raises(self, env):
        with pytest.raises(RuntimeError, match="No task loaded"):
            env.step(Action(type=ActionType.QUERY_LOGS, params={"service": "test"}))
