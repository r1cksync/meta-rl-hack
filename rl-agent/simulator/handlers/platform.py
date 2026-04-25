"""Platform pseudo-service — exposes the simulator's "physics" subsystems
to the agent as ordinary AWS-like actions.

These action ids all live under the `platform.*` namespace and are routed
even though they don't exist in the catalog. They cover:

    * runbook search/fetch   — agent reads internal docs.
    * topology introspection — agent inspects DAG state.
    * telemetry              — high-fidelity logs / metrics / traces with
                               sine-wave traffic and seeded noise.
    * remediation primitives — pause_health_checks, failover_replica,
                               vacuum_freeze_db, restore_from_backup, …
    * trolley resolution     — choose rebuild vs restore for the data-loss
                               trade-off scoring.
"""

from __future__ import annotations

from ..runbooks import RUNBOOKS, search as rb_search, fetch as rb_fetch
from ..scoring  import BRUTE_FORCE_ACTIONS
from ..state    import ActionResult, SimState
from ..temporal import PendingAction
from ..topology import (HEALTHY, DEAD, MEMORY_LEAK, CPU_THROTTLED,
                         ROLLING_BACK, DEGRADED, REBUILDING, CORRUPTED)


# ---------------------------------------------------------------------------
# Runbook actions
# ---------------------------------------------------------------------------

def _verb_search_runbook(params: dict, state: SimState) -> ActionResult:
    query = params.get("query", "")
    hits  = rb_search(query, k=3)
    return ActionResult(ok=True, payload={"query": query, "hits": hits},
                        tags=["runbook_search"])


def _verb_read_runbook(params: dict, state: SimState) -> ActionResult:
    rid = params.get("runbook_id") or params.get("id", "")
    rb  = rb_fetch(rid)
    if rb is None:
        return ActionResult(ok=False, error="NoSuchRunbook",
                            error_message=f"runbook {rid} not found",
                            tags=["runbook_read"])
    state.runbooks_read.add(rid)
    # Disarm any trap matching this runbook.
    for trap in state.runbook_traps:
        if trap.runbook_id == rid:
            trap.runbook_read = True
    state.inspected.add("runbook")
    return ActionResult(ok=True,
                        payload={"id": rid, "title": rb["title"],
                                 "body": rb["body"]},
                        tags=["runbook_read", "investigation"])


# ---------------------------------------------------------------------------
# Topology / telemetry introspection
# ---------------------------------------------------------------------------

def _verb_describe_topology(params: dict, state: SimState) -> ActionResult:
    """Returns the DAG structure (edges only — node *status* is hidden)."""
    edges = []
    for name, deps in state.topology.deps.items():
        for d in deps:
            edges.append({"from": name, "to": d})
    return ActionResult(ok=True, payload={"edges": edges,
                                          "nodes": list(state.topology.nodes.keys())},
                        tags=["topology"])


def _verb_get_metrics(params: dict, state: SimState) -> ActionResult:
    svc    = params.get("service", "")
    metric = params.get("metric", "latency_ms")
    point  = state.telemetry.generate_metrics(state.topology, svc,
                                              state.tick_n, metric)
    return ActionResult(ok=True, payload=point, tags=["metrics"])


def _verb_get_logs(params: dict, state: SimState) -> ActionResult:
    svc      = params.get("service", "")
    n        = int(params.get("n_lines", 50))
    pattern  = params.get("pattern", "")
    lines    = state.telemetry.generate_logs(state.topology, svc,
                                              state.tick_n, n_lines=n,
                                              pattern=pattern)
    return ActionResult(ok=True,
                        payload={"service": svc, "lines": lines,
                                 "tick": state.tick_n,
                                 "traffic_load": round(
                                     state.telemetry.traffic_load(state.tick_n), 3)},
                        tags=["logs", "investigation"])


def _verb_get_trace(params: dict, state: SimState) -> ActionResult:
    svc   = params.get("service", "frontend")
    trace = state.telemetry.generate_trace(state.topology, svc, state.tick_n)
    return ActionResult(ok=True, payload=trace, tags=["trace", "investigation"])


def _verb_get_traffic(params: dict, state: SimState) -> ActionResult:
    """Surface the current sine-wave traffic load — lets the agent decide
    whether a "fix" survived a peak."""
    return ActionResult(ok=True,
                        payload={"tick": state.tick_n,
                                 "load": round(
                                     state.telemetry.traffic_load(state.tick_n), 3)},
                        tags=["traffic"])


