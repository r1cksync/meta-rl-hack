"""Phase 7 — simulator tests.

Asserts:
    * catalog file integrity (counts + uniqueness).
    * dispatch correctness (sqs round trip, scheduled failures, unknown id).
    * scenario corpus coverage (>= 200 scenarios; every chain ends ok).
    * physics subsystems (topology cascade, telemetry determinism,
      runbook trap, trolley scoring, k8s controller).
    * pure-Python invariant: simulator package never imports boto3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]            # rl-agent/
sys.path.insert(0, str(ROOT))

from simulator import SimState, dispatch, load_catalogs, load_scenario     # noqa: E402
from simulator.runbooks  import RUNBOOKS, search as rb_search              # noqa: E402
from simulator.scoring   import BRUTE_FORCE_ACTIONS                        # noqa: E402
from simulator.topology  import (HEALTHY, CORRUPTED, MEMORY_LEAK, DEAD,
                                 default_ecommerce_topology)                # noqa: E402

CAT_DIR       = ROOT / "simulator" / "catalogs"
SCENARIO_GLOB = ROOT / "scenarios" / "sim"


# ---------------------------------------------------------------------------
# 1. Catalog integrity
# ---------------------------------------------------------------------------

def test_catalogs_files_present():
    assert (CAT_DIR / "services.json").exists()
    assert (CAT_DIR / "actions.json").exists()
    assert (CAT_DIR / "errors.json").exists()


def test_catalogs_meet_size_targets():
    cat = load_catalogs()
    assert len(cat["services"]) >= 170, f"services={len(cat['services'])}"
    assert len(cat["actions"])  >= 5000, f"actions={len(cat['actions'])}"
    assert len(cat["errors"])   >= 150,  f"errors={len(cat['errors'])}"


def test_catalogs_action_ids_unique():
    cat = load_catalogs()
    ids = [a["id"] for a in cat["actions"]]
    assert len(ids) == len(set(ids)), "duplicate action ids"


# ---------------------------------------------------------------------------
# 2. Dispatch correctness
# ---------------------------------------------------------------------------

def test_dispatch_unknown_action():
    s = SimState()
    r = dispatch({"id": "no_such.verb", "params": {}}, s)
    assert not r.ok and r.error == "InvalidAction"


def test_sqs_round_trip():
    s = SimState()
    s.sqs["q1"] = {"name": "q1", "depth": 0, "in_flight": 0,
                   "messages": [], "attrs": {}, "dlq": None}
    r1 = dispatch({"id": "sqs.send", "params": {"resource_id": "q1",
                                                 "payload": "hi"}}, s)
    assert r1.ok
    r2 = dispatch({"id": "sqs.receive", "params": {"resource_id": "q1"}}, s)
    assert r2.ok and "dlq_inspect" in r2.tags
    r3 = dispatch({"id": "sqs.purge", "params": {"resource_id": "q1"}}, s)
    assert r3.ok and "remediation" in r3.tags


def test_scheduled_failures_fire_once():
    s = SimState()
    s.lambda_["fn1"] = {"name": "fn1", "state": "Active",
                        "reserved_concurrency": 25, "invocations": 0,
                        "errors": 0, "throttles": 0}
    s.schedule_failure("lambda.invoke", "TooManyRequestsException",
                       "throttled", count=1)
    r1 = dispatch({"id": "lambda.invoke",
                   "params": {"resource_id": "fn1"}}, s)
    assert not r1.ok and r1.error == "TooManyRequestsException"
    r2 = dispatch({"id": "lambda.invoke",
                   "params": {"resource_id": "fn1"}}, s)
    assert r2.ok                     # second invoke succeeds


# ---------------------------------------------------------------------------
# 3. Scenario corpus coverage
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_scenarios():
    files = sorted(SCENARIO_GLOB.rglob("*.json"))
    assert len(files) >= 200, f"only {len(files)} scenarios on disk"
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


def test_at_least_200_scenarios(all_scenarios):
    assert len(all_scenarios) >= 200


def test_every_scenario_has_correct_chain_that_succeeds(all_scenarios):
    for scn in all_scenarios:
        s = SimState()
        load_scenario(scn, s)
        for step in scn["correct_action_chain"]:
            r = dispatch(step, s)
        assert r.ok, f"scenario {scn['id']} final action failed: {r.error}"


def test_difficulty_distribution(all_scenarios):
    by_diff = {}
    for scn in all_scenarios:
        by_diff[scn.get("difficulty", "?")] = by_diff.get(scn.get("difficulty", "?"), 0) + 1
    assert by_diff.get("easy",   0) >= 30
    assert by_diff.get("medium", 0) >= 20
    assert by_diff.get("hard",   0) >= 10


# ---------------------------------------------------------------------------
# 4. Topology cascade physics
# ---------------------------------------------------------------------------

def test_topology_cascade_propagates_upward():
    t = default_ecommerce_topology()
    t.set_status("users_db", DEAD)
    t.propagate()
    # auth depends on users_db -> auth visible error_rate must be lifted.
    assert t.nodes["auth"].error_rate >= 0.5
    # frontend transitively depends on auth via api_gateway.
    assert t.nodes["frontend"].error_rate >= 0.5


def test_memory_leak_kills_node_over_time():
    s = SimState()
    s.topology.nodes["users_db"].leak_rate_per_tick = 0.30
    for _ in range(5):
        s.tick()
    assert s.topology.nodes["users_db"].status in (DEAD, "rolling_back")


def test_blast_radius_recorded_for_brute_force():
    s = SimState()
    r = dispatch({"id": "platform.restart_cluster",
                  "params": {"target": "users_db"}}, s)
    assert r.error == "BlastRadiusWarning"
    assert s.blast_ledger.total_radius() > 0


# ---------------------------------------------------------------------------
# 5. Telemetry determinism
# ---------------------------------------------------------------------------

def test_telemetry_is_deterministic_under_same_seed():
    a = SimState(); a.telemetry.seed = 1234
    a.telemetry.__post_init__()
    a.topology.nodes["auth"].latency_p50 = 200
    pa = a.telemetry.generate_metrics(a.topology, "auth", tick=3,
                                      metric="latency_ms")
    b = SimState(); b.telemetry.seed = 1234
    b.telemetry.__post_init__()
    b.topology.nodes["auth"].latency_p50 = 200
    pb = b.telemetry.generate_metrics(b.topology, "auth", tick=3,
                                      metric="latency_ms")
    assert pa["value"] == pb["value"]


def test_telemetry_traffic_load_swings():
    s = SimState()
    loads = [s.telemetry.traffic_load(t) for t in range(0, 24, 4)]
    # Not all equal (sine wave should produce variation).
    assert max(loads) - min(loads) > 0.5


def test_log_generator_injects_error_when_node_unhealthy():
    s = SimState()
    s.topology.set_status("users_db", DEAD)
    s.topology.propagate()
    lines = s.telemetry.generate_logs(s.topology, "auth", tick=0,
                                      n_lines=50)
    # Should contain a cascade line referencing users_db.
    assert any("users_db" in l for l in lines)


# ---------------------------------------------------------------------------
# 6. Runbook traps + adversarial controller
# ---------------------------------------------------------------------------

def test_runbook_search_returns_relevant_hit():
    hits = rb_search("postgres transaction id wraparound")
    assert hits and hits[0]["id"] == "postgres_txid_wraparound"


def test_runbook_trap_corrupts_target_when_forbidden_action_fired():
    p = SCENARIO_GLOB / "hard" / "sim_advanced_runbook_trap_postgres_001.json"
    s = SimState()
    load_scenario(p, s)
    dispatch({"id": "platform.restart_cluster",
              "params": {"target": "users_db"}}, s)
    assert s.topology.nodes["users_db"].status == CORRUPTED
    assert s.runbook_traps[0].triggered


def test_runbook_trap_disarmed_after_read():
    p = SCENARIO_GLOB / "hard" / "sim_advanced_runbook_trap_postgres_001.json"
    s = SimState()
    load_scenario(p, s)
    dispatch({"id": "platform.read_runbook",
              "params": {"runbook_id": "postgres_txid_wraparound"}}, s)
    dispatch({"id": "platform.restart_cluster",
              "params": {"target": "users_db"}}, s)
    assert not s.runbook_traps[0].triggered


def test_k8s_controller_kicks_unhealthy_node_after_two_strikes():
    s = SimState()
    s.topology.set_status("inventory", "memory_leak")
    s.topology.nodes["inventory"].mem_pct = 0.97
    for _ in range(3):
        s.tick()
    # Either rolling_back (controller kicked) or dead (faded too far before kick).
    assert s.topology.nodes["inventory"].status in ("rolling_back", DEAD)


def test_pause_health_checks_protects_node_from_controller():
    s = SimState()
    s.topology.set_status("inventory", "memory_leak")
    s.topology.nodes["inventory"].mem_pct = 0.97
    dispatch({"id": "platform.pause_health_checks",
              "params": {"target": "inventory"}}, s)
    for _ in range(3):
        s.tick()
    assert s.topology.nodes["inventory"].status == "memory_leak"


# ---------------------------------------------------------------------------
# 7. Trolley scoring
# ---------------------------------------------------------------------------

def test_trolley_restore_path_records_data_loss_cost():
    p = SCENARIO_GLOB / "hard" / "sim_advanced_trolley_orders_db_001.json"
    s = SimState()
    load_scenario(p, s)
    dispatch({"id": "platform.restore_from_backup",
              "params": {"target": "orders_db", "backup_age_hours": 1.5}}, s)
    assert s.trolley.chosen_path == "restore"
    assert 0.0 < s.trolley.cost() <= 1.0


def test_trolley_rebuild_path_pending_for_n_ticks():
    p = SCENARIO_GLOB / "hard" / "sim_advanced_trolley_orders_db_001.json"
    s = SimState()
    load_scenario(p, s)
    dispatch({"id": "platform.rebuild_index",
              "params": {"target": "orders_db", "ticks": 4}}, s)
    assert s.trolley.chosen_path == "rebuild"
    # After 4 ticks the rebuild completes -> orders_db healthy.
    for _ in range(4):
        s.tick()
    assert s.topology.nodes["orders_db"].status == HEALTHY


# ---------------------------------------------------------------------------
# 8. Pure-Python invariant
# ---------------------------------------------------------------------------

def test_simulator_does_not_import_boto3():
    sim_dir = ROOT / "simulator"
    offenders: list[str] = []
    for py in sim_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "import boto3" in text or "from boto3" in text:
            offenders.append(str(py))
    assert not offenders, f"boto3 leaked into simulator: {offenders}"
