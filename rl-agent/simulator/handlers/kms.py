"""KMS handler — keys, aliases, key state, encrypt/decrypt."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def _k(state: SimState, alias: str | None) -> dict | None:
    if not alias:
        return None
    return state.kms.get(alias)


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    alias = params.get("resource_id") or params.get("name") \
        or params.get("key_alias")

    if verb in ("describe", "get", "head", "get_status", "get_policy"):
        k = _k(state, alias)
        if k is None:
            return ActionResult(ok=False, error="NotFoundException",
                                error_message=f"kms key {alias} not found",
                                tags=["kms.describe"])
        return ActionResult(ok=True,
                            payload={"alias": alias,
                                     "state": k["state"],
                                     "scheduled_deletion": k.get("pending_deletion_days"),
                                     "policy": k.get("policy", "")},
                            tags=["kms.describe", "resource_policy"])
    if verb == "list":
        return ActionResult(ok=True,
                            payload={"aliases": list(state.kms.keys())},
                            tags=["kms.list"])
    if verb in ("encrypt", "decrypt"):
        k = _k(state, alias)
        if k is None:
            return ActionResult(ok=False, error="NotFoundException",
                                error_message=f"kms key {alias} not found",
                                tags=[f"kms.{verb}"])
        if k["state"] == "PendingDeletion":
            return ActionResult(ok=False, error="KMSInvalidStateException",
                                error_message="key is pending deletion",
                                tags=[f"kms.{verb}"])
        return ActionResult(ok=True,
                            payload={"key": alias, "result": "ok"},
                            tags=[f"kms.{verb}"])
    if verb == "enable":
        k = _k(state, alias)
        if k is None:
            return ActionResult(ok=False, error="NotFoundException",
                                error_message=f"kms key {alias} not found",
                                tags=["kms.enable"])
        k["state"] = "Enabled"
        k["pending_deletion_days"] = None
        state.remediated.add("kms_enable")
        state.mitigation_applied = True
        state.emit_cloudtrail("CancelKeyDeletion", resources=[alias])
        return ActionResult(ok=True, payload={"key": alias, "state": "Enabled"},
                            tags=["kms.enable", "remediation"])
    if verb == "disable":
        k = _k(state, alias)
        if k is None:
            return ActionResult(ok=False, error="NotFoundException",
                                error_message=f"kms key {alias} not found",
                                tags=["kms.disable"])
        k["state"] = "Disabled"
        return ActionResult(ok=True, payload={"key": alias, "state": "Disabled"},
                            tags=["kms.disable"])
    if verb == "delete":
        k = _k(state, alias)
        if k is None:
            return ActionResult(ok=False, error="NotFoundException",
                                error_message=f"kms key {alias} not found",
                                tags=["kms.delete"])
        k["state"] = "PendingDeletion"
        k["pending_deletion_days"] = 7
        return ActionResult(ok=True, payload={"key": alias,
                                              "state": "PendingDeletion"},
                            tags=["kms.delete"])
    return generic.handle(spec, params, state)
