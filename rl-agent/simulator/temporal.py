"""Temporal event loop — action delays + scheduled state transitions.

A real SRE rollback doesn't complete in the same turn it's issued. We model
this with a `PendingActions` queue: when the agent issues a multi-tick action
(rollback, rebuild_index, restore_from_backup) we push an entry; each `tick`
counts down its `ticks_remaining`. When it hits zero, the queued completion
callback fires and the topology node settles into its post-action status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class PendingAction:
    name:           str           # human label, e.g. "rollback:auth"
    target:         str           # topology node it operates on
    ticks_remaining: int
    on_complete:    Callable[[], None]
    # Status the topology node sits in *while* this is in-flight.
    in_flight_status: str | None = None


@dataclass
class TemporalQueue:
    pending: list[PendingAction] = field(default_factory=list)

    def enqueue(self, action: PendingAction) -> None:
        self.pending.append(action)

    def cancel(self, name: str) -> None:
        self.pending = [p for p in self.pending if p.name != name]

    def tick(self) -> list[str]:
        """Decrement timers; fire completion callbacks. Returns labels of
        actions that completed this tick."""
        completed: list[str] = []
        still_pending: list[PendingAction] = []
        for p in self.pending:
            p.ticks_remaining -= 1
            if p.ticks_remaining <= 0:
                p.on_complete()
                completed.append(p.name)
            else:
                still_pending.append(p)
        self.pending = still_pending
        return completed

    def is_in_flight(self, target: str) -> bool:
        return any(p.target == target for p in self.pending)
