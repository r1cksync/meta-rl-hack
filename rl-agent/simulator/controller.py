"""Adversarial Kubernetes-style controller.

Every tick (after the agent's action) the controller scans the topology and
takes "well-meaning" automated remediations:

    * any node with mem_pct >= 0.95 gets restarted (status -> rolling_back
      for 2 ticks, then -> healthy). Restarting destroys whatever evidence
      the agent was capturing — this is the "K8s killed my heap dump" trap.
    * any node failing health checks (error_rate >= 0.5) for two consecutive
      ticks is restarted similarly.

Pause-health-checks counterplay: if `node.health_checks_paused` is True the
controller skips that node, letting the agent debug in peace.

The controller is intentionally aggressive: it can make incidents WORSE if
the agent doesn't pause checks first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .topology import (Topology, ServiceNode, HEALTHY, ROLLING_BACK,
                       MEMORY_LEAK, CPU_THROTTLED, DEAD)


@dataclass
class K8sController:
    enabled: bool = True
    # name -> consecutive ticks above the unhealthy threshold.
    _strikes: dict[str, int] = field(default_factory=dict)
    # restart_log records every controller-driven restart so the env can
    # detect when the agent's evidence got nuked.
    restart_log: list[dict] = field(default_factory=list)

    def step(self, topology: Topology, tick: int,
             pending_action_targets: set[str]) -> list[str]:
        """Run one controller tick. Returns names of nodes the controller
        kicked. `pending_action_targets` lets us avoid double-acting on a
        node the agent is already remediating."""
        if not self.enabled:
            return []
        kicked: list[str] = []
        for name, node in topology.nodes.items():
            if node.health_checks_paused:
                self._strikes[name] = 0
                continue
            if name in pending_action_targets:
                self._strikes[name] = 0
                continue
            unhealthy = (node.mem_pct >= 0.95
                         or (node.error_rate >= 0.5 and node.status != ROLLING_BACK)
                         or node.status == MEMORY_LEAK and node.mem_pct >= 0.90)
            if unhealthy:
                self._strikes[name] = self._strikes.get(name, 0) + 1
            else:
                self._strikes[name] = 0
            if self._strikes.get(name, 0) >= 2:
                # Kick the pod.
                node.status   = ROLLING_BACK
                node.mem_pct  = 0.30
                node.cpu_pct  = 0.20
                node.error_rate = 0.20
                node.leak_rate_per_tick = 0.0   # restart resets the leak
                self.restart_log.append({
                    "tick": tick, "node": name, "reason": "health_check_failure",
                })
                kicked.append(name)
                self._strikes[name] = 0
        return kicked
