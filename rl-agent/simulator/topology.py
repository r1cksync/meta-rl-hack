"""Service-dependency topology — a deterministic, pure-Python DAG.

We deliberately avoid `networkx` so the simulator stays dependency-free and
trivially serialisable. The graph drives:

    * cascading failure propagation (DB dies -> Auth 500s -> Frontend 504s)
    * blast-radius scoring (a "restart cluster" hits every dependent node)
    * telemetry generation (latency at the edge = sum of latencies of all
      downstream nodes weighted by traffic share)

Hidden state per node:
    - status:        "healthy" | "degraded" | "memory_leak" | "cpu_throttled"
                     | "rolling_back" | "dead" | "rebuilding"
    - error_rate:    float in [0.0, 1.0]   (visible only via telemetry)
    - latency_ms_p50: int                  (visible only via telemetry)
    - mem_pct:       float in [0.0, 1.0]   (visible only via telemetry)
    - cpu_pct:       float in [0.0, 1.0]   (visible only via telemetry)
    - health_checks_paused: bool           (controller hint)
    - failover_replica: str | None         (used by blast-radius logic)

The agent never gets `status` directly — it can only infer it from queries
to logs/metrics/traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


HEALTHY        = "healthy"
DEGRADED       = "degraded"
MEMORY_LEAK    = "memory_leak"
CPU_THROTTLED  = "cpu_throttled"
ROLLING_BACK   = "rolling_back"
DEAD           = "dead"
REBUILDING     = "rebuilding"
CORRUPTED      = "corrupted"

# --- Telemetry surface ranges per status (pre-noise, pre-traffic). ---------
_BASE = {
    HEALTHY:       {"error_rate": 0.001, "latency": 35,  "cpu": 0.18, "mem": 0.30},
    DEGRADED:      {"error_rate": 0.05,  "latency": 180, "cpu": 0.55, "mem": 0.45},
    MEMORY_LEAK:   {"error_rate": 0.02,  "latency": 90,  "cpu": 0.40, "mem": 0.70},
    CPU_THROTTLED: {"error_rate": 0.04,  "latency": 250, "cpu": 0.95, "mem": 0.40},
    ROLLING_BACK:  {"error_rate": 0.20,  "latency": 400, "cpu": 0.30, "mem": 0.30},
    DEAD:          {"error_rate": 1.00,  "latency": 9999,"cpu": 0.00, "mem": 0.00},
    REBUILDING:    {"error_rate": 0.30,  "latency": 800, "cpu": 0.35, "mem": 0.35},
    CORRUPTED:     {"error_rate": 0.80,  "latency": 600, "cpu": 0.20, "mem": 0.40},
}


@dataclass
class ServiceNode:
    name: str
    status: str = HEALTHY
    aws_resource: str | None = None      # e.g. "lambda:ic-checkout"
    failover_replica: str | None = None  # name of fallback node
    health_checks_paused: bool = False
    # Telemetry instantaneous (re-derived each tick from base + noise)
    error_rate:   float = 0.001
    latency_p50:  int   = 35
    cpu_pct:      float = 0.18
    mem_pct:      float = 0.30
    # Evolving-fault parameters (set when we inject a leak/spike)
    leak_rate_per_tick: float = 0.0     # mem_pct increment per tick
    cpu_drift_per_tick: float = 0.0
    # Tags consumed by the runbook trap mechanic.
    tags: list[str] = field(default_factory=list)


@dataclass
class Topology:
    """A directed dependency DAG: edge u -> v means u depends on v.
    Failures propagate UP the graph (against the edge direction): if v dies,
    every node u that depends on v starts seeing its tail latency spike."""

    nodes: dict[str, ServiceNode] = field(default_factory=dict)
    # adjacency: name -> list of names this node depends on (downstream).
    deps:  dict[str, list[str]]   = field(default_factory=dict)

    # ------------------------------------------------------------------
    def add(self, name: str, *, depends_on: Iterable[str] = (),
            aws_resource: str | None = None,
            failover_replica: str | None = None,
            tags: Iterable[str] = ()) -> ServiceNode:
        node = ServiceNode(name=name, aws_resource=aws_resource,
                           failover_replica=failover_replica,
                           tags=list(tags))
        self.nodes[name] = node
        self.deps[name]  = list(depends_on)
        # Make sure every dep also has an entry, even if no further deps.
        for d in depends_on:
            self.deps.setdefault(d, [])
            self.nodes.setdefault(d, ServiceNode(name=d))
        return node

    # ------------------------------------------------------------------
    def upstream(self, name: str) -> list[str]:
        """Nodes that DEPEND ON `name`. A failure in `name` propagates to these."""
        return [u for u, ds in self.deps.items() if name in ds]

    def downstream(self, name: str) -> list[str]:
        """Nodes `name` depends on (and a failure in any of these reaches `name`)."""
        return list(self.deps.get(name, ()))

    def transitive_upstream(self, name: str) -> set[str]:
        seen: set[str] = set()
        frontier = [name]
        while frontier:
            cur = frontier.pop()
            for u in self.upstream(cur):
                if u not in seen:
                    seen.add(u); frontier.append(u)
        return seen

    def transitive_downstream(self, name: str) -> set[str]:
        seen: set[str] = set()
        frontier = [name]
        while frontier:
            cur = frontier.pop()
            for d in self.downstream(cur):
                if d not in seen:
                    seen.add(d); frontier.append(d)
        return seen

    # ------------------------------------------------------------------
    def set_status(self, name: str, status: str) -> None:
        node = self.nodes.get(name)
        if node is None:
            return
        node.status = status
        base = _BASE[status]
        node.error_rate  = base["error_rate"]
        node.latency_p50 = base["latency"]
        node.cpu_pct     = base["cpu"]
        node.mem_pct     = base["mem"]

    # ------------------------------------------------------------------
    def propagate(self) -> None:
        """Propagate downstream failures up the graph.

        Algorithm: each upstream node's *visible* error_rate / latency is the
        max of its base (from its own status) and a degraded floor whenever a
        downstream node is unhealthy. We do NOT change `status` of upstream
        nodes — the truth stays at the root, the symptoms cascade up.
        """
        # Reset "visible" telemetry to base for every node.
        for node in self.nodes.values():
            base = _BASE[node.status]
            node.error_rate  = base["error_rate"]
            node.latency_p50 = base["latency"]
            # CPU/mem are local to a node and don't cascade.
        # For each unhealthy node, walk its transitive upstream and lift their
        # visible telemetry.
        for src_name, src in self.nodes.items():
            if src.status == HEALTHY:
                continue
            if src.status == DEAD:
                err_lift, lat_lift = 0.95, 5000
            elif src.status == CORRUPTED:
                err_lift, lat_lift = 0.50, 1200
            elif src.status in (DEGRADED, REBUILDING, ROLLING_BACK):
                err_lift, lat_lift = 0.15, 400
            else:                       # leak / throttle: subtle.
                err_lift, lat_lift = 0.08, 180
            for up_name in self.transitive_upstream(src_name):
                up = self.nodes[up_name]
                up.error_rate  = max(up.error_rate, err_lift)
                up.latency_p50 = max(up.latency_p50, lat_lift)

    # ------------------------------------------------------------------
    def evolve_faults(self, dt: float = 1.0) -> list[str]:
        """Advance memory leaks / cpu drifts. Returns names that died this tick."""
        died: list[str] = []
        for node in self.nodes.values():
            if node.leak_rate_per_tick > 0 and node.status not in (DEAD, REBUILDING):
                node.mem_pct = min(1.0, node.mem_pct + node.leak_rate_per_tick * dt)
                if node.mem_pct >= 0.99 and node.status != DEAD:
                    node.status = DEAD
                    died.append(node.name)
                elif node.mem_pct >= 0.80 and node.status == HEALTHY:
                    node.status = MEMORY_LEAK
            if node.cpu_drift_per_tick > 0 and node.status not in (DEAD, REBUILDING):
                node.cpu_pct = min(1.0, node.cpu_pct + node.cpu_drift_per_tick * dt)
                if node.cpu_pct >= 0.95 and node.status == HEALTHY:
                    node.status = CPU_THROTTLED
        return died

    # ------------------------------------------------------------------
    def blast_radius(self, name: str) -> int:
        """Count of downstream + upstream nodes that would see fallout from
        a brute-force operation on `name`."""
        return len(self.transitive_upstream(name) |
                   self.transitive_downstream(name))


# ---------------------------------------------------------------------------
# Default e-commerce topology used by 95% of scenarios.
# ---------------------------------------------------------------------------

def default_ecommerce_topology() -> Topology:
    """A 12-node DAG that mirrors a typical e-com microservice stack.

    Edges run agent-visible -> backend, so failures in a leaf (DB / cache)
    propagate up to user-facing services (Frontend, ApiGateway).
    """
    t = Topology()
    t.add("frontend",       depends_on=["api_gateway", "cdn"])
    t.add("cdn",            tags=["edge"])
    t.add("api_gateway",    depends_on=["auth", "checkout", "catalog"])
    t.add("auth",           depends_on=["users_db", "session_cache"],
          aws_resource="lambda:ic-auth")
    t.add("checkout",       depends_on=["payments", "inventory", "orders_db"],
          aws_resource="lambda:ic-checkout")
    t.add("catalog",        depends_on=["catalog_db", "search_index"],
          aws_resource="lambda:ic-catalog")
    t.add("payments",       depends_on=["payments_db", "stripe_proxy"],
          aws_resource="lambda:ic-payments")
    t.add("inventory",      depends_on=["inventory_db"],
          aws_resource="lambda:ic-inventory")
    t.add("users_db",       failover_replica="users_db_replica",
          aws_resource="rds:users-db", tags=["database", "stateful"])
    t.add("orders_db",      failover_replica="orders_db_replica",
          aws_resource="dynamodb:orders", tags=["database", "stateful"])
    t.add("payments_db",    aws_resource="dynamodb:payments",
          tags=["database", "stateful"])
    t.add("inventory_db",   aws_resource="dynamodb:inventory",
          tags=["database", "stateful"])
    t.add("catalog_db",     aws_resource="rds:catalog",
          tags=["database", "stateful"])
    t.add("session_cache",  aws_resource="elasticache:sessions",
          tags=["cache"])
    t.add("search_index",   aws_resource="opensearch:catalog",
          tags=["search"])
    t.add("stripe_proxy",   tags=["external"])
    t.add("users_db_replica", aws_resource="rds:users-db-replica",
          tags=["database", "replica"])
    t.add("orders_db_replica", aws_resource="dynamodb:orders-replica",
          tags=["database", "replica"])
    return t
