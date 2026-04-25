"""Generate ~110 saboteur+slack scenarios across the topology.

Run from the repo root:

    python rl-agent/scripts/gen_saboteur_scenarios.py

Writes JSON files under `rl-agent/scenarios/sim/<difficulty>/`. Idempotent —
re-running overwrites existing generated files (template names start with
`sim_gen_*` so we never clobber the hand-authored advanced scenarios).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]            # rl-agent/
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "scenarios" / "sim"

# Service taxonomy from default_ecommerce_topology() ----------------------
APP_SERVICES   = ["auth", "checkout", "catalog", "payments", "inventory"]
EDGE_SERVICES  = ["frontend", "api_gateway", "cdn"]
DBS_FAILOVER   = [("users_db", "users_db_replica", "auth"),
                  ("orders_db", "orders_db_replica", "checkout")]
DBS_NO_FAILOVER= ["payments_db", "inventory_db", "catalog_db"]
CACHES         = ["session_cache", "search_index"]


def _scn(out: dict, difficulty: str, sid: str) -> Path:
    """Persist scenario JSON, return path."""
    p = OUT_DIR / difficulty / f"{sid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    return p


# ---------------------------------------------------------------------------
# Template 1: app-tier memory leak (saboteur attacks an app service).
# ---------------------------------------------------------------------------
def gen_app_leak() -> list[Path]:
    paths = []
    aggro_levels = [0.4, 0.6, 0.8, 0.95]
    leak_rates   = [0.01, 0.02, 0.03]
    seed_base    = 10_000
    i = 0
    for svc in APP_SERVICES + EDGE_SERVICES[:2]:                       # 7
        for aggr in aggro_levels[:3]:                                  # 3
            for leak in leak_rates[:2]:                                # 2
                i += 1
                sid = f"sim_gen_app_leak_{svc}_{i:03d}"
                difficulty = "easy" if leak <= 0.02 and aggr < 0.7 else "medium"
                out = {
                    "id":         sid,
                    "difficulty": difficulty,
                    "title":      f"Memory leak in {svc} (aggro={aggr})",
                    "description": (f"Saboteur targets {svc} with a slow memory "
                                    f"leak. Slack channel is noisy. Agent must "
                                    f"pause health checks before grabbing a heap "
                                    f"dump, then rollback."),
                    "preconditions": [],
                    "scheduled_failures": [],
                    "topology_overrides": [
                        {"kind": "set_status", "node": svc, "status": "memory_leak"},
                        {"kind": "set_leak",   "node": svc, "rate":  leak},
                    ],
                    "saboteur": {
                        "primary_target":  svc,
                        "failover_target": None,
                        "dependency_chain": ["api_gateway", "frontend"],
                        "aggressiveness":   aggr,
                        "cooldown_ticks":   2,
                    },
                    "slack": {"msgs_per_tick": 1.0 + aggr},
                    "traffic_profile": {"period": 14 + (i % 6), "amplitude": 0.6,
                                        "phase": float(i % 8), "jitter": 0.10},
                    "seed": seed_base + i,
                    "k8s_controller": True,
                    "correct_action_chain": [
                        {"id": "platform.read_slack",          "params": {"last_n": 5}},
                        {"id": "platform.get_logs",            "params": {"service": svc}},
                        {"id": "platform.get_metrics",         "params": {"service": svc, "metric": "mem_pct"}},
                        {"id": "platform.pause_health_checks", "params": {"target": svc}},
                        {"id": "platform.capture_memory_dump", "params": {"target": svc}},
                        {"id": "platform.rollback_deployment", "params": {"target": svc}},
                        {"id": "platform.resume_health_checks","params": {"target": svc}},
                    ],
                    "target_score": 0.55,
                    "max_steps": 16,
                }
                paths.append(_scn(out, difficulty, sid))
    return paths


# ---------------------------------------------------------------------------
# Template 2: DB failover duel (saboteur escalates to attack the replica).
# ---------------------------------------------------------------------------
def gen_db_duel() -> list[Path]:
    paths = []
    aggro_levels = [0.6, 0.8, 0.95]
    seeds        = [5151, 5252, 5353, 5454]
    i = 0
    for primary, replica, fronting in DBS_FAILOVER:                    # 2
        for aggr in aggro_levels:                                      # 3
            for seed in seeds:                                         # 4
                i += 1
                sid = f"sim_gen_db_duel_{primary}_{i:03d}"
                out = {
                    "id":         sid,
                    "difficulty": "hard",
                    "title":      f"Failover duel — saboteur attacks {primary}, "
                                  f"then chokes {replica}",
                    "description": (f"Saboteur takes down {primary}; once the "
                                    f"agent fails over, it pins a heavy backup "
                                    f"job on {replica}'s CPU. Agent must detect "
                                    f"both phases via slack + metrics."),
                    "preconditions":      [],
                    "scheduled_failures": [],
                    "topology_overrides": [],
                    "saboteur": {
                        "primary_target":   primary,
                        "failover_target":  replica,
                        "dependency_chain": [fronting, "api_gateway"],
                        "aggressiveness":   aggr,
                        "cooldown_ticks":   1,
                    },
                    "slack": {"msgs_per_tick": 1.5},
                    "traffic_profile": {"period": 16, "amplitude": 0.7,
                                        "phase": float(i % 12), "jitter": 0.12},
                    "seed": seed + i,
                    "k8s_controller": True,
                    "correct_action_chain": [
                        {"id": "platform.read_slack",         "params": {"last_n": 5}},
                        {"id": "platform.get_logs",           "params": {"service": fronting}},
                        {"id": "platform.get_trace",          "params": {"service": "frontend"}},
                        {"id": "platform.failover_replica",   "params": {"target": primary}},
                        {"id": "platform.read_slack",         "params": {"last_n": 5}},
                        {"id": "platform.get_metrics",        "params": {"service": replica, "metric": "cpu_pct"}},
                        {"id": "platform.rollback_deployment","params": {"target": replica}},
                    ],
                    "target_score": 0.65,
                    "max_steps": 20,
                }
                paths.append(_scn(out, "hard", sid))
    return paths


# ---------------------------------------------------------------------------
# Template 3: cache stampede / warmup. Saboteur knocks cache, slack erupts.
# ---------------------------------------------------------------------------
def gen_cache_warm() -> list[Path]:
    paths = []
    i = 0
    for cache in CACHES:                                                # 2
        for upstream_dep in ["api_gateway", "auth", "catalog", "checkout"]:   # 4
            for amplitude in [0.5, 1.0, 1.4]:                          # 3
                i += 1
                sid = f"sim_gen_cache_warm_{cache}_{i:03d}"
                difficulty = "easy" if amplitude < 1.0 else "medium"
                out = {
                    "id":         sid,
                    "difficulty": difficulty,
                    "title":      f"Cache outage on {cache} during {amplitude}x peak",
                    "description": (f"{cache} is degraded; sine-wave traffic peak "
                                    f"is amplifying the stampede. Agent must "
                                    f"enable request coalescing AND warm the "
                                    f"cache before the next peak."),
                    "preconditions":      [],
                    "scheduled_failures": [],
                    "topology_overrides": [
                        {"kind": "set_status", "node": cache, "status": "degraded"},
                    ],
                    "saboteur": {
                        "primary_target":   cache,
                        "failover_target":  None,
                        "dependency_chain": [upstream_dep, "api_gateway"],
                        "aggressiveness":   0.7,
                        "cooldown_ticks":   2,
                    },
                    "slack": {"msgs_per_tick": 1.2},
                    "traffic_profile": {"period": 10, "amplitude": amplitude,
                                        "phase": float(i % 5), "jitter": 0.15},
                    "seed": 20_000 + i,
                    "k8s_controller": True,
                    "correct_action_chain": [
                        {"id": "platform.read_slack",         "params": {"last_n": 6}},
                        {"id": "platform.get_traffic",        "params": {}},
                        {"id": "platform.get_logs",           "params": {"service": upstream_dep}},
                        {"id": "platform.search_runbook",     "params": {"query": "cache stampede"}},
                        {"id": "platform.enable_request_coalescing", "params": {"target": upstream_dep}},
                        {"id": "platform.warm_cache",         "params": {"target": cache}},
                    ],
                    "target_score": 0.6,
                    "max_steps": 14,
                }
                paths.append(_scn(out, difficulty, sid))
    return paths


# ---------------------------------------------------------------------------
# Template 4: slack red-herring. The chatter lies about root cause.
# ---------------------------------------------------------------------------
def gen_slack_redherring() -> list[Path]:
    paths = []
    seeds = [6262, 6363, 6464, 6565, 6666]
    i = 0
    for svc in APP_SERVICES:                                            # 5
        for seed in seeds[:4]:                                          # 4
            i += 1
            sid = f"sim_gen_redherring_{svc}_{i:03d}"
            out = {
                "id":         sid,
                "difficulty": "medium",
                "title":      f"Red-herring on Slack — true cause is leak in {svc}",
                "description": (f"Slack is loud with red herrings (a hotfix dev, "
                                f"an intern, a VP demanding ETA). Real cause is "
                                f"a memory leak in {svc}. Agent must triage."),
                "preconditions":      [],
                "scheduled_failures": [],
                "topology_overrides": [
                    {"kind": "set_status", "node": svc, "status": "memory_leak"},
                    {"kind": "set_leak",   "node": svc, "rate":  0.02},
                ],
                "saboteur": {
                    "primary_target":   svc,
                    "failover_target":  None,
                    "dependency_chain": ["api_gateway", "frontend"],
                    "aggressiveness":   0.4,
                    "cooldown_ticks":   3,
                },
                "slack": {"msgs_per_tick": 2.2},        # very chatty
                "traffic_profile": {"period": 12, "amplitude": 0.8,
                                    "phase": float(i % 6), "jitter": 0.15},
                "seed": seed + i,
                "k8s_controller": True,
                "correct_action_chain": [
                    {"id": "platform.read_slack",          "params": {"last_n": 10}},
                    {"id": "platform.get_logs",            "params": {"service": svc}},
                    {"id": "platform.get_metrics",         "params": {"service": svc, "metric": "mem_pct"}},
                    {"id": "platform.pause_health_checks", "params": {"target": svc}},
                    {"id": "platform.capture_memory_dump", "params": {"target": svc}},
                    {"id": "platform.rollback_deployment", "params": {"target": svc}},
                    {"id": "platform.resume_health_checks","params": {"target": svc}},
                ],
                "target_score": 0.6,
                "max_steps": 16,
            }
            paths.append(_scn(out, "medium", sid))
    return paths


# ---------------------------------------------------------------------------
# Template 5: dependency cascade. A deep DB issue surfaces as upstream alerts.
# ---------------------------------------------------------------------------
def gen_dependency_cascade() -> list[Path]:
    paths = []
    db_to_app = {
        "payments_db":  ("payments",  "checkout"),
        "inventory_db": ("inventory", "checkout"),
        "catalog_db":   ("catalog",   "api_gateway"),
        "users_db":     ("auth",      "api_gateway"),
        "orders_db":    ("checkout",  "api_gateway"),
    }
    statuses = ["degraded", "memory_leak", "cpu_throttled"]
    seeds    = [7171, 7272, 7373, 7474]
    i = 0
    for db, (mid, upstream) in db_to_app.items():                       # 5
        for status in statuses:                                         # 3
            for seed in seeds[:2]:                                      # 2
                i += 1
                sid = f"sim_gen_cascade_{db}_{i:03d}"
                out = {
                    "id":         sid,
                    "difficulty": "hard",
                    "title":      f"Dependency cascade — {db} is {status}, "
                                  f"surfacing as alerts on {upstream}",
                    "description": (f"Alerts hit {upstream}, but the truth lives "
                                    f"in {db} ({status}). Agent must walk the "
                                    f"trace + describe_topology to find the "
                                    f"real root, then vacuum/rollback."),
                    "preconditions":      [],
                    "scheduled_failures": [],
                    "topology_overrides": [
                        {"kind": "set_status", "node": db, "status": status},
                    ],
                    "saboteur": {
                        "primary_target":   mid,
                        "failover_target":  None,
                        "dependency_chain": [upstream, "frontend"],
                        "aggressiveness":   0.5,
                        "cooldown_ticks":   2,
                    },
                    "slack": {"msgs_per_tick": 1.4},
                    "traffic_profile": {"period": 18, "amplitude": 0.9,
                                        "phase": float(i % 9), "jitter": 0.13},
                    "seed": seed + i,
                    "k8s_controller": True,
                    "correct_action_chain": [
                        {"id": "platform.read_slack",       "params": {"last_n": 5}},
                        {"id": "platform.describe_topology","params": {}},
                        {"id": "platform.get_logs",         "params": {"service": upstream}},
                        {"id": "platform.get_logs",         "params": {"service": db}},
                        {"id": "platform.get_trace",        "params": {"service": "frontend"}},
                        {"id": "platform.vacuum_freeze_db", "params": {"target": db}},
                    ],
                    "target_score": 0.65,
                    "max_steps": 18,
                }
                paths.append(_scn(out, "hard", sid))
    return paths


# ---------------------------------------------------------------------------
# Template 6: peak traffic + service degradation (sine-wave amplification).
# ---------------------------------------------------------------------------
def gen_peak_traffic() -> list[Path]:
    paths = []
    i = 0
    for svc in EDGE_SERVICES + APP_SERVICES[:3]:                        # 6
        for amplitude in [1.2, 1.5, 1.8]:                              # 3
            i += 1
            sid = f"sim_gen_peak_{svc}_{i:03d}"
            out = {
                "id":         sid,
                "difficulty": "medium",
                "title":      f"Sine-wave peak hammers {svc} (x{amplitude})",
                "description": (f"Sine-wave traffic at {amplitude}x amplitude is "
                                f"saturating {svc}. Agent must read traffic, "
                                f"enable coalescing, and warm caches BEFORE "
                                f"the next peak."),
                "preconditions":      [],
                "scheduled_failures": [],
                "topology_overrides": [
                    {"kind": "set_status",     "node": svc, "status": "degraded"},
                    {"kind": "set_cpu_drift",  "node": svc, "rate":   0.02},
                ],
                "saboteur": {
                    "primary_target":   svc,
                    "failover_target":  None,
                    "dependency_chain": ["api_gateway", "frontend"],
                    "aggressiveness":   0.5,
                    "cooldown_ticks":   2,
                },
                "slack": {"msgs_per_tick": 1.6},
                "traffic_profile": {"period": 8, "amplitude": amplitude,
                                    "phase": float(i % 4), "jitter": 0.18},
                "seed": 30_000 + i,
                "k8s_controller": True,
                "correct_action_chain": [
                    {"id": "platform.read_slack",         "params": {"last_n": 5}},
                    {"id": "platform.get_traffic",        "params": {}},
                    {"id": "platform.get_metrics",        "params": {"service": svc, "metric": "cpu_pct"}},
                    {"id": "platform.enable_request_coalescing", "params": {"target": svc}},
                    {"id": "platform.warm_cache",         "params": {"target": "session_cache"}},
                ],
                "target_score": 0.55,
                "max_steps": 14,
            }
            paths.append(_scn(out, "medium", sid))
    return paths


# ---------------------------------------------------------------------------
# Template 7: data corruption — restore from backup (trolley).
# ---------------------------------------------------------------------------
def gen_corruption_restore() -> list[Path]:
    paths = []
    i = 0
    for db in ["payments_db", "inventory_db", "catalog_db", "orders_db"]:  # 4
        for age in [0.5, 1.5]:                                           # 2
            i += 1
            sid = f"sim_gen_restore_{db}_{i:03d}"
            out = {
                "id":         sid,
                "difficulty": "hard",
                "title":      f"Corruption in {db} — restore vs rebuild trolley",
                "description": (f"{db} is corrupted. Agent must read the runbook "
                                f"and pick: restore from a {age}h-old backup "
                                f"(data loss) or rebuild (long downtime)."),
                "preconditions":      [],
                "scheduled_failures": [],
                "topology_overrides": [
                    {"kind": "set_status", "node": db, "status": "corrupted"},
                ],
                "trolley": {"ttr_rebuild_ticks": 12, "backup_age_hours": age},
                "saboteur": {
                    "primary_target":   db,
                    "failover_target":  None,
                    "dependency_chain": ["api_gateway"],
                    "aggressiveness":   0.3,                             # quiet, focus on trolley
                    "cooldown_ticks":   3,
                },
                "slack": {"msgs_per_tick": 1.0},
                "traffic_profile": {"period": 12, "amplitude": 0.6,
                                    "phase": float(i % 6), "jitter": 0.10},
                "seed": 40_000 + i,
                "k8s_controller": True,
                "correct_action_chain": [
                    {"id": "platform.read_slack",          "params": {"last_n": 5}},
                    {"id": "platform.get_logs",            "params": {"service": db}},
                    {"id": "platform.get_trace",           "params": {"service": "frontend"}},
                    {"id": "platform.search_runbook",      "params": {"query": "corruption restore"}},
                    {"id": "platform.restore_from_backup", "params": {"target": db, "backup_age_hours": age}},
                ],
                "target_score": 0.6,
                "max_steps": 14,
            }
            paths.append(_scn(out, "hard", sid))
    return paths


# ---------------------------------------------------------------------------
def main() -> None:
    all_paths: list[Path] = []
    all_paths += gen_app_leak()
    all_paths += gen_db_duel()
    all_paths += gen_cache_warm()
    all_paths += gen_slack_redherring()
    all_paths += gen_dependency_cascade()
    all_paths += gen_peak_traffic()
    all_paths += gen_corruption_restore()

    # Verify every chain runs end-to-end without errors.
    from simulator import SimState, dispatch, load_scenario
    failures: list[tuple[str, str]] = []
    for p in all_paths:
        s = SimState()
        scn = load_scenario(p, s)
        last = None
        for step in scn["correct_action_chain"]:
            last = dispatch(step, s)
        if not last.ok:
            failures.append((p.name, last.error or "unknown"))

    print(f"Generated {len(all_paths)} scenarios.")
    print(f"  passing chains: {len(all_paths) - len(failures)}")
    if failures:
        print(f"  FAILING ({len(failures)}):")
        for name, err in failures[:10]:
            print(f"    - {name}: {err}")


if __name__ == "__main__":
    main()