def _verb_read_slack(params: dict, state: SimState) -> ActionResult:
    """Pull the latest N Slack messages — chaotic human chatter, including
    deliberate red herrings. Forces the LLM to triage unstructured text."""
    if state.slack is None:
        return ActionResult(ok=True, payload=[], tags=["slack"])
    n = int(params.get("last_n", 10))
    msgs = [m.to_dict() for m in state.slack.recent(n)]
    return ActionResult(ok=True, payload=msgs,
                        tags=["slack", "investigation"])


# ---------------------------------------------------------------------------
# Remediation primitives
# ---------------------------------------------------------------------------

def _verb_pause_health_checks(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node   = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["pause_hc"])
    node.health_checks_paused = True
    state.inspected.add("hc_paused")
    return ActionResult(ok=True, payload={"target": target, "paused": True},
                        tags=["pause_hc", "remediation_safe"])


def _verb_resume_health_checks(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node   = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["resume_hc"])
    node.health_checks_paused = False
    return ActionResult(ok=True, payload={"target": target, "paused": False},
                        tags=["resume_hc"])


def _verb_failover_replica(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None or node.failover_replica is None:
        return ActionResult(ok=False, error="NoFailoverReplica",
                            error_message=f"{target} has no replica",
                            tags=["failover"])
    replica = node.failover_replica
    state.topology.set_status(target,  HEALTHY)
    state.topology.set_status(replica, HEALTHY)
    state.mitigation_applied = True
    state.remediated.add("failover")
    return ActionResult(ok=True,
                        payload={"primary": target, "replica": replica,
                                 "mode": "warm-failover"},
                        tags=["failover", "remediation_safe"])


def _verb_vacuum_freeze_db(params: dict, state: SimState) -> ActionResult:
    """Used to satisfy the postgres TXID wraparound runbook."""
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["vacuum"])
    state.topology.set_status(target, HEALTHY)
    state.mitigation_applied = True
    state.remediated.add("vacuum_freeze")
    return ActionResult(ok=True, payload={"target": target,
                                          "xid_age": "ok"},
                        tags=["vacuum", "remediation_safe"])


def _verb_warm_cache(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["warm_cache"])
    state.topology.set_status(target, HEALTHY)
    state.remediated.add("warm_cache")
    return ActionResult(ok=True, payload={"target": target},
                        tags=["warm_cache", "remediation_safe"])


def _verb_enable_request_coalescing(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    state.remediated.add("coalescing")
    return ActionResult(ok=True, payload={"target": target,
                                          "coalescing": True},
                        tags=["coalescing", "remediation_safe"])


# Multi-tick action: rollback (3 ticks).
def _verb_rollback_deployment(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["rollback"])
    if state.temporal.is_in_flight(target):
        return ActionResult(ok=False, error="ConflictException",
                            error_message=f"rollback already in flight for {target}",
                            tags=["rollback"])
    state.topology.set_status(target, ROLLING_BACK)

    def _on_complete(node=node, state=state):
        state.topology.set_status(node.name, HEALTHY)
        node.leak_rate_per_tick = 0.0
        node.cpu_drift_per_tick = 0.0
        state.mitigation_applied = True
        state.remediated.add("rollback")

    state.temporal.enqueue(PendingAction(
        name=f"rollback:{target}", target=target, ticks_remaining=3,
        on_complete=_on_complete, in_flight_status=ROLLING_BACK,
    ))
    return ActionResult(ok=True,
                        payload={"target": target, "ticks_remaining": 3,
                                 "status": "rolling_back"},
                        tags=["rollback", "remediation_pending"])


# Multi-tick action: rebuild index (configurable, defaults to trolley TTR).
def _verb_rebuild_index(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["rebuild"])
    if state.temporal.is_in_flight(target):
        return ActionResult(ok=False, error="ConflictException",
                            error_message=f"rebuild already in flight for {target}",
                            tags=["rebuild"])
    ticks = int(params.get("ticks", state.trolley.ttr_rebuild_ticks))
    state.topology.set_status(target, REBUILDING)
    state.trolley.chosen_path = "rebuild"

    def _on_complete(node=node, state=state):
        state.topology.set_status(node.name, HEALTHY)
        state.mitigation_applied = True
        state.remediated.add("rebuild")

    state.temporal.enqueue(PendingAction(
        name=f"rebuild:{target}", target=target, ticks_remaining=ticks,
        on_complete=_on_complete, in_flight_status=REBUILDING,
    ))
    return ActionResult(ok=True,
                        payload={"target": target, "ticks_remaining": ticks,
                                 "status": "rebuilding",
                                 "trolley_path": "rebuild"},
                        tags=["rebuild", "remediation_pending", "trolley"])


def _verb_restore_from_backup(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    age_h  = float(params.get("backup_age_hours", state.trolley.backup_age_hours))
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["restore"])
    state.topology.set_status(target, HEALTHY)
    state.trolley.chosen_path  = "restore"
    state.trolley.restore_age_h = age_h
    state.mitigation_applied = True
    state.remediated.add("restore")
    return ActionResult(ok=True,
                        payload={"target": target, "backup_age_hours": age_h,
                                 "trolley_path": "restore",
                                 "data_loss_cost": min(1.0, 0.50 * age_h)},
                        tags=["restore", "remediation_safe", "trolley"])


# Brute-force actions (these incur blast-radius penalties).
def _verb_restart_cluster(params: dict, state: SimState) -> ActionResult:
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["restart_cluster"])
    radius = state.blast_ledger.record(state.topology, "restart_cluster",
                                       target, state.tick_n)
    # Knock every dependent node into degraded for 2 ticks (cache stampede).
    for up in state.topology.transitive_upstream(target):
        state.topology.set_status(up, DEGRADED)
    state.topology.set_status(target, ROLLING_BACK)

    def _on_complete(node=node, state=state, target=target):
        state.topology.set_status(target, HEALTHY)
        for up in state.topology.transitive_upstream(target):
            if state.topology.nodes[up].status == DEGRADED:
                state.topology.set_status(up, HEALTHY)
        state.remediated.add("restart_cluster")

    state.temporal.enqueue(PendingAction(
        name=f"restart_cluster:{target}", target=target, ticks_remaining=2,
        on_complete=_on_complete,
    ))
    return ActionResult(ok=False,    # success at the API level, but harmful
                        error="BlastRadiusWarning",
                        error_message=(f"restart_cluster on {target} affected "
                                       f"{radius} dependent services"),
                        payload={"target": target, "blast_radius": radius},
                        tags=["restart_cluster", "blast_radius"])


