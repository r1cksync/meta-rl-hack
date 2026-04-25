"""Active Saboteur — an adversarial heuristic actor that runs every tick.

The saboteur is NOT random. It observes the agent's actions and the topology
state, then escalates the incident along a finite playbook:

    Phase 1 — `attack_primary`:  Take down the configured primary target.
    Phase 2 — `attack_failover`: Once the agent fails over to a replica, the
                                 saboteur attacks the replica too (CPU choke).
    Phase 3 — `attack_dependency`: If the agent stabilises the application
                                   tier, the saboteur escalates upstream
                                   (cache, gateway, auth) to keep pressure on.

All decisions are seeded by `SimState.seed` so episodes remain deterministic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .topology import Topology


@dataclass
class SaboteurEvent:
    """A single adversarial move recorded for the replay artifact."""
    tick:   int
    phase:  str
    target: str
    note:   str


@dataclass
class Saboteur:
    """Stateful 1v1 opponent."""
    primary_target:   str
    failover_target:  str | None = None
    dependency_chain: list[str] = field(default_factory=list)
    seed:             int = 0
    aggressiveness:   float = 0.6     # probability of acting on any given tick
    cooldown_ticks:   int = 2         # min ticks between moves
    enabled:          bool = True

    # mutable runtime
    _phase:           str = "idle"
    _last_move_tick:  int = -999
    _moves:           list[SaboteurEvent] = field(default_factory=list)
    _rng:             random.Random | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed ^ 0x5A_B0_7E_07)

    # ------------------------------------------------------------------
    def maybe_act(self, topology: "Topology", tick: int) -> SaboteurEvent | None:
        """Hook called from `SimState.tick` after the controller runs."""
        if not self.enabled:
            return None
        if tick - self._last_move_tick < self.cooldown_ticks:
            return None
        assert self._rng is not None
        if self._rng.random() > self.aggressiveness:
            return None

        from .topology import (CORRUPTED, CPU_THROTTLED, DEAD, DEGRADED,
                                HEALTHY, MEMORY_LEAK, ROLLING_BACK)

        # ── Phase 1: knock the primary down (idempotent — only first time). ──
        primary = topology.nodes.get(self.primary_target)
        if primary is not None and primary.status == HEALTHY:
            primary.status      = MEMORY_LEAK
            primary.mem_pct     = max(primary.mem_pct, 0.82)
            primary.leak_rate_per_tick = max(primary.leak_rate_per_tick, 0.05)
            ev = SaboteurEvent(tick, "attack_primary", primary.name,
                               f"Memory leak injected on {primary.name}")
            self._phase = "watching"
            return self._record(ev, tick)

        # ── Phase 2: the agent failed over → choke the replica's CPU. ──
        if self.failover_target is not None:
            replica = topology.nodes.get(self.failover_target)
            if replica is not None and replica.status == HEALTHY:
                # Only attack the replica if the primary is now bypassed
                # (i.e. agent already pulled the failover lever).
                primary_dead = (primary is not None
                                and primary.status in (DEAD, CORRUPTED,
                                                       ROLLING_BACK))
                if primary_dead:
                    replica.status = CPU_THROTTLED
                    replica.cpu_pct = max(replica.cpu_pct, 0.88)
                    replica.cpu_drift_per_tick = \
                        max(replica.cpu_drift_per_tick, 0.04)
                    ev = SaboteurEvent(
                        tick, "attack_failover", replica.name,
                        f"Heavy backup job pinned to {replica.name} — CPU choke")
                    self._phase = "escalating"
                    return self._record(ev, tick)

        # ── Phase 3: escalate upstream into the dependency chain. ──
        for dep in self.dependency_chain:
            n = topology.nodes.get(dep)
            if n is None or n.status != HEALTHY:
                continue
            n.status = DEGRADED
            n.error_rate = max(n.error_rate, 0.20)
            n.latency_p50 = max(n.latency_p50, 800)
            ev = SaboteurEvent(tick, "attack_dependency", n.name,
                               f"Lateral pivot — degrading {n.name}")
            self._phase = "lateral"
            return self._record(ev, tick)

        return None

    # ------------------------------------------------------------------
    def _record(self, ev: SaboteurEvent, tick: int) -> SaboteurEvent:
        self._moves.append(ev)
        self._last_move_tick = tick
        return ev

    @property
    def history(self) -> list[SaboteurEvent]:
        return list(self._moves)
