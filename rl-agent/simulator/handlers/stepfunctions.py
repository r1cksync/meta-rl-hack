"""Step Functions handler — state machines + executions."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("state_machine_name")

    if verb == "create":
        nm = params.get("name") or name
        state.stepfunctions[nm] = {"name": nm, "executions": []}
        return ActionResult(ok=True, payload={"state_machine": nm},
                            tags=["sfn.create"])
    if verb in ("describe", "get"):
        sm = state.stepfunctions.get(name) if name else None
        if sm is None:
            return ActionResult(ok=False, error="StateMachineDoesNotExist",
                                error_message=f"sfn {name} not found",
                                tags=["sfn.describe"])
        recent = sm["executions"][-5:]
        return ActionResult(ok=True,
                            payload={"name": name,
                                     "execution_count": len(sm["executions"]),
                                     "recent": recent},
                            tags=["sfn.describe", "sfn_exec"])
    if verb == "list_events":
        sm = state.stepfunctions.get(name) if name else None
        if sm is None:
            return ActionResult(ok=False, error="StateMachineDoesNotExist",
                                error_message=f"sfn {name} not found",
                                tags=["sfn.list_events"])
        return ActionResult(ok=True,
                            payload={"executions": sm["executions"][-20:]},
                            tags=["sfn.list_events", "sfn_exec"])
    if verb == "start":
        sm = state.stepfunctions.get(name) if name else None
        if sm is None:
            return ActionResult(ok=False, error="StateMachineDoesNotExist",
                                error_message=f"sfn {name} not found",
                                tags=["sfn.start"])
        ex_id = f"sfn-exec-{len(sm['executions'])}"
        ex = {"id": ex_id, "status": "SUCCEEDED",
              "input": params.get("input", "{}")}
        # If scenario scheduled a failure, the engine layer would already have
        # short-circuited; here we honour the sm-level "force_fail" flag.
        if sm.get("force_fail"):
            ex["status"] = "FAILED"
            ex["error"] = "States.TaskFailed"
        sm["executions"].append(ex)
        return ActionResult(ok=True, payload=ex,
                            tags=["sfn.start"])
    if verb == "stop":
        sm = state.stepfunctions.get(name) if name else None
        if sm is None:
            return ActionResult(ok=False, error="StateMachineDoesNotExist",
                                error_message=f"sfn {name} not found",
                                tags=["sfn.stop"])
        if sm["executions"]:
            sm["executions"][-1]["status"] = "ABORTED"
        return ActionResult(ok=True, payload={"sfn": name},
                            tags=["sfn.stop"])
    return generic.handle(spec, params, state)
