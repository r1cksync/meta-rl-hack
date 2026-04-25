"""Probabilistic telemetry generator.

Converts the *hidden* topology + traffic state into the *visible* observations
the agent gets when it queries logs, metrics, or traces.

Key properties:
    * Fully deterministic given a seed (uses `random.Random(seed)`).
    * Traffic shaped by a sine wave + Gaussian jitter (the "2 AM vs Black
      Friday" effect from the spec).
    * Logs are 90% noise (deprecation warnings, OK lines) with the genuine
      error injected at a position that depends on the RNG.
    * Metrics scale with traffic_load — a service that LOOKS healthy at 3am
      can crash at 8am if the agent didn't fix the root cause.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .topology import Topology, ServiceNode


# ---------------------------------------------------------------------------
# Noise log lines — the 90% chaff.
# ---------------------------------------------------------------------------

_NOISE_INFO = [
    "[INFO]  health-check ok",
    "[INFO]  request id=%s ms=%d status=200",
    "[INFO]  cache hit ratio=0.%02d",
    "[INFO]  background gc completed in %dms",
    "[INFO]  metrics flushed to prom (n=%d)",
    "[INFO]  signal HUP -> reloading config",
    "[INFO]  user %s logged in",
    "[INFO]  shipped event to bus session.audit",
]
_NOISE_WARN = [
    "[WARN]  deprecated header X-Legacy-Trace seen from upstream",
    "[WARN]  TLS cert expires in 41d",
    "[WARN]  slow query 312ms on idx_users_email",
    "[WARN]  retry budget low (8/10)",
    "[WARN]  config drift: fluentbit.conf differs from baseline",
]

# Status-specific error templates. The agent has to find these among the noise.
_ERROR_FOR_STATUS = {
    "dead":          "[ERROR] {svc}: connection refused — peer down",
    "corrupted":     "[ERROR] {svc}: index corrupted, vacuum_freeze required",
    "memory_leak":   "[ERROR] {svc}: java.lang.OutOfMemoryError: heap",
    "cpu_throttled": "[ERROR] {svc}: TooManyRequestsException — concurrency cap hit",
    "degraded":      "[ERROR] {svc}: 5xx ratio over SLO (current=%.2f)",
    "rolling_back":  "[INFO]  {svc}: rollback in progress (rev N-1)",
    "rebuilding":    "[INFO]  {svc}: rebuilding from snapshot",
}

# When an UPSTREAM is failing, downstream nodes start emitting these.
_CASCADE_LINES = [
    "[ERROR] HTTP 504 Gateway Timeout calling {dep}",
    "[ERROR] circuit breaker OPEN for downstream={dep}",
    "[ERROR] tcp dial timeout {dep}:443 after 5s",
]


# ---------------------------------------------------------------------------
# Traffic profile.
# ---------------------------------------------------------------------------

@dataclass
class TrafficProfile:
    """Deterministic sine wave with Gaussian jitter modelling diurnal load.

    `value(tick)` returns a multiplier in roughly [0.5, 2.5]:
        - amplitude=1.0 means at the peak we get 2x baseline traffic.
        - period=24 means a full cycle spans 24 ticks (the simulator's day).
    """
    period:    int   = 24
    amplitude: float = 1.0
    jitter:    float = 0.10        # Gaussian sigma
    phase:     float = 0.0         # offset along the cycle (0..period)

    def at(self, tick: int, rng: random.Random) -> float:
        radians = (2 * math.pi) * ((tick + self.phase) / self.period)
        wave    = 1.0 + self.amplitude * math.sin(radians)
        # Gaussian noise. Seeded RNG → deterministic.
        wave   += rng.gauss(0.0, self.jitter)
        return max(0.05, wave)


# ---------------------------------------------------------------------------
# Telemetry engine — pure functions of (topology, traffic, tick, rng).
# ---------------------------------------------------------------------------

@dataclass
class TelemetryEngine:
    seed:    int            = 0
    traffic: TrafficProfile = field(default_factory=TrafficProfile)
    # NOTE: the engine owns its own RNG so each query is reproducible.
    _rng:    random.Random  = field(init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    # --- traffic --------------------------------------------------------
    def traffic_load(self, tick: int) -> float:
        # Use a sub-RNG so calling traffic_load doesn't perturb log/metric noise.
        sub = random.Random(("traffic", self.seed, tick).__hash__() & 0xFFFFFFFF)
        return self.traffic.at(tick, sub)

    # --- logs -----------------------------------------------------------
    def generate_logs(self, topology: "Topology", service: str, tick: int,
                      n_lines: int = 50, pattern: str = "") -> list[str]:
        """Emit `n_lines` log lines for `service` reflecting current state."""
        node = topology.nodes.get(service)
        if node is None:
            return [f"[WARN] log group for unknown service {service}"]

        rng = random.Random(("logs", self.seed, service, tick).__hash__() & 0xFFFFFFFF)
        out: list[str] = []
        # 1. Determine which downstream nodes are unhealthy → cascade lines.
        unhealthy_deps = [d for d in topology.downstream(service)
                          if topology.nodes[d].status != "healthy"]
        # 2. Inject 1 error line per status that is *not* healthy.
        target_errors: list[str] = []
        if node.status != "healthy" and node.status in _ERROR_FOR_STATUS:
            tmpl = _ERROR_FOR_STATUS[node.status]
            line = tmpl.format(svc=service)
            if "%.2f" in line:  line = line % (node.error_rate,)
            target_errors.append(line)
        for dep in unhealthy_deps:
            target_errors.append(rng.choice(_CASCADE_LINES).format(dep=dep))
        # 3. Fill the rest with noise.
        for _ in range(max(0, n_lines - len(target_errors))):
            if rng.random() < 0.85:
                tmpl = rng.choice(_NOISE_INFO)
                has_s = "%s" in tmpl
                n_d   = tmpl.count("%d")
                args: list = []
                if has_s:
                    args.append(rng.choice(["alice","bob","carol","dave"])
                                if "user" in tmpl
                                else f"{rng.randint(1,9999):04x}")
                args.extend(rng.randint(10, 999) for _ in range(n_d))
                line = tmpl % tuple(args) if args else tmpl
            else:
                line = rng.choice(_NOISE_WARN)
            out.append(line)
        # 4. Splice errors at random positions so the agent has to scan.
        for err in target_errors:
            pos = rng.randint(0, max(1, len(out) - 1))
            out.insert(pos, err)
        # 5. Optional caller-side filter (agent-supplied substring).
        if pattern:
            out = [l for l in out if pattern.lower() in l.lower()]
        return out

    # --- metrics --------------------------------------------------------
    def generate_metrics(self, topology: "Topology", service: str, tick: int,
                         metric: str = "latency_ms") -> dict:
        """Return a single (metric, value, tags) datapoint scaled by traffic."""
        node = topology.nodes.get(service)
        if node is None:
            return {"metric": metric, "value": 0, "tags": {"service": service,
                                                            "tick": tick}}
        load = self.traffic_load(tick)
        rng  = random.Random(("metric", self.seed, service, tick, metric)
                             .__hash__() & 0xFFFFFFFF)
        if metric == "latency_ms":
            v = node.latency_p50 * load * (1.0 + rng.gauss(0, 0.05))
        elif metric == "error_rate":
            v = min(1.0, node.error_rate * load * (1.0 + rng.gauss(0, 0.05)))
        elif metric == "cpu_pct":
            v = min(1.0, node.cpu_pct * load * (1.0 + rng.gauss(0, 0.03)))
        elif metric == "mem_pct":
            v = min(1.0, node.mem_pct + rng.gauss(0, 0.01))
        elif metric == "rps":
            v = 100.0 * load * (1.0 + rng.gauss(0, 0.05))
        else:
            v = rng.gauss(0.5, 0.1)
        return {
            "metric": metric,
            "value": round(float(v), 4),
            "tags": {"service": service, "tick": tick,
                     "traffic_load": round(load, 3)},
        }

    # --- traces ---------------------------------------------------------
    def generate_trace(self, topology: "Topology", entry_service: str,
                       tick: int) -> dict:
        """Synthesise a single Jaeger-style trace rooted at `entry_service`.

        Each downstream call inherits status from the topology so a trace
        through a sick database surfaces the failing span at the right depth.
        """
        rng = random.Random(("trace", self.seed, entry_service, tick)
                            .__hash__() & 0xFFFFFFFF)

        def _span(name: str, depth: int = 0) -> dict:
            node = topology.nodes.get(name)
            if node is None:
                return {"service": name, "ms": 0, "status": "unknown",
                        "children": []}
            ms = int(node.latency_p50 * (1.0 + rng.gauss(0, 0.05)))
            status_code = "ERROR" if node.status != "healthy" \
                                     and rng.random() < (node.error_rate + 0.05) \
                          else "OK"
            children = []
            if depth < 4:                     # bound recursion
                for d in topology.downstream(name):
                    children.append(_span(d, depth + 1))
            return {"service": name, "ms": ms, "status": status_code,
                    "children": children}

        return {
            "trace_id": f"{rng.randrange(1<<63):016x}",
            "tick": tick,
            "root": _span(entry_service),
        }
