"""Secrets Manager handler — secrets, rotation, versions."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def _s(state: SimState, name: str | None) -> dict | None:
    if not name:
        return None
    return state.secrets.get(name)


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("secret_name")

    if verb == "create":
        nm = params.get("name") or name
        state.secrets[nm] = {"name": nm, "value": params.get("config", {}).get("value", "init"),
                             "versions": ["v1"], "rotation_enabled": False,
                             "last_rotated_s": None,
                             "tags": {"RotationStatus": "NEVER"}}
        return ActionResult(ok=True, payload={"secret": nm},
                            tags=["secretsmanager.create"])
    if verb in ("describe", "get", "head", "get_status"):
        s = _s(state, name)
        if s is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"secret {name} not found",
                                tags=["secretsmanager.describe", "secret_rotation"])
        return ActionResult(ok=True,
                            payload={"name": s["name"],
                                     "rotation_enabled": s["rotation_enabled"],
                                     "last_rotated_s": s["last_rotated_s"],
                                     "version_count": len(s["versions"]),
                                     "tags": s["tags"]},
                            tags=["secretsmanager.describe", "secret_rotation"])
    if verb == "rotate":
        s = _s(state, name)
        if s is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"secret {name} not found",
                                tags=["secretsmanager.rotate"])
        new_ver = f"v{len(s['versions']) + 1}"
        s["versions"].append(new_ver)
        s["last_rotated_s"] = state.clock_s
        s["tags"]["RotationStatus"] = "ROTATED"
        s["tags"]["LastRotatedDays"] = "0"
        state.remediated.add("secret_rotation")
        state.mitigation_applied = True
        state.emit_cloudtrail("RotateSecret", resources=[name])
        return ActionResult(ok=True,
                            payload={"secret": name, "new_version": new_ver},
                            tags=["secretsmanager.rotate", "remediation"])
    if verb == "list_versions":
        s = _s(state, name)
        if s is None:
            return ActionResult(ok=False, error="ResourceNotFoundException",
                                error_message=f"secret {name} not found",
                                tags=["secretsmanager.list_versions"])
        return ActionResult(ok=True, payload={"versions": s["versions"]},
                            tags=["secretsmanager.list_versions"])
    if verb == "delete":
        if name in state.secrets:
            del state.secrets[name]
            return ActionResult(ok=True, payload={"deleted": name},
                                tags=["secretsmanager.delete"])
        return ActionResult(ok=False, error="ResourceNotFoundException",
                            error_message=f"secret {name} not found",
                            tags=["secretsmanager.delete"])
    return generic.handle(spec, params, state)
