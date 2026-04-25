"""Generic fallback handler.

Used for services that don't have a bespoke module. Produces a deterministic,
shape-realistic response based on the action's verb/kind. Side-effects are
limited to growing `state.generic[service]` so the simulator can still answer
follow-up describe/list calls coherently.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..state import ActionResult, SimState


def _store(state: SimState, service: str) -> dict:
    return state.generic.setdefault(service, {"resources": {}, "events": []})


def _det_id(*parts: Any) -> str:
    """Deterministic short id derived from the inputs."""
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return h[:12]


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    svc   = spec["service"]
    verb  = spec["verb"]
    kind  = spec["kind"]
    store = _store(state, svc)
    rid   = params.get("resource_id") or params.get("name")

    # ---- read verbs ---------------------------------------------------
    if kind == "read":
        if verb in ("list", "list_versions", "list_tags", "list_events"):
            items = list(store["resources"].keys())
            return ActionResult(ok=True,
                                payload={"items": items, "count": len(items)},
                                tags=[f"{svc}.{verb}"])
        if verb in ("describe", "get", "head", "get_policy", "get_tags",
                    "get_status", "get_metrics", "get_logs"):
            if rid is None:
                # Some verbs are global (e.g. get_quota); just return a stub.
                return ActionResult(ok=True,
                                    payload={"service": svc, "verb": verb,
                                             "result": "ok"},
                                    tags=[f"{svc}.{verb}"])
            res = store["resources"].get(rid)
            if res is None:
                return ActionResult(ok=False,
                                    error="ResourceNotFoundException",
                                    error_message=f"{svc}/{rid} not found",
                                    tags=[f"{svc}.{verb}"])
            return ActionResult(ok=True, payload=res,
                                tags=[f"{svc}.{verb}"])
        if verb == "get_quota":
            code = params.get("service_code") or svc
            return ActionResult(ok=True,
                                payload={"service_code": code,
                                         "quota": 1000, "used": 12},
                                tags=[f"{svc}.{verb}"])
        if verb == "simulate_policy":
            return ActionResult(ok=True,
                                payload={"decision": "allowed",
                                         "principal": params.get("principal", "?"),
                                         "action": params.get("action_name", "?")},
                                tags=[f"{svc}.simulate_policy", "iam_sim"])
        if verb == "diff_versions":
            return ActionResult(ok=True,
                                payload={"v1": params.get("v1", "v1"),
                                         "v2": params.get("v2", "v2"),
                                         "diff": "no changes"},
                                tags=[f"{svc}.diff_versions"])
        # Unknown read — deterministic stub.
        return ActionResult(ok=True,
                            payload={"service": svc, "verb": verb,
                                     "stub": True},
                            tags=[f"{svc}.{verb}"])

    # ---- write / mutate verbs -----------------------------------------
    if kind in ("write", "mutate"):
        if verb == "create":
            name = params.get("name") or _det_id(svc, len(store["resources"]))
            if name in store["resources"]:
                return ActionResult(ok=False,
                                    error="ResourceAlreadyExistsException",
                                    error_message=f"{svc}/{name} exists",
                                    tags=[f"{svc}.create"])
            store["resources"][name] = {"id": name, "state": "ACTIVE",
                                        "config": params.get("config", {})}
            state.emit_cloudtrail(f"Create{svc.capitalize()}",
                                  resources=[name])
            return ActionResult(ok=True, payload={"id": name},
                                tags=[f"{svc}.create"])
        if verb == "delete":
            if rid is None or rid not in store["resources"]:
                return ActionResult(ok=False,
                                    error="ResourceNotFoundException",
                                    error_message=f"{svc}/{rid} not found",
                                    tags=[f"{svc}.delete"])
            del store["resources"][rid]
            state.emit_cloudtrail(f"Delete{svc.capitalize()}",
                                  resources=[rid])
            return ActionResult(ok=True, payload={"deleted": rid},
                                tags=[f"{svc}.delete"])
        if verb == "update":
            if rid is None or rid not in store["resources"]:
                return ActionResult(ok=False,
                                    error="ResourceNotFoundException",
                                    error_message=f"{svc}/{rid} not found",
                                    tags=[f"{svc}.update"])
            store["resources"][rid].update(params.get("config", {}))
            return ActionResult(ok=True, payload={"updated": rid},
                                tags=[f"{svc}.update"])
        if verb in ("start", "stop", "restart", "pause", "resume",
                    "enable", "disable", "rollback", "rotate", "purge"):
            if rid and rid in store["resources"]:
                store["resources"][rid]["state"] = verb.upper()
            tag_suffix = "remediation" if verb in (
                "rollback", "restart", "rotate", "purge",
                "enable", "resume") else verb
            return ActionResult(ok=True, payload={"resource": rid,
                                                  "new_state": verb.upper()},
                                tags=[f"{svc}.{verb}", tag_suffix])
        if verb in ("invoke", "publish", "send", "encrypt", "decrypt",
                    "receive"):
            return ActionResult(ok=True, payload={"resource": rid,
                                                  "verb": verb,
                                                  "status": 200},
                                tags=[f"{svc}.{verb}"])
        if verb == "scale":
            cap = params.get("capacity", 1)
            if rid and rid in store["resources"]:
                store["resources"][rid]["capacity"] = cap
            return ActionResult(ok=True, payload={"resource": rid,
                                                  "capacity": cap},
                                tags=[f"{svc}.scale", "remediation"])
        if verb in ("tag", "untag"):
            if rid and rid in store["resources"]:
                tags = store["resources"][rid].setdefault("tags", {})
                if verb == "tag":
                    tags.update(params.get("tags", {}))
                else:
                    for k in params.get("tag_keys", []):
                        tags.pop(k, None)
            return ActionResult(ok=True, payload={"resource": rid},
                                tags=[f"{svc}.{verb}"])
        if verb in ("put_policy", "delete_policy"):
            if rid and rid in store["resources"]:
                if verb == "put_policy":
                    store["resources"][rid]["policy"] = params.get("policy")
                else:
                    store["resources"][rid].pop("policy", None)
            return ActionResult(ok=True, payload={"resource": rid},
                                tags=[f"{svc}.{verb}"])

    # ---- poll ---------------------------------------------------------
    if kind == "poll":
        if rid and rid in store["resources"]:
            return ActionResult(ok=True,
                                payload={"resource": rid,
                                         "state": store["resources"][rid].get("state", "ACTIVE")},
                                tags=[f"{svc}.{verb}"])
        return ActionResult(ok=False, error="ResourceNotFoundException",
                            error_message=f"{svc}/{rid} not found",
                            tags=[f"{svc}.{verb}"])

    # default
    return ActionResult(ok=True,
                        payload={"service": svc, "verb": verb, "stub": True},
                        tags=[f"{svc}.{verb}"])
