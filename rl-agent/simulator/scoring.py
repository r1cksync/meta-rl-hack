"""Scoring helpers — blast radius and data-loss vs uptime trade-offs.

These are computed by the simulator and surfaced via SimState breadcrumbs.
The env reward shaper consults them; the simulator never tries to compute
the agent's reward itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .topology import Topology


# Actions that, if executed without first failing-over to a replica, count as
# brute-force and incur a blast-radius penalty proportional to the count of
# downstream/upstream nodes they took out.
BRUTE_FORCE_ACTIONS = {
    "restart_cluster",
    "rds.reboot",
    "elasticache.reboot",
    "msk.reboot_broker",
    "ec2.terminate",
    "eks.delete_nodegroup",
}


@dataclass
class IncidentTrolley:
    """The 'data-loss vs uptime' problem.

    Configured by the scenario:
        ttr_rebuild_ticks: ticks needed to rebuild the corrupted index.
        backup_age_hours:  how stale the available backup is.

    The agent's choice exposes a measurable score:
        rebuild path:  -0.10 * ticks_down
        restore path:  -0.50 * backup_age_hours_chosen   (one-shot)
    The env caps both at -1.0 so the trolley contributes the full ±0.10
    bound the user mandated.
    """
    ttr_rebuild_ticks: int   = 15
    backup_age_hours:  float = 2.0
    chosen_path:      str | None = None     # "rebuild" | "restore"
    ticks_down:       int = 0
    restore_age_h:    float = 0.0

    def cost(self) -> float:
        if self.chosen_path == "rebuild":
            return min(1.0, 0.10 * self.ticks_down)
        if self.chosen_path == "restore":
            return min(1.0, 0.50 * self.restore_age_h)
        return 0.0

    def as_dict(self) -> dict:
        return {
            "chosen_path":  self.chosen_path,
            "ticks_down":   self.ticks_down,
            "restore_age_h": self.restore_age_h,
            "cost":         self.cost(),
        }


@dataclass
class BlastRadiusLedger:
    """Tracks every brute-force action and the resulting fallout."""
    incidents: list[dict] = field(default_factory=list)

    def record(self, topology: Topology, action_id: str,
               target: str, tick: int) -> int:
        if action_id not in BRUTE_FORCE_ACTIONS:
            return 0
        radius = topology.blast_radius(target) if target else 0
        self.incidents.append({
            "tick":   tick,
            "action": action_id,
            "target": target,
            "radius": radius,
        })
        return radius

    def total_radius(self) -> int:
        return sum(i["radius"] for i in self.incidents)
