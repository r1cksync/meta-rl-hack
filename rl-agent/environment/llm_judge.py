"""LLM judge with three expert personas.

Mirrors the "Snorkel AI expert-in-the-loop" idea from kube-sre-gym: three
different SRE personas evaluate the agent's per-step action with progressively
stricter criteria. When no API key is configured the judge falls back to a
deterministic heuristic scorer so CI and MOCK_MODE remain usable.

Personas:
    - junior:    lenient; partial credit; rewards attempts
    - senior:    standard SRE expectations; rewards systematic diagnosis
    - principal: strict; penalises inefficiency and random commands

The judge also labels each step with an SRE workflow *phase*:
    triage > investigate > fix > verify
so the environment can compute phase-order bonuses.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Literal

from .models import Action, ActionType, READ_ACTIONS, WRITE_ACTIONS


Persona = Literal["junior", "senior", "principal"]
Phase = Literal["triage", "investigate", "fix", "verify"]


PERSONA_SYSTEM = {
    "junior": (
        "You are a JUNIOR SRE reviewer. Be lenient: give partial credit for any "
        "reasonable diagnostic attempt. Only penalise obviously harmful actions."
    ),
    "senior": (
        "You are a SENIOR SRE reviewer. Apply standard on-call expectations: "
        "reward systematic triage → investigate → fix → verify flow. Penalise "
        "write actions taken before logs/metrics have been inspected."
    ),
    "principal": (
        "You are a PRINCIPAL SRE reviewer. Be strict. Reward elegant, minimal "
        "fixes. Penalise repeated or redundant commands, wrong targets, and "
        "any action that widens the blast radius."
    ),
}


PERSONA_RANGE: dict[Persona, tuple[float, float]] = {
    "junior":    (-0.5, 1.0),
    "senior":    (-0.75, 1.0),
    "principal": (-1.0, 1.0),
}


JUDGE_USER_TEMPLATE = """Action taken (step {step}): {action_type} {params}

Action result (truncated):
{action_result}

Current blast radius: {blast_radius:.1f}%
Cumulative reward so far: {cumulative_reward:.2f}
Unique services investigated: {inspected_services}
Current inferred phase: {phase}

