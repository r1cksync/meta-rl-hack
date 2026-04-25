"""EKS minimal handler."""
from __future__ import annotations
from ..state import ActionResult, SimState
from . import generic


def handle(spec, params, state):
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name")
    if verb == "create":
        nm = params.get("name") or name
        state.eks[nm] = {"name": nm, "status": "ACTIVE", "version": "1.29",
                         "nodegroups": {}}
        return ActionResult(ok=True, payload={"cluster": nm}, tags=["eks.create"])
    if verb in ("describe", "get", "head", "get_status"):
        c = state.eks.get(name) if name else None
        if c is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"eks {name} not found",
                                tags=["eks.describe"])
        return ActionResult(ok=True, payload=dict(c), tags=["eks.describe"])
    if verb == "list":
        return ActionResult(ok=True, payload={"clusters": list(state.eks.keys())},
                            tags=["eks.list"])
    return generic.handle(spec, params, state)
