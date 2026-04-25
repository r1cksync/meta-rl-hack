"""DynamoDB handler — tables, items, throttling."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("table_name")

    if verb == "create":
        nm = params.get("name") or name
        state.dynamodb[nm] = {"name": nm, "items": {}, "throttled": False,
                              "capacity": 5}
        return ActionResult(ok=True, payload={"table": nm},
                            tags=["dynamodb.create"])
    if verb in ("describe", "get", "head", "get_status"):
        t = state.dynamodb.get(name) if name else None
        if t is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"table {name} not found",
                                tags=["dynamodb.describe"])
        return ActionResult(ok=True,
                            payload={"name": name, "items": len(t["items"]),
                                     "throttled": t["throttled"],
                                     "capacity": t["capacity"]},
                            tags=["dynamodb.describe"])
    if verb in ("send", "publish"):              # treat as PutItem
        t = state.dynamodb.get(name) if name else None
        if t is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"table {name} not found",
                                tags=["dynamodb.put_item"])
        if t["throttled"]:
            return ActionResult(ok=False,
                                error="ProvisionedThroughputExceededException",
                                error_message="capacity exceeded",
                                tags=["dynamodb.put_item"])
        pk = params.get("payload", {}).get("pk", f"item-{len(t['items'])}")
        t["items"][pk] = params.get("payload", {})
        return ActionResult(ok=True, payload={"table": name, "pk": pk},
                            tags=["dynamodb.put_item"])
    if verb == "scale":
        t = state.dynamodb.get(name) if name else None
        if t is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"table {name} not found",
                                tags=["dynamodb.scale"])
        t["capacity"] = int(params.get("capacity", 25))
        t["throttled"] = False
        state.mitigation_applied = True
        return ActionResult(ok=True, payload={"table": name,
                                              "capacity": t["capacity"]},
                            tags=["dynamodb.scale", "remediation"])
    return generic.handle(spec, params, state)
