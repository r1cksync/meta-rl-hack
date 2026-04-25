"""IAM handler — minimal: simulate_principal_policy + role/policy CRUD."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name")

    if verb == "simulate_policy":
        principal = params.get("principal", "arn:aws:iam::000000000000:role/agent")
        action_name = params.get("action_name", "s3:GetObject")
        resource = params.get("resource", "*")
        # Lookup explicit denies in scenario state
        denies = state.iam.get(principal, {}).get("denies", [])
        if action_name in denies or "*" in denies:
            return ActionResult(ok=True,
                                payload={"principal": principal,
                                         "action": action_name,
                                         "resource": resource,
                                         "decision": "implicitDeny"},
                                tags=["iam.simulate_policy", "iam_sim"])
        return ActionResult(ok=True,
                            payload={"principal": principal,
                                     "action": action_name,
                                     "resource": resource,
                                     "decision": "allowed"},
                            tags=["iam.simulate_policy", "iam_sim"])
    if verb == "describe":
        r = state.iam.get(name) if name else None
        if r is None:
            return ActionResult(ok=False, error="NoSuchEntity",
                                error_message=f"iam role {name} not found",
                                tags=["iam.describe"])
        return ActionResult(ok=True, payload=dict(r),
                            tags=["iam.describe"])
    if verb == "list":
        return ActionResult(ok=True,
                            payload={"roles": list(state.iam.keys())},
                            tags=["iam.list"])
    return generic.handle(spec, params, state)
