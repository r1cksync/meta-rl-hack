"""Scenario loader.

A simulator scenario JSON looks like::

    {
        "id": "sim_lambda_throttle_easy_001",
        "difficulty": "easy",
        "title": "Checkout Lambda throttled",
        "description": "...",
        "preconditions": [
            {"path": "lambda_/ic-checkout", "op": "set",
             "value": {"name": "ic-checkout", "state": "Active",
                       "reserved_concurrency": 0, "invocations": 0,
                       "errors": 0, "throttles": 0}}
        ],
        "scheduled_failures": [
            {"action_id": "lambda.invoke", "error": "TooManyRequestsException",
             "message": "throttled", "count": 1}
        ],
        "correct_action_chain": [
            {"id": "lambda.describe", "params": {"resource_id": "ic-checkout"}},
            {"id": "lambda.scale",    "params": {"resource_id": "ic-checkout", "capacity": 25}},
            {"id": "lambda.invoke",   "params": {"resource_id": "ic-checkout"}}
        ],
        "target_score": 0.6,
        "max_steps": 12
    }

`load_scenario(path, state)` mutates `state` in place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runbooks import RunbookTrap
from .state    import SimState
from .telemetry import TelemetryEngine, TrafficProfile


def _apply_op(state: SimState, path: str, op: str, value: Any) -> None:
    """Mutate state.<path>. Path uses dots and indexes via /, e.g.
    `lambda_/ic-checkout` => state.lambda_["ic-checkout"]."""
    head, _, rest = path.partition("/")
    container = getattr(state, head, None)
    if container is None:
        # Allow generic.<service>
        container = state.generic.setdefault(head, {})
    if op == "set":
        if rest:
            container[rest] = value
        else:
            # Replace the whole container if it's a dict.
            if isinstance(container, dict):
                container.clear()
                container.update(value)
    elif op == "merge":
        if rest:
            target = container.setdefault(rest, {})
            target.update(value)
        elif isinstance(container, dict):
            container.update(value)
    elif op == "delete":
        if rest and rest in container:
            del container[rest]


def load_scenario(scenario: dict | str | Path, state: SimState) -> dict:
    if isinstance(scenario, (str, Path)):
        scenario = json.loads(Path(scenario).read_text(encoding="utf-8"))

    for pre in scenario.get("preconditions", []):
        _apply_op(state, pre["path"], pre.get("op", "set"), pre.get("value"))

    for sf in scenario.get("scheduled_failures", []):
        state.schedule_failure(sf["action_id"], sf["error"],
                               sf.get("message", ""),
                               sf.get("count", 1))

    # ---------- Phase 6c additions ----------------------------------
    # Topology overrides: scenarios can flip a node's status, plant a
    # memory leak, or wire in a new edge.
    for ov in scenario.get("topology_overrides", []):
        kind = ov.get("kind", "set_status")
        if kind == "set_status":
            state.topology.set_status(ov["node"], ov["status"])
        elif kind == "set_leak":
            node = state.topology.nodes.get(ov["node"])
            if node:
                node.leak_rate_per_tick = float(ov.get("rate", 0.05))
        elif kind == "set_cpu_drift":
            node = state.topology.nodes.get(ov["node"])
            if node:
                node.cpu_drift_per_tick = float(ov.get("rate", 0.03))
        elif kind == "add_edge":
            state.topology.deps.setdefault(ov["from"], []).append(ov["to"])

    # Runbook traps: each entry like {"runbook_id":"...", "target":"users_db"}.
    for trap in scenario.get("runbook_traps", []):
        state.runbook_traps.append(RunbookTrap(
            runbook_id=trap["runbook_id"], target=trap["target"]))

    # Trolley problem (only on hardest scenarios).
    troll = scenario.get("trolley")
    if troll:
        state.trolley.ttr_rebuild_ticks = int(troll.get("ttr_rebuild_ticks", 15))
        state.trolley.backup_age_hours  = float(troll.get("backup_age_hours", 2.0))

    # Telemetry / traffic profile (deterministic per-seed).
    seed = int(scenario.get("seed", abs(hash(scenario["id"])) & 0xFFFFFFFF))
    state.rng_seed = seed
    tp = scenario.get("traffic_profile") or {}
    state.telemetry = TelemetryEngine(
        seed=seed,
        traffic=TrafficProfile(
            period=int(tp.get("period", 24)),
            amplitude=float(tp.get("amplitude", 1.0)),
            jitter=float(tp.get("jitter", 0.10)),
            phase=float(tp.get("phase", 0.0)),
        ),
    )

    # K8s controller toggle (on by default; advanced scenarios may disable).
    state.controller.enabled = bool(scenario.get("k8s_controller", True))

    # ── Phase 8: Active Saboteur (1v1 duel) ─────────────────────────
    sab = scenario.get("saboteur")
    if sab:
        from .saboteur import Saboteur
        state.saboteur = Saboteur(
            primary_target  = sab["primary_target"],
            failover_target = sab.get("failover_target"),
            dependency_chain= list(sab.get("dependency_chain", [])),
            seed            = seed,
            aggressiveness  = float(sab.get("aggressiveness", 0.6)),
            cooldown_ticks  = int(sab.get("cooldown_ticks", 2)),
            enabled         = bool(sab.get("enabled", True)),
        )

    # ── Phase 8: Slack channel ──────────────────────────────────────
    slack_cfg = scenario.get("slack")
    if slack_cfg or sab:                # always emit chatter if saboteur exists
        from .slack import SlackStream
        primary = (sab or {}).get("primary_target") or scenario.get("id")
        state.slack = SlackStream(
            seed          = seed,
            primary       = primary,
            msgs_per_tick = float((slack_cfg or {}).get("msgs_per_tick", 1.2)),
        )

    # Recompute cascading visibility once preconditions are applied.
    state.topology.propagate()

    return scenario
