"""CloudWatch handler — alarms, log groups + insights queries, metrics."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def _ensure(state: SimState) -> dict:
    if "alarms" not in state.cloudwatch:
        state.cloudwatch["alarms"] = {}
        state.cloudwatch["log_groups"] = {}
        state.cloudwatch["metrics"] = {}
    return state.cloudwatch


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    cw = _ensure(state)
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name")

    if verb == "list":
        return ActionResult(ok=True,
                            payload={"alarms": list(cw["alarms"].keys()),
                                     "log_groups": list(cw["log_groups"].keys())},
                            tags=["cloudwatch.list"])
    if verb in ("describe", "get", "get_status"):
        if name in cw["alarms"]:
            return ActionResult(ok=True, payload=cw["alarms"][name],
                                tags=["cloudwatch.describe"])
        if name in cw["log_groups"]:
            return ActionResult(ok=True, payload=cw["log_groups"][name],
                                tags=["cloudwatch.describe"])
        return ActionResult(ok=False, error="ResourceNotFound",
                            error_message=f"{name} not found",
                            tags=["cloudwatch.describe"])
    if verb == "get_logs":
        lg_name = name or params.get("log_group")
        lg = cw["log_groups"].get(lg_name) or {"streams": {}}
        out = []
        pattern = (params.get("filter") or "").lower()
        for stream_name, events in lg["streams"].items():
            for ev in events:
                if not pattern or pattern in ev.get("message", "").lower():
                    out.append({"stream": stream_name, **ev})
        out = out[-20:]
        return ActionResult(ok=True,
                            payload={"events": out, "count": len(out),
                                     "log_group": lg_name},
                            tags=["cloudwatch.get_logs", "insights"])
    if verb == "get_metrics":
        return ActionResult(ok=True,
                            payload={"metric": name,
                                     "datapoints": [{"ts": state.clock_s,
                                                     "value": 1.0}]},
                            tags=["cloudwatch.get_metrics"])
    if verb == "create":
        nm = params.get("name") or name
        cw["alarms"][nm] = {"name": nm, "state": "OK",
                            "threshold": params.get("config", {}).get("threshold")}
        return ActionResult(ok=True, payload={"alarm": nm},
                            tags=["cloudwatch.create"])
    if verb == "enable":
        if name in cw["alarms"]:
            cw["alarms"][name]["state"] = "OK"
            return ActionResult(ok=True, payload={"alarm": name, "state": "OK"},
                                tags=["cloudwatch.enable"])
        return ActionResult(ok=False, error="AlarmNotFound",
                            error_message=f"alarm {name} not found",
                            tags=["cloudwatch.enable"])
    return generic.handle(spec, params, state)