Score this action in [-1.0, 1.0] (higher = better SRE practice).
Return strict JSON: {{"score": <float>, "phase": <"triage"|"investigate"|"fix"|"verify">, "reason": "<one sentence>"}}
"""


@dataclass
class JudgeResult:
    score: float
    phase: Phase
    reason: str
    persona: Persona
    used_llm: bool


class LLMJudge:
    """LLM or heuristic per-step action judge, persona-aware."""

    def __init__(
        self,
        api_base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._api_base = api_base_url or os.getenv("API_BASE_URL", "https://api.openai.com/v1")
        self._model = model or os.getenv("JUDGE_MODEL", os.getenv("MODEL_NAME", "gpt-4o-mini"))
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("HF_TOKEN")

    # ------------------------------------------------------------------ API

    def judge(
        self,
        *,
        action: Action,
        action_result: str,
        step: int,
        blast_radius: float,
        cumulative_reward: float,
        inspected_services: int,
        persona: Persona = "senior",
        use_llm: bool = True,
    ) -> JudgeResult:
        phase = self._infer_phase(action, step)
        if use_llm and self._api_key:
            try:
                return self._judge_via_llm(
                    action=action,
                    action_result=action_result,
                    step=step,
                    blast_radius=blast_radius,
                    cumulative_reward=cumulative_reward,
                    inspected_services=inspected_services,
                    persona=persona,
                    fallback_phase=phase,
                )
            except Exception:
                pass
        score = self._heuristic_score(action, action_result, step, inspected_services, persona)
        return JudgeResult(
            score=score,
            phase=phase,
            reason="heuristic (no LLM)",
            persona=persona,
            used_llm=False,
        )

    # -------------------------------------------------------------- helpers

    def _judge_via_llm(
        self,
        *,
        action: Action,
        action_result: str,
        step: int,
        blast_radius: float,
        cumulative_reward: float,
        inspected_services: int,
        persona: Persona,
        fallback_phase: Phase,
    ) -> JudgeResult:
        import httpx  # lazy import

        truncated = (action_result or "")[:1500]
        user = JUDGE_USER_TEMPLATE.format(
            step=step,
            action_type=action.type.value,
            params=json.dumps(action.params),
            action_result=truncated,
            blast_radius=blast_radius,
            cumulative_reward=cumulative_reward,
            inspected_services=inspected_services,
            phase=fallback_phase,
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": PERSONA_SYSTEM[persona]},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = self._api_base.rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=20.0) as c:
            r = c.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        lo, hi = PERSONA_RANGE[persona]
        score = float(parsed.get("score", 0.0))
        score = max(lo, min(hi, score))
        phase_val = parsed.get("phase", fallback_phase)
        if phase_val not in ("triage", "investigate", "fix", "verify"):
            phase_val = fallback_phase
        return JudgeResult(
            score=score,
            phase=phase_val,
            reason=str(parsed.get("reason", ""))[:240],
            persona=persona,
            used_llm=True,
        )

    # --- heuristic fallback ---------------------------------------------

    def _heuristic_score(
        self,
        action: Action,
        action_result: str,
        step: int,
        inspected_services: int,
        persona: Persona,
    ) -> float:
        score = 0.0
        if action.type in READ_ACTIONS:
            score += 0.3
            if inspected_services >= 2:
                score += 0.2
        elif action.type in WRITE_ACTIONS:
            if inspected_services == 0:
                score -= 0.6 if persona == "principal" else 0.3
            else:
                score += 0.4
        elif action.type == ActionType.SUBMIT_POSTMORTEM:
            score += 0.5 if len(action.params.get("root_cause", "")) > 20 else 0.1

        if "error" in (action_result or "").lower():
            score -= 0.15

        # Principal: extra penalty for late-episode churn without a fix.
        if persona == "principal" and step > 10 and action.type in READ_ACTIONS:
            score -= 0.1

        lo, hi = PERSONA_RANGE[persona]
        return max(lo, min(hi, score))

    def _infer_phase(self, action: Action, step: int) -> Phase:
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            return "verify"
        if action.type in WRITE_ACTIONS:
            return "fix"
        if action.type in READ_ACTIONS:
            # First two steps = triage; later reads = investigate
            return "triage" if step <= 1 else "investigate"
        return "investigate"


# --------------------------------------------------------------- phase logic


PHASE_ORDER = ["triage", "investigate", "fix", "verify"]


def phase_order_bonus(prev_phase: Phase | None, next_phase: Phase) -> float:
    """Reward the agent for following `triage → investigate → fix → verify`.

    +0.10 when the phase strictly progresses forward.
    -0.10 when the agent regresses (e.g. goes back to triage after fix).
    0 for staying in the same phase.
    """
    if prev_phase is None:
        return 0.05 if next_phase == "triage" else 0.0
    prev_idx = PHASE_ORDER.index(prev_phase)
    next_idx = PHASE_ORDER.index(next_phase)
    if next_idx == prev_idx:
        return 0.0
    if next_idx == prev_idx + 1:
        return 0.10
    if next_idx > prev_idx + 1:
        return 0.05  # skipping ahead — small bonus
    return -0.10  # regressed


# --------------------------------------------------------------- repeat detection


_SIGNATURE_RE = re.compile(r"\s+")


def action_signature(action: Action) -> str:
    """Canonical signature of an action for repeat-detection."""
    parts = [action.type.value]
    for k in sorted(action.params.keys()):
        v = action.params[k]
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        parts.append(f"{k}={v}")
    return _SIGNATURE_RE.sub(" ", "|".join(parts)).strip().lower()
