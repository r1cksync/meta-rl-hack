"""Simulator dispatch engine.

`dispatch(action, state)` looks up the action id in the catalog, applies
any scenario-scheduled failures, then routes to the right handler. If no
bespoke handler exists for the service, it falls back to the generic
handler which produces a deterministic, schema-shaped response.
"""

from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .state import ActionResult, SimState

CAT_DIR = Path(__file__).resolve().parent / "catalogs"


@lru_cache(maxsize=1)
def load_catalogs() -> dict[str, Any]:
    """Read services.json + actions.json + errors.json once and cache."""
    services = json.loads((CAT_DIR / "services.json").read_text(encoding="utf-8"))
    actions  = json.loads((CAT_DIR / "actions.json").read_text(encoding="utf-8"))
    errors   = json.loads((CAT_DIR / "errors.json").read_text(encoding="utf-8"))
    by_id    = {a["id"]: a for a in actions}
    return {"services": services, "actions": actions,
            "errors": errors, "by_id": by_id}


# Map service-slug -> handler module name. Anything not listed routes to
# `generic`. Each handler exposes `handle(action, params, state)`.
_HANDLERS = {
    "sqs":            "sqs",
    "lambda":         "lambda_",
    "ec2":            "ec2",
    "eks":            "eks",
    "s3":             "s3",
    "dynamodb":       "dynamodb",
    "secretsmanager": "secrets",
    "kms":            "kms",
    "ssm":            "ssm",
    "iam":            "iam",
    "events":         "eventbridge",
    "stepfunctions":  "stepfunctions",
    "cloudwatch":     "cloudwatch",
    "cloudtrail":     "cloudtrail",
}


def _load_handler(service: str):
    name = _HANDLERS.get(service, "generic")
    return importlib.import_module(f".handlers.{name}", package=__package__)


def dispatch(action: dict, state: SimState) -> ActionResult:
    """Dispatch one action.

    `action` is `{"id": "lambda.invoke", "params": {...}}`. Returns a
    fully-populated `ActionResult` and mutates `state` accordingly.
    """
    cat   = load_catalogs()
    aid   = action.get("id") or f"{action.get('service','?')}.{action.get('verb','?')}"
    params = action.get("params", {}) or {}

    # ---------------- Runbook trap arm-check ---------------------------
    # We inspect each armed trap *before* dispatch to record that the
    # forbidden action was attempted. Corruption is applied AFTER the
    # action runs so that the action's own status mutations don't override
    # the trap's CORRUPTED state.
    triggered_traps = []
    for trap in state.runbook_traps:
        if trap.maybe_trigger(aid):
            triggered_traps.append(trap)

    # ---------------- platform.* pseudo-service ------------------------
    if aid.startswith("platform."):
        verb = aid.split(".", 1)[1]
        spec = {"id": aid, "service": "platform", "verb": verb}
        handler = importlib.import_module(".handlers.platform",
                                          package=__package__)
        try:
            result = handler.handle(spec, params, state)
        except Exception as e:                            # pragma: no cover
            result = ActionResult(ok=False, error="ServiceException",
                                  error_message=str(e))
        if triggered_traps:
            from .topology import CORRUPTED
            for trap in triggered_traps:
                state.topology.set_status(trap.target, CORRUPTED)
                state.action_log.append({
                    "ts": state.clock_s, "action": "_runbook.trap_triggered",
                    "params": {"runbook": trap.runbook_id, "target": trap.target,
                               "trigger": aid},
                    "ok": False, "error": "RunbookTrapTriggered",
                })
            result.tags = list(result.tags) + ["runbook_trap"]
        state.log(aid, params, result)
        state.tick()
        return result

    spec  = cat["by_id"].get(aid)
    if spec is None:
        result = ActionResult(
            ok=False, error="InvalidAction",
            error_message=f"unknown action id: {aid}",
        )
        state.log(aid, params, result)
        return result

    # Scheduled failures (set by scenario.load_scenario) take priority.
    sched = state.consume_scheduled_failure(aid)
    if sched is not None:
        msg = sched.get("message") or f"scheduled failure for {aid}"
        result = ActionResult(
            ok=False, error=sched["error"], error_message=msg,
            tags=["scheduled_failure"],
        )
        state.log(aid, params, result)
        state.tick()
        return result

    handler = _load_handler(spec["service"])
    try:
        result = handler.handle(spec, params, state)
    except Exception as e:                                # pragma: no cover
        result = ActionResult(ok=False, error="ServiceException",
                              error_message=str(e))
    # Apply trap corruption AFTER the handler so the action's own status
    # writes don't override CORRUPTED.
    if triggered_traps:
        from .topology import CORRUPTED
        for trap in triggered_traps:
            state.topology.set_status(trap.target, CORRUPTED)
            state.action_log.append({
                "ts": state.clock_s, "action": "_runbook.trap_triggered",
                "params": {"runbook": trap.runbook_id, "target": trap.target,
                           "trigger": aid},
                "ok": False, "error": "RunbookTrapTriggered",
            })
        # Surface the catastrophe in the action result tags.
        result.tags = list(result.tags) + ["runbook_trap"]
    state.log(aid, params, result)
    state.tick()
    return result
