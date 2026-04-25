"""SimState — the in-memory AWS world the simulator operates on.

Each AWS service we care about gets its own dict of resources. Generic
services (the long tail covered by `handlers/generic.py`) just park their
state in `state.generic[service_slug]`. The state is fully serialisable
(pure-Python dicts/lists) so it can be diffed for tests and snapshot/restored
for episode resets.

The state also owns four "physics engine" subsystems (added in Phase 6c):

    * topology       — DAG of service nodes with cascading failures.
    * telemetry      — sine-wave traffic + Gaussian-noise log/metric generator.
    * temporal       — pending-action queue for delayed completions.
    * controller     — adversarial K8s-style auto-remediation.
    * trolley        — data-loss vs uptime trade-off ledger.
    * blast_ledger   — running tally of brute-force fallout.
    * runbook_traps  — per-scenario armed runbook traps.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .controller import K8sController
from .saboteur   import Saboteur, SaboteurEvent
from .scoring    import BlastRadiusLedger, IncidentTrolley
from .slack      import SlackStream
from .telemetry  import TelemetryEngine
from .temporal   import TemporalQueue
from .topology   import Topology, default_ecommerce_topology


# ---------------------------------------------------------------------------
# Result of one action dispatch.
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    ok: bool
    payload: Any = None             # service response dict / string
    error: str | None = None        # AWS-style error code (e.g. "ResourceNotFoundException")
    error_message: str = ""
    tags: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    latency_ms: int = 0

    def as_observation(self) -> str:
        """Compact one-line string for `last_action_result`."""
        if self.ok:
            tag = "/".join(self.tags) if self.tags else "ok"
            payload = self.payload
            if isinstance(payload, (list, dict)):
                payload = str(payload)[:240]
            return f"[sim:{tag}] {payload}"
        return f"[sim:error {self.error}] {self.error_message[:240]}"


# ---------------------------------------------------------------------------
# State containers, one per service that we model.
# ---------------------------------------------------------------------------

@dataclass
class SimState:
    """All AWS state lives here. Created fresh per episode."""

    # Episode bookkeeping
    clock_s:       float        = field(default_factory=time.time)
    rng_seed:      int          = 0
    action_log:    list[dict]   = field(default_factory=list)
    cloudtrail:    list[dict]   = field(default_factory=list)
    scheduled_failures: dict[str, list[dict]] = field(default_factory=dict)
    # ^ key = action.id ("lambda.invoke"); value = list of {error, message,
    # remaining_count} popped one-per-call.

    # ---- Per-service stores (only the ones with bespoke handlers) -----
    sqs:        dict[str, dict] = field(default_factory=dict)
    # name -> {url, depth, dlq, in_flight, attrs, messages: [{id,body,visible_at}]}
    sns:        dict[str, dict] = field(default_factory=dict)
    # arn -> {name, subscriptions: list, published: int}
    lambda_:    dict[str, dict] = field(default_factory=dict)
    # name -> {state, runtime, memory, env, last_invocation, invocations,
    #           reserved_concurrency, last_error, version}
    ec2:        dict[str, dict] = field(default_factory=dict)
    # iid -> {state, type, az, sg: list, tags}
    eks:        dict[str, dict] = field(default_factory=dict)
    # name -> {status, version, nodegroups: {ngname: {desired, status}}}
    ecs:        dict[str, dict] = field(default_factory=dict)
    s3:         dict[str, dict] = field(default_factory=dict)
    # bucket -> {objects: {key: bytes}, policy, versioning, encryption}
    dynamodb:   dict[str, dict] = field(default_factory=dict)
    # table -> {items: {pk: {attr...}}, throttled, capacity, gsi}
    rds:        dict[str, dict] = field(default_factory=dict)
    elasticache: dict[str, dict]= field(default_factory=dict)
    secrets:    dict[str, dict] = field(default_factory=dict)
    # name -> {value, version_ids, rotation_days, last_rotated_s, tags}
    kms:        dict[str, dict] = field(default_factory=dict)
    # alias -> {key_id, state, policy, scheduled_for_deletion}
    ssm:        dict[str, dict] = field(default_factory=dict)
    # param_name -> {value, version, history: [...]}
    iam:        dict[str, dict] = field(default_factory=dict)
    # role/user -> {policies: list, attached_policy_arns: list}
    events:     dict[str, dict] = field(default_factory=dict)
    # bus -> {rules: {name: {state, target_arn, schedule}}}
    stepfunctions: dict[str, dict] = field(default_factory=dict)
    # name -> {arn, executions: [{status, input, output, history}]}
    apigateway: dict[str, dict] = field(default_factory=dict)
    cloudfront: dict[str, dict] = field(default_factory=dict)
    cloudwatch: dict[str, dict] = field(default_factory=dict)
    # special: {alarms: {name: {state, threshold, namespace, metric}},
    #           log_groups: {name: {streams: {name: [events]}}},
    #           metrics: {namespace.metric: [{ts, value, dims}]} }
    cloudtrail_trails: dict[str, dict] = field(default_factory=dict)
    athena:     dict[str, dict] = field(default_factory=dict)
    glue:       dict[str, dict] = field(default_factory=dict)
    bedrock:    dict[str, dict] = field(default_factory=dict)
    sagemaker:  dict[str, dict] = field(default_factory=dict)
    route53:    dict[str, dict] = field(default_factory=dict)
    vpc:        dict[str, dict] = field(default_factory=dict)
    apprunner:  dict[str, dict] = field(default_factory=dict)
    cognito:    dict[str, dict] = field(default_factory=dict)
    quicksight: dict[str, dict] = field(default_factory=dict)
    cloudformation: dict[str, dict] = field(default_factory=dict)
    organizations: dict[str, dict] = field(default_factory=dict)
    redshift:   dict[str, dict] = field(default_factory=dict)
    msk:        dict[str, dict] = field(default_factory=dict)
    kinesis:    dict[str, dict] = field(default_factory=dict)
    firehose:   dict[str, dict] = field(default_factory=dict)
    ecr:        dict[str, dict] = field(default_factory=dict)
    elb:        dict[str, dict] = field(default_factory=dict)
    autoscaling: dict[str, dict] = field(default_factory=dict)
    backup:     dict[str, dict] = field(default_factory=dict)
    waf:        dict[str, dict] = field(default_factory=dict)
    guardduty:  dict[str, dict] = field(default_factory=dict)
    securityhub: dict[str, dict] = field(default_factory=dict)
    config:     dict[str, dict] = field(default_factory=dict)
    xray:       dict[str, dict] = field(default_factory=dict)
    transfer:   dict[str, dict] = field(default_factory=dict)
    appflow:    dict[str, dict] = field(default_factory=dict)
    appsync:    dict[str, dict] = field(default_factory=dict)
    appmesh:    dict[str, dict] = field(default_factory=dict)
    cloudfront: dict[str, dict] = field(default_factory=dict)

    # ---- Generic fallback for the long-tail services -----
    generic:    dict[str, dict] = field(default_factory=dict)

    # ---- Reward-shaping breadcrumbs (read by env._compute_reward) -----
    inspected:  set[str]        = field(default_factory=set)
    remediated: set[str]        = field(default_factory=set)
    mitigation_applied: bool    = False

    # ---- Phase 6c subsystems (cascading topology, telemetry, controller) -
    tick_n:           int                  = 0
    topology:         Topology             = field(default_factory=default_ecommerce_topology)
    telemetry:        TelemetryEngine      = field(default_factory=TelemetryEngine)
    temporal:         TemporalQueue        = field(default_factory=TemporalQueue)
    controller:       K8sController        = field(default_factory=K8sController)
    blast_ledger:     BlastRadiusLedger    = field(default_factory=BlastRadiusLedger)
    trolley:          IncidentTrolley      = field(default_factory=IncidentTrolley)
    runbook_traps:    list                 = field(default_factory=list)
    # Set of runbook ids the agent has fetched this episode. Reading a
    # runbook disarms its corresponding trap.
    runbooks_read:    set[str]             = field(default_factory=set)
    # Cumulative count of ticks any node was unhealthy (for trolley scoring).
    ticks_with_outage: int                 = 0

    # ---- Phase 8 — Active Saboteur + Slack channel + history -----------
    saboteur:        Saboteur | None       = None
    slack:           SlackStream | None    = None
    saboteur_events: list[SaboteurEvent]   = field(default_factory=list)
    history:         list[dict]            = field(default_factory=list)
    # ^ Per-step snapshots, populated by env.step for the replay artifact.

    # ---------------------------------------------------------------------
    def tick(self, dt_s: float = 1.0) -> None:
        """Advance the world by one step. This runs AFTER each agent action.

        Order matters:
            1. evolve_faults     - memory leaks creep, cpu drifts.
            2. temporal.tick     - delayed actions (rollback, restore) finish.
            3. controller.step   - K8s bot may kick unhealthy pods.
            4. propagate         - cascade failures up the dependency graph.
            5. accounting        - tick counters + trolley bookkeeping.
        """
        self.clock_s += dt_s
        self.tick_n  += 1

        died = self.topology.evolve_faults(dt_s)
        for name in died:
            self.action_log.append({
                "ts": self.clock_s, "action": "_topology.died",
                "params": {"node": name}, "ok": False, "error": "FaultEvolved",
            })

        completed = self.temporal.tick()
        for label in completed:
            self.action_log.append({
                "ts": self.clock_s, "action": "_temporal.completed",
                "params": {"label": label}, "ok": True, "error": None,
            })

        pending_targets = {p.target for p in self.temporal.pending}
        kicked = self.controller.step(self.topology, self.tick_n,
                                      pending_targets)
        for name in kicked:
            self.action_log.append({
                "ts": self.clock_s, "action": "_controller.restart",
                "params": {"node": name}, "ok": True, "error": None,
            })

        self.topology.propagate()

        # ── Saboteur runs after the controller and propagation so it sees
        # the same world the agent will see at the next observation. ──
        sab_phase: str | None = None
        if self.saboteur is not None:
            ev = self.saboteur.maybe_act(self.topology, self.tick_n)
            if ev is not None:
                self.saboteur_events.append(ev)
                sab_phase = ev.phase
                self.action_log.append({
                    "ts": self.clock_s, "action": "_saboteur.move",
                    "params": {"phase": ev.phase, "target": ev.target,
                               "note": ev.note},
                    "ok": True, "error": None,
                })
                # Re-propagate so the saboteur's hit cascades immediately.
                self.topology.propagate()

        # ── Slack chatter (emits even when no saboteur fired). ──
        if self.slack is not None:
            self.slack.emit_for_tick(self.tick_n, saboteur_phase=sab_phase)

        # Trolley accounting — count any tick with at least one unhealthy node.
        if any(n.status != "healthy" for n in self.topology.nodes.values()):
            self.ticks_with_outage += 1
            self.trolley.ticks_down += 1

    def log(self, action_id: str, params: dict, result: ActionResult) -> None:
        self.action_log.append({
            "ts":      self.clock_s,
            "action":  action_id,
            "params":  params,
            "ok":      result.ok,
            "error":   result.error,
        })

    def emit_cloudtrail(self, event_name: str, principal: str = "agent",
                        resources: list[str] | None = None) -> None:
        self.cloudtrail.append({
            "EventTime":     self.clock_s,
            "EventName":     event_name,
            "Username":      principal,
            "Resources":     resources or [],
            "EventSource":   "simulator.amazonaws.com",
            "EventId":       str(uuid.uuid4()),
        })

    def schedule_failure(self, action_id: str, error: str,
                         message: str = "", count: int = 1) -> None:
        bucket = self.scheduled_failures.setdefault(action_id, [])
        bucket.append({"error": error, "message": message,
                       "remaining": count})

    def consume_scheduled_failure(self, action_id: str) -> dict | None:
        bucket = self.scheduled_failures.get(action_id) or []
        for f in bucket:
            if f["remaining"] > 0:
                f["remaining"] -= 1
                return f
        return None
