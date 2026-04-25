"""IncidentCommander AWS simulator package.

Replaces live boto3 calls with an in-memory, deterministic AWS environment.
The agent dispatches actions through `engine.dispatch(action_dict, state)`
which routes to a per-service handler. Scenarios populate `SimState` with
deformities; correct action chains drive the state back to healthy.

Public surface:
    from environment.simulator import (
        SimState, ActionResult, dispatch, load_scenario, load_catalogs,
    )
"""

from __future__ import annotations

from .state import SimState, ActionResult
from .engine import dispatch, load_catalogs
from .scenarios import load_scenario

__all__ = [
    "SimState",
    "ActionResult",
    "dispatch",
    "load_catalogs",
    "load_scenario",
]
