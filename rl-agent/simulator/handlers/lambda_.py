"""Lambda handler — functions, invocations, concurrency, errors."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def _fn(state: SimState, name: str | None) -> dict | None:
    if not name:
        return None
    return state.lambda_.get(name)


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("function_name")

    if verb == "create":
        nm = params.get("name") or name
        state.lambda_[nm] = {
            "name": nm, "state": "Active",
            "runtime": params.get("config", {}).get("runtime", "python3.11"),
            "memory": 256, "version": "$LATEST",
            "invocations": 0, "errors": 0, "throttles": 0,
            "reserved_concurrency": None, "last_error": None,
        }
        state.emit_cloudtrail("CreateFunction", resources=[nm])
        return ActionResult(ok=True, payload={"function": nm},
                            tags=["lambda.create"])
    if verb in ("describe", "get", "head", "get_status"):
        fn = _fn(state, name)
        if fn is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"lambda {name} not found",
                                tags=["lambda.describe"])
        return ActionResult(ok=True, payload=dict(fn),
                            tags=["lambda.describe"])
    if verb == "list":
        return ActionResult(ok=True,
                            payload={"functions": list(state.lambda_.keys())},
                            tags=["lambda.list"])
    if verb == "invoke":
        fn = _fn(state, name)
        if fn is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"lambda {name} not found",
                                tags=["lambda.invoke"])
        # Throttle if reserved_concurrency=0
        if fn.get("reserved_concurrency") == 0:
            fn["throttles"] += 1
            return ActionResult(ok=False, error="TooManyRequestsException",
                                error_message="reserved concurrency = 0",
                                tags=["lambda.invoke"])
        fn["invocations"] += 1
        state.remediated.add("lambda")
        state.emit_cloudtrail("Invoke", resources=[name])
        return ActionResult(ok=True,
                            payload={"function": name, "status": 200,
                                     "invocations": fn["invocations"]},
                            tags=["lambda.invoke", "remediation"])
    if verb == "update":
        fn = _fn(state, name)
        if fn is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"lambda {name} not found",
                                tags=["lambda.update"])
        fn.update(params.get("config", {}))
        return ActionResult(ok=True, payload={"updated": name},
                            tags=["lambda.update"])
    if verb == "scale":
        fn = _fn(state, name)
        if fn is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"lambda {name} not found",
                                tags=["lambda.scale"])
        fn["reserved_concurrency"] = int(params.get("capacity", 10))
        state.mitigation_applied = True
        state.remediated.add("lambda.scale")
        return ActionResult(ok=True, payload={"function": name,
                                              "reserved": fn["reserved_concurrency"]},
                            tags=["lambda.scale", "remediation"])
    if verb == "rollback":
        fn = _fn(state, name)
        if fn is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"lambda {name} not found",
                                tags=["lambda.rollback"])
        fn["version"] = params.get("version", "$LATEST")
        fn["last_error"] = None
        state.mitigation_applied = True
        return ActionResult(ok=True, payload={"function": name,
                                              "rolled_back_to": fn["version"]},
                            tags=["lambda.rollback", "remediation"])
    if verb == "delete":
        if name in state.lambda_:
            del state.lambda_[name]
            return ActionResult(ok=True, payload={"deleted": name},
                                tags=["lambda.delete"])
        return ActionResult(ok=False, error="ResourceNotFoundException",
                            error_message=f"lambda {name} not found",
                            tags=["lambda.delete"])
    return generic.handle(spec, params, state)
