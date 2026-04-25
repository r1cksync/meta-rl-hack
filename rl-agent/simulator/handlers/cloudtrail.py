"""CloudTrail handler — read agent + scenario-emitted events."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    if verb in ("list_events", "list", "describe", "get"):
        event_name = params.get("event_name") or params.get("filter")
        last = float(params.get("range_minutes", 60) or 60) * 60
        cutoff = state.clock_s - last
        evs = [e for e in state.cloudtrail
               if e["EventTime"] >= cutoff
               and (event_name is None or e["EventName"] == event_name)]
        evs = evs[-20:]
        return ActionResult(ok=True,
                            payload={"events": evs, "count": len(evs)},
                            tags=["cloudtrail.list_events", "cloudtrail"])
    return generic.handle(spec, params, state)
