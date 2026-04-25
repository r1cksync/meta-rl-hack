"""EC2 handler — instances minimal."""
from __future__ import annotations
from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    iid = params.get("resource_id") or params.get("instance_id") or params.get("name")
    if verb == "create":
        new_id = params.get("name") or f"i-{len(state.ec2):08x}"
        state.ec2[new_id] = {"id": new_id, "state": "running",
                             "type": params.get("config", {}).get("type", "t3.micro")}
        return ActionResult(ok=True, payload={"instance": new_id}, tags=["ec2.create"])
    if verb in ("describe", "get", "head", "get_status"):
        i = state.ec2.get(iid) if iid else None
        if i is None:
            return ActionResult(ok=False, error="InvalidInstanceID.NotFound",
                                error_message=f"{iid} not found", tags=["ec2.describe"])
        return ActionResult(ok=True, payload=dict(i), tags=["ec2.describe"])
    if verb == "list":
        return ActionResult(ok=True, payload={"instances": list(state.ec2.keys())},
                            tags=["ec2.list"])
    if verb in ("start", "stop", "restart"):
        i = state.ec2.get(iid) if iid else None
        if i is None:
            return ActionResult(ok=False, error="InvalidInstanceID.NotFound",
                                error_message=f"{iid} not found",
                                tags=[f"ec2.{verb}"])
        new_state = "running" if verb in ("start", "restart") else "stopped"
        i["state"] = new_state
        return ActionResult(ok=True, payload={"instance": iid, "state": new_state},
                            tags=[f"ec2.{verb}", "remediation"])
    return generic.handle(spec, params, state)
