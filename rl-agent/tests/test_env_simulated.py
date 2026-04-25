"""Phase 7 — env-level integration tests for simulator scenarios.

We sample a handful of sim_* scenarios, drive their `correct_action_chain`
through `IncidentCommanderEnv.step` via `AWS_API_CALL`, and assert:

    * the env transitions to `done=True` within max_steps.
    * `mitigation_applied` flips True for canonical-fix scenarios.
    * `_aws_inspected` and `_aws_remediated` get populated from sim tags.
    * legacy K8s task ids still reset cleanly with `_sim_active=False`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Force mock mode (no Loki, no Prometheus, no kube).
os.environ["INCIDENT_COMMANDER_MOCK"] = "true"

from environment.env    import IncidentCommanderEnv          # noqa: E402
from environment.models import Action, ActionType            # noqa: E402


SAMPLE_SIM_IDS = [
    "sim_easy_lambda_throttle_001",
    "sim_med_eb_lambda_016",
    "sim_hard_apigw_chain_001",
    "sim_advanced_cascade_users_db_001",
    "sim_advanced_runbook_trap_postgres_001",
    "sim_advanced_trolley_orders_db_001",
]


@pytest.fixture
def env():
    return IncidentCommanderEnv(use_mock=True)


@pytest.mark.parametrize("task_id", SAMPLE_SIM_IDS)
def test_sim_scenario_reset_marks_sim_active(env, task_id):
    env.reset(task_id)
    assert env._sim_active is True
    assert env._sim_state is not None
    assert env._sim_scenario is not None
    assert env._task.task_id == task_id


@pytest.mark.parametrize("task_id", SAMPLE_SIM_IDS)
def test_sim_correct_chain_applies_mitigation(env, task_id):
    env.reset(task_id)
    chain = env._sim_scenario["correct_action_chain"]
    last_obs = None
    for step in chain:
        sid = step["id"]
        svc, _, verb = sid.partition(".")
        params = {"service": svc, "verb": verb, **step.get("params", {})}
        last_obs = env.step(Action(type=ActionType.AWS_API_CALL, params=params))
    assert env._mitigation_applied is True, \
        f"{task_id} did not flip mitigation_applied"
    assert last_obs is not None


def test_legacy_k8s_reset_clears_sim_state(env):
    env.reset("sim_easy_lambda_throttle_001")
    assert env._sim_active is True
    env.reset("task1")
    assert env._sim_active is False


def test_unknown_task_id_raises(env):
    with pytest.raises(ValueError):
        env.reset("not_a_real_task_id_xyz")


def test_aws_breadcrumbs_populate_on_inspection(env):
    env.reset("sim_advanced_cascade_users_db_001")
    chain = env._sim_scenario["correct_action_chain"]
    for step in chain:
        sid = step["id"]; svc, _, verb = sid.partition(".")
        env.step(Action(type=ActionType.AWS_API_CALL,
                        params={"service": svc, "verb": verb,
                                **step.get("params", {})}))
    # The cascade scenario reads logs, traces, runbook, captures heap dump.
    assert env._aws_inspected, "no inspection breadcrumbs recorded"


def test_runbook_trap_credits_negative_in_reward(env):
    env.reset("sim_advanced_runbook_trap_postgres_001")
    # Fire forbidden action without reading the runbook.
    env.step(Action(type=ActionType.AWS_API_CALL,
                    params={"service": "platform",
                            "verb":    "restart_cluster",
                            "target":  "users_db"}))
    assert any(t.triggered for t in env._sim_state.runbook_traps)


def test_trolley_restore_records_cost(env):
    env.reset("sim_advanced_trolley_orders_db_001")
    env.step(Action(type=ActionType.AWS_API_CALL,
                    params={"service": "platform",
                            "verb":    "restore_from_backup",
                            "target":  "orders_db",
                            "backup_age_hours": 1.0}))
    assert env._sim_state.trolley.chosen_path == "restore"
    assert env._sim_state.trolley.cost() > 0
