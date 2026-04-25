"""Curriculum controller with per-fault-type mastery tracking.

Tracks the agent's success rate on each fault type and escalates the
difficulty tier automatically as mastery increases. Inspired by kube-sre-gym's
curriculum controller but adapted to our 7 static scenarios plus a dynamic
multi-fault tier.

Tiers:
    warmup       → task1, task4               (easy, single fault)
    beginner     → task1, task2, task4, task5 (easy+medium, single fault)
    intermediate → all 7 tasks                (adds hard single-fault)
    advanced     → multi-fault pairs          (2 concurrent faults, no red herrings)
    expert       → adversarial multi-fault    (2-3 faults + red herrings + LLM-designed)

State is purely in-memory and serializable. Call `record_episode()` after every
episode completion; the controller will auto-promote when mastery thresholds
are hit. Call `sample_task()` before `env.reset()` to get the next task id.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


TIERS: list[str] = [
    "warmup",
    "beginner",
    "intermediate",
    "advanced",
    "expert",
]

TIER_TASKS: dict[str, list[str]] = {
    "warmup":       ["task1", "task4", "task9", "task16", "task19"],
    "beginner":     ["task1", "task2", "task4", "task5", "task9", "task16", "task19", "task22"],
    "intermediate": ["task1", "task2", "task3", "task4", "task5", "task6", "task7", "task8",
                     "task9", "task10", "task12", "task14", "task17", "task22"],
    "advanced":     ["task2", "task3", "task5", "task6", "task7", "task8", "task10", "task11",
                     "task12", "task13", "task14", "task15", "task17", "task18", "task20", "task21", "task23"],
    "expert":       ["task3", "task6", "task7", "task8", "task10", "task11",
                     "task13", "task15", "task18", "task20", "task21", "task23"],
}

# Minimum rolling success rate (score >= target) to promote to the next tier.
PROMOTION_THRESHOLD = 0.65
# Number of recent episodes considered for the rolling mastery computation.
MASTERY_WINDOW = 8
# Min episodes in current tier before promotion is considered.
MIN_EPISODES_PER_TIER = 6


@dataclass
class EpisodeOutcome:
    task_id: str
    score: float
    target_score: float
    steps: int
    mitigation_applied: bool
    root_cause_correct: bool
    tier: str


@dataclass
class CurriculumState:
    """Serializable curriculum state."""

    tier: str = "warmup"
    episodes_in_tier: int = 0
    total_episodes: int = 0
    history: list[EpisodeOutcome] = field(default_factory=list)
    per_task_mastery: dict[str, float] = field(default_factory=dict)
    per_task_attempts: dict[str, int] = field(default_factory=dict)


class CurriculumController:
    """Manages task difficulty progression across episodes."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self.state = CurriculumState()

    # ------------------------------------------------------------------ API

    def sample_task(self, force_task_id: str | None = None) -> dict[str, Any]:
        """Pick the next task based on current tier and weakness tracking.

        If `force_task_id` is given, returns it directly (still recorded).
        The sampling is weakness-biased: tasks with lower mastery in the
        current tier's task pool are more likely to be chosen.
        """
        tier = self.state.tier
        pool = TIER_TASKS[tier]

        if force_task_id:
            task_id = force_task_id
        else:
            task_id = self._weighted_sample(pool)

        multi_fault = tier in ("advanced", "expert")
        adversarial = tier == "expert"

        return {
            "task_id": task_id,
            "tier": tier,
            "multi_fault": multi_fault,
            "adversarial": adversarial,
            "companion_task_ids": self._pick_companions(task_id, pool) if multi_fault else [],
        }

    def record_episode(self, outcome: EpisodeOutcome) -> dict[str, Any]:
        """Record an episode outcome and maybe promote the tier.

        Returns a dict describing the promotion (or lack thereof).
        """
        self.state.history.append(outcome)
        self.state.episodes_in_tier += 1
        self.state.total_episodes += 1
        self.state.per_task_attempts[outcome.task_id] = (
            self.state.per_task_attempts.get(outcome.task_id, 0) + 1
        )

        # Exponential moving average per task (alpha=0.3)
        prev = self.state.per_task_mastery.get(outcome.task_id, 0.0)
        target = outcome.target_score if outcome.target_score > 0 else 0.5
        success = 1.0 if outcome.score >= target else 0.0
        self.state.per_task_mastery[outcome.task_id] = 0.7 * prev + 0.3 * success

        promoted = self._maybe_promote()
        return {
            "tier": self.state.tier,
            "promoted": promoted,
            "episodes_in_tier": self.state.episodes_in_tier,
            "total_episodes": self.state.total_episodes,
            "mastery": dict(self.state.per_task_mastery),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of curriculum state (for API / dashboard)."""
        return {
            "tier": self.state.tier,
            "tier_index": TIERS.index(self.state.tier),
            "tier_total": len(TIERS),
            "episodes_in_tier": self.state.episodes_in_tier,
            "total_episodes": self.state.total_episodes,
            "current_pool": TIER_TASKS[self.state.tier],
            "per_task_mastery": dict(self.state.per_task_mastery),
            "per_task_attempts": dict(self.state.per_task_attempts),
            "rolling_success_rate": self._rolling_success_rate(),
            "multi_fault": self.state.tier in ("advanced", "expert"),
            "adversarial": self.state.tier == "expert",
            "next_promotion_at": PROMOTION_THRESHOLD,
        }

    def reset(self) -> None:
        """Reset curriculum back to warmup."""
        self.state = CurriculumState()

    def force_tier(self, tier: str) -> None:
        """Jump to an explicit tier (useful for eval)."""
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier}; expected one of {TIERS}")
        self.state.tier = tier
        self.state.episodes_in_tier = 0

    # -------------------------------------------------------------- helpers

    def _weighted_sample(self, pool: list[str]) -> str:
        """Sample from `pool` inversely weighted by per-task mastery."""
        weights = []
        for t in pool:
            mastery = self.state.per_task_mastery.get(t, 0.0)
            # Lower mastery => higher weight. Add a floor so all tasks stay sampled.
            weights.append(max(0.1, 1.0 - mastery))
        total = sum(weights)
        r = self._rng.uniform(0, total)
        acc = 0.0
        for t, w in zip(pool, weights):
            acc += w
            if r <= acc:
                return t
        return pool[-1]

    def _pick_companions(self, primary: str, pool: list[str]) -> list[str]:
        """For multi-fault tiers, pick 1-2 companion tasks distinct from `primary`."""
        others = [t for t in pool if t != primary]
        if not others:
            return []
        k = 2 if self.state.tier == "expert" and len(others) >= 2 else 1
        return self._rng.sample(others, k=min(k, len(others)))

    def _maybe_promote(self) -> bool:
        if self.state.tier == TIERS[-1]:
            return False
        if self.state.episodes_in_tier < MIN_EPISODES_PER_TIER:
            return False
        if self._rolling_success_rate() >= PROMOTION_THRESHOLD:
            idx = TIERS.index(self.state.tier)
            self.state.tier = TIERS[idx + 1]
            self.state.episodes_in_tier = 0
            return True
        return False

    def _rolling_success_rate(self) -> float:
        window = self.state.history[-MASTERY_WINDOW:]
        if not window:
            return 0.0
        succs = sum(
            1 for ep in window
            if ep.score >= (ep.target_score if ep.target_score > 0 else 0.5)
        )
        return succs / len(window)
