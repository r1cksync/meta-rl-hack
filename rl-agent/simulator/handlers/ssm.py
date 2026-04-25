"""SSM handler — Parameter Store with version history."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("parameter_name")

    if verb == "create":
        nm = params.get("name") or name
        val = params.get("config", {}).get("value", "init")
        state.ssm[nm] = {"name": nm, "value": val, "version": 1,
                         "history": [{"v": 1, "value": val,
                                      "ts": state.clock_s}]}
        return ActionResult(ok=True, payload={"parameter": nm},
                            tags=["ssm.create"])
    if verb in ("describe", "get", "head", "get_status"):
        p = state.ssm.get(name) if name else None
        if p is None:
            return ActionResult(ok=False, error="ParameterNotFound",
                                error_message=f"ssm {name} not found",
                                tags=["ssm.describe"])
        return ActionResult(ok=True, payload=dict(p),
                            tags=["ssm.describe"])
    if verb == "diff_versions":
        p = state.ssm.get(name) if name else None
        if p is None:
            return ActionResult(ok=False, error="ParameterNotFound",
                                error_message=f"ssm {name} not found",
                                tags=["ssm.diff_versions", "ssm_diff"])
        v1 = int(params.get("v1", 1))
        v2 = int(params.get("v2", p["version"]))
        if not p["history"] or v1 == v2:
            return ActionResult(ok=True, payload={"diff": "no history"},
                                tags=["ssm.diff_versions", "ssm_diff"])
        h = {h["v"]: h["value"] for h in p["history"]}
        return ActionResult(ok=True,
                            payload={"v1": h.get(v1), "v2": h.get(v2),
                                     "diff": (h.get(v1) != h.get(v2))},
                            tags=["ssm.diff_versions", "ssm_diff"])
    if verb == "update":
        p = state.ssm.get(name) if name else None
        if p is None:
            return ActionResult(ok=False, error="ParameterNotFound",
                                error_message=f"ssm {name} not found",
                                tags=["ssm.update"])
        new_val = params.get("config", {}).get("value")
        p["version"] += 1
        p["value"] = new_val
        p["history"].append({"v": p["version"], "value": new_val,
                             "ts": state.clock_s})
        state.mitigation_applied = True
        return ActionResult(ok=True,
                            payload={"parameter": name,
                                     "new_version": p["version"]},
                            tags=["ssm.update", "remediation"])
    if verb == "rollback":
        p = state.ssm.get(name) if name else None
        if p is None:
            return ActionResult(ok=False, error="ParameterNotFound",
                                error_message=f"ssm {name} not found",
                                tags=["ssm.rollback"])
        target = int(params.get("version", 1))
        prior = next((h for h in p["history"] if h["v"] == target), None)
        if prior:
            p["value"] = prior["value"]
            p["version"] += 1
            p["history"].append({"v": p["version"], "value": prior["value"],
                                 "ts": state.clock_s})
            state.mitigation_applied = True
        return ActionResult(ok=True, payload={"parameter": name,
                                              "rolled_to": target},
                            tags=["ssm.rollback", "remediation"])
    return generic.handle(spec, params, state)
