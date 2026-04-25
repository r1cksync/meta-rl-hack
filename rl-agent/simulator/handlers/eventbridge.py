"""EventBridge handler — buses + rules with state."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def _bus(state: SimState, name: str) -> dict | None:
    return state.events.get(name)


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name")
    rule_name = params.get("rule_name")
    bus_name  = params.get("bus_name") or name

    if verb == "create":
        nm = params.get("name") or name
        # Treat as rule create if bus_name provided.
        if bus_name and bus_name != nm and bus_name in state.events:
            state.events[bus_name].setdefault("rules", {})[nm] = {
                "name": nm, "state": "ENABLED",
                "schedule": params.get("config", {}).get("schedule")}
            return ActionResult(ok=True, payload={"rule": nm, "bus": bus_name},
                                tags=["events.create_rule"])
        state.events[nm] = {"name": nm, "rules": {}}
        return ActionResult(ok=True, payload={"bus": nm},
                            tags=["events.create_bus"])
    if verb == "describe":
        if rule_name and bus_name in state.events:
            r = state.events[bus_name]["rules"].get(rule_name)
            if r is None:
                return ActionResult(ok=False, error="ResourceNotFoundException",
                                    error_message=f"rule {rule_name} not found",
                                    tags=["events.describe"])
            return ActionResult(ok=True, payload=dict(r),
                                tags=["events.describe"])
        b = _bus(state, name)
        if b is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"bus {name} not found",
                                tags=["events.describe"])
        return ActionResult(ok=True, payload={"name": name,
                                              "rules": list(b["rules"].keys())},
                            tags=["events.describe"])
    if verb == "list":
        return ActionResult(ok=True,
                            payload={"buses": list(state.events.keys())},
                            tags=["events.list"])
    if verb == "enable":
        b = state.events.get(bus_name) if bus_name else None
        rn = rule_name or name
        if b and rn in b.get("rules", {}):
            b["rules"][rn]["state"] = "ENABLED"
            state.remediated.add("enable_rule")
            state.mitigation_applied = True
            state.emit_cloudtrail("EnableRule", resources=[rn])
            return ActionResult(ok=True, payload={"rule": rn, "state": "ENABLED"},
                                tags=["events.enable", "remediation"])
        return ActionResult(ok=False, error="ResourceNotFoundException",
                            error_message=f"rule {rn} not found",
                            tags=["events.enable"])
    if verb == "disable":
        b = state.events.get(bus_name) if bus_name else None
        rn = rule_name or name
        if b and rn in b.get("rules", {}):
            b["rules"][rn]["state"] = "DISABLED"
            return ActionResult(ok=True, payload={"rule": rn, "state": "DISABLED"},
                                tags=["events.disable"])
        return ActionResult(ok=False, error="ResourceNotFoundException",
                            error_message=f"rule {rn} not found",
                            tags=["events.disable"])
    if verb == "publish":
        b = state.events.get(bus_name) if bus_name else None
        if b is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"bus {bus_name} not found",
                                tags=["events.publish"])
        b.setdefault("published", 0)
        b["published"] += 1
        return ActionResult(ok=True, payload={"bus": bus_name,
                                              "published": b["published"]},
                            tags=["events.publish"])
    return generic.handle(spec, params, state)