def _verb_capture_memory_dump(params: dict, state: SimState) -> ActionResult:
    """Diagnostic action — works only if health checks paused (otherwise
    the K8s controller will kick the pod mid-capture)."""
    target = params.get("target", "")
    node = state.topology.nodes.get(target)
    if node is None:
        return ActionResult(ok=False, error="UnknownNode",
                            error_message=f"node {target} not in topology",
                            tags=["heap_dump"])
    if not node.health_checks_paused:
        # 50% chance the controller has already kicked. We model it as: if
        # health_checks aren't paused, the dump is "destroyed" by the
        # controller restart.
        return ActionResult(ok=False, error="EvidenceLost",
                            error_message=("pod restarted by k8s controller "
                                           "before dump completed; pause health "
                                           "checks first"),
                            tags=["heap_dump"])
    state.inspected.add("heap_dump")
    return ActionResult(ok=True,
                        payload={"target": target, "size_mb": 412,
                                 "top_consumers": ["LeakyCache", "ImagePool"]},
                        tags=["heap_dump", "investigation"])


# ---------------------------------------------------------------------------
# Verb table — what `dispatch` consults.
# ---------------------------------------------------------------------------

_VERBS = {
    "search_runbook":          _verb_search_runbook,
    "read_runbook":            _verb_read_runbook,
    "describe_topology":       _verb_describe_topology,
    "get_metrics":             _verb_get_metrics,
    "get_logs":                _verb_get_logs,
    "get_trace":               _verb_get_trace,
    "get_traffic":             _verb_get_traffic,
    "read_slack":              _verb_read_slack,
    "pause_health_checks":     _verb_pause_health_checks,
    "resume_health_checks":    _verb_resume_health_checks,
    "failover_replica":        _verb_failover_replica,
    "vacuum_freeze_db":        _verb_vacuum_freeze_db,
    "warm_cache":              _verb_warm_cache,
    "enable_request_coalescing": _verb_enable_request_coalescing,
    "rollback_deployment":     _verb_rollback_deployment,
    "rebuild_index":           _verb_rebuild_index,
    "restore_from_backup":     _verb_restore_from_backup,
    "restart_cluster":         _verb_restart_cluster,
    "capture_memory_dump":     _verb_capture_memory_dump,
    "resume_writes":           _verb_vacuum_freeze_db,  # alias for runbook
    "fence_minority_partition": _verb_failover_replica,  # alias
    "force_controller_election": _verb_failover_replica,  # alias
    "enable_adaptive_capacity": _verb_warm_cache,         # alias
    "add_partition_suffix":    _verb_warm_cache,          # alias
    "describe_topics":         _verb_describe_topology,   # alias
}


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec.get("verb", "")
    fn = _VERBS.get(verb)
    if fn is None:
        return ActionResult(ok=False, error="UnknownPlatformVerb",
                            error_message=f"platform.{verb} not implemented",
                            tags=["platform"])
    return fn(params, state)
