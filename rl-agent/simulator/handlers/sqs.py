"""SQS handler — queues with depth, in-flight messages, DLQ wiring."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def _q(state: SimState, name: str | None) -> dict | None:
    if not name:
        return None
    return state.sqs.get(name)


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("queue_name")

    if verb == "create":
        nm = params.get("name") or name
        if not nm:
            return ActionResult(ok=False, error="InvalidParameterValueException",
                                error_message="missing queue name")
        state.sqs[nm] = {"name": nm, "depth": 0, "in_flight": 0,
                         "messages": [], "attrs": {"VisibilityTimeout": 30,
                                                   "DelaySeconds": 0},
                         "dlq": params.get("config", {}).get("dlq")}
        return ActionResult(ok=True, payload={"queue": nm},
                            tags=["sqs.create"])
    if verb in ("describe", "get", "head", "get_status"):
        q = _q(state, name)
        if q is None:
            return ActionResult(ok=False, error="AWS.SimpleQueueService.NonExistentQueue",
                                error_message=f"queue {name} not found",
                                tags=["sqs.describe"])
        return ActionResult(ok=True,
                            payload={"name": q["name"], "depth": q["depth"],
                                     "in_flight": q["in_flight"],
                                     "attrs": q["attrs"], "dlq": q.get("dlq")},
                            tags=["sqs.describe"])
    if verb == "list":
        return ActionResult(ok=True,
                            payload={"queues": list(state.sqs.keys())},
                            tags=["sqs.list"])
    if verb == "send" or verb == "publish":
        q = _q(state, name)
        if q is None:
            return ActionResult(ok=False, error="AWS.SimpleQueueService.NonExistentQueue",
                                error_message=f"queue {name} not found",
                                tags=["sqs.send"])
        msg = {"id": f"msg-{q['depth']}", "body": params.get("payload", "")}
        q["messages"].append(msg)
        q["depth"] += 1
        return ActionResult(ok=True, payload={"queue": name,
                                              "depth": q["depth"]},
                            tags=["sqs.send"])
    if verb == "receive":
        q = _q(state, name)
        if q is None:
            return ActionResult(ok=False, error="AWS.SimpleQueueService.NonExistentQueue",
                                error_message=f"queue {name} not found",
                                tags=["sqs.receive"])
        n = min(int(params.get("limit", 1) or 1), len(q["messages"]))
        peek = q["messages"][:n]
        q["in_flight"] += n
        return ActionResult(ok=True,
                            payload={"messages": peek, "depth": q["depth"],
                                     "in_flight": q["in_flight"]},
                            tags=["sqs.receive", "dlq_inspect"])
    if verb == "purge":
        q = _q(state, name)
        if q is None:
            return ActionResult(ok=False, error="AWS.SimpleQueueService.NonExistentQueue",
                                error_message=f"queue {name} not found",
                                tags=["sqs.purge"])
        q["messages"].clear()
        q["depth"] = 0
        q["in_flight"] = 0
        state.remediated.add("purge")
        state.emit_cloudtrail("PurgeQueue", resources=[name])
        return ActionResult(ok=True, payload={"queue": name, "depth": 0},
                            tags=["sqs.purge", "remediation"])
    if verb == "delete":
        if name in state.sqs:
            del state.sqs[name]
            return ActionResult(ok=True, payload={"deleted": name},
                                tags=["sqs.delete"])
        return ActionResult(ok=False, error="AWS.SimpleQueueService.NonExistentQueue",
                            error_message=f"queue {name} not found",
                            tags=["sqs.delete"])
    if verb in ("get_policy", "put_policy", "tag", "untag", "list_tags"):
        return generic.handle(spec, params, state)
    return generic.handle(spec, params, state)
