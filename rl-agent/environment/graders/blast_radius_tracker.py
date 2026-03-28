"""Blast radius tracker — tracks error impact over time."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BlastRadiusRecord:
    step: int
    blast_radius_pct: float
    action_type: str  # "" for observation-only steps


class BlastRadiusTracker:
    """Tracks blast radius history across steps in an episode."""

    history: list[BlastRadiusRecord] = field(default_factory=list)

    def __init__(self) -> None:
        self.history: list[BlastRadiusRecord] = []

    def reset(self) -> None:
        self.history.clear()

    def record(self, step: int, blast_radius_pct: float, action_type: str) -> None:
        self.history.append(BlastRadiusRecord(
            step=step,
            blast_radius_pct=blast_radius_pct,
            action_type=action_type,
        ))

    def compute_area_under_curve(self) -> float:
        """Trapezoidal integral of blast_radius over steps."""
        if len(self.history) < 2:
            return 0.0
        area = 0.0
        for i in range(1, len(self.history)):
            prev = self.history[i - 1]
            curr = self.history[i]
            dt = curr.step - prev.step
            area += 0.5 * (prev.blast_radius_pct + curr.blast_radius_pct) * dt
        return area

    def check_action_caused_increase(self, step: int) -> bool:
        """True if blast_radius at step N > blast_radius at N-1 AND previous action was write."""
        if step < 1 or len(self.history) < 2:
            return False
        curr = next((r for r in self.history if r.step == step), None)
        prev = next((r for r in self.history if r.step == step - 1), None)
        if curr is None or prev is None:
            return False
        write_actions = {
            "rollback_deployment", "restart_pods", "scale_deployment",
            "apply_config_patch", "delete_chaos_experiment",
        }
        return (
            curr.blast_radius_pct > prev.blast_radius_pct
            and prev.action_type in write_actions
        )

    @property
    def latest(self) -> float:
        if not self.history:
            return 0.0
        return self.history[-1].blast_radius_pct
