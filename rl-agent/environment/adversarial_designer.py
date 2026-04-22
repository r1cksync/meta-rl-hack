"""Adversarial scenario designer.

Produces novel incident scenarios that target the agent's tracked weaknesses.
Mirrors kube-sre-gym's adversarial designer, but adapted to our scenario
schema (TaskScenario). The LLM is optional — when no API key is configured
the designer falls back to a deterministic procedural composer that mutates
existing scenarios (injects extra alerts, swaps red herrings, raises time
pressure, composes multi-fault bundles).

Usage
-----
>>> designer = AdversarialDesigner(base_scenarios_dir=Path(".../scenarios"))
>>> scenario = designer.design(
...     primary_task_id="task6",
...     companion_task_ids=["task3"],
...     mastery={"task6": 0.9, "task3": 0.2},
...     use_llm=True,
... )
>>> scenario.fault_type
'multi_fault_adversarial'
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TaskScenario


DESIGNER_PROMPT = """You are an adversarial SRE trainer creating realistic production incident
scenarios for a reinforcement-learning agent. The agent has demonstrated the
following per-task mastery (1.0 = solved; 0.0 = always fails):

{mastery_table}

Design ONE new hard scenario that specifically targets the agent's weaknesses.
Return strict JSON with the following keys (no markdown, no prose):

{{
  "task_id":                    string (e.g. "adv-<timestamp>"),
  "difficulty":                 "hard",
  "target_score":               number between 0.15 and 0.35,
  "fault_type":                 short snake_case label,
  "chaos_experiment_name":      string or null,
  "ground_truth_root_cause":    snake_case string,
  "correct_mitigation_action":  one of {action_space},
  "correct_mitigation_target":  deployment name (e.g. "payments-api") or chaos experiment,
  "wrong_mitigation_penalty_services": array of service names,
  "useful_log_keywords":        array of 3-6 short strings,
  "red_herrings":               array of 2-4 misleading service names,
  "reference_postmortem":       3-6 sentence postmortem written by a senior SRE
}}

Constraints:
 - Services available: payments-api, inventory-service, order-worker, notification-service, checkout-frontend
 - If fault is chaos-induced, correct_mitigation_action MUST be "delete_chaos_experiment"
 - If fault is config/deploy-related, correct_mitigation_action MUST be "rollback_deployment" or "apply_config_patch" or "restart_pods"
 - Red herrings MUST be plausible but wrong targets
 - Do NOT reuse a scenario the agent has already mastered
"""


ACTION_SPACE_VALUES = [
    "rollback_deployment",
    "restart_pods",
    "scale_deployment",
    "apply_config_patch",
    "delete_chaos_experiment",
]


@dataclass
class DesignRequest:
    primary_task_id: str
    companion_task_ids: list[str]
    mastery: dict[str, float]
    use_llm: bool = True


class AdversarialDesigner:
    """Generates novel or composed scenarios. LLM-optional."""

    def __init__(
        self,
        base_scenarios_dir: Path,
        api_base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._dir = Path(base_scenarios_dir)
        self._api_base = api_base_url or os.getenv("API_BASE_URL", "https://api.openai.com/v1")
        self._model = model or os.getenv("ADVERSARIAL_MODEL", os.getenv("MODEL_NAME", "gpt-4o-mini"))
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("HF_TOKEN")

    # ------------------------------------------------------------------ API

    def design(self, request: DesignRequest) -> TaskScenario:
        """Produce a new scenario. Tries LLM first, falls back to procedural."""
        if request.use_llm and self._api_key:
            try:
                return self._design_via_llm(request)
            except Exception:
                # Fall through to procedural composer.
                pass
        return self._design_procedural(request)

    def compose_multi_fault(self, task_ids: list[str]) -> TaskScenario:
        """Compose a multi-fault scenario from N base scenarios without LLM."""
        scenarios = [self._load_base(tid) for tid in task_ids]
        primary = scenarios[0]
        merged_keywords: list[str] = []
        merged_red_herrings: list[str] = []
        for s in scenarios:
            merged_keywords.extend(s.useful_log_keywords)
            merged_red_herrings.extend(s.red_herrings)
        return TaskScenario(
            task_id=f"multi-{'+'.join(task_ids)}",
            difficulty="hard",
            target_score=max(0.15, min(s.target_score for s in scenarios) - 0.05),
            fault_type=f"multi_fault({','.join(s.fault_type for s in scenarios)})",
            chaos_experiment_name=primary.chaos_experiment_name,
            ground_truth_root_cause=primary.ground_truth_root_cause,
            correct_mitigation_action=primary.correct_mitigation_action,
            correct_mitigation_target=primary.correct_mitigation_target,
            wrong_mitigation_penalty_services=list(
                {
                    svc
                    for s in scenarios
                    for svc in s.wrong_mitigation_penalty_services
                }
            ),
            useful_log_keywords=list(dict.fromkeys(merged_keywords))[:10],
            red_herrings=list(dict.fromkeys(merged_red_herrings))[:6],
            reference_postmortem=(
                f"Two concurrent faults: {primary.fault_type} and "
                f"{scenarios[1].fault_type}. Primary root cause: {primary.ground_truth_root_cause}."
            ),
        )

    # -------------------------------------------------------------- helpers

    def _design_via_llm(self, request: DesignRequest) -> TaskScenario:
        import httpx  # lazy import — HF Space may not have httpx in the hot path

        mastery_table = "\n".join(
            f"  - {tid}: {score:.2f}"
            for tid, score in sorted(request.mastery.items(), key=lambda kv: kv[1])
        ) or "  - (no history)"

        prompt = DESIGNER_PROMPT.format(
            mastery_table=mastery_table,
            action_space=json.dumps(ACTION_SPACE_VALUES),
        )

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "You are an expert SRE incident designer. Return strict JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = self._api_base.rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=30.0) as c:
            r = c.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        # Backfill required fields
        parsed.setdefault("chaos_experiment_name", None)
        parsed.setdefault("wrong_mitigation_penalty_services", [])
        parsed.setdefault("red_herrings", [])
        parsed.setdefault("useful_log_keywords", [])
        parsed.setdefault("reference_postmortem", "")
        return TaskScenario(**parsed)

    def _design_procedural(self, request: DesignRequest) -> TaskScenario:
        """Deterministic fallback: mutate or compose existing scenarios."""
        if request.companion_task_ids:
            return self.compose_multi_fault([request.primary_task_id, *request.companion_task_ids])

        base = self._load_base(request.primary_task_id)
        rng = random.Random(hash(request.primary_task_id) & 0xFFFF)
        # Inject an extra red herring and tighten the target score.
        extra_red_herrings = ["redis", "postgres", "kafka", "notification-service"]
        rng.shuffle(extra_red_herrings)
        merged_red = list(dict.fromkeys([*base.red_herrings, *extra_red_herrings[:2]]))[:6]
        return TaskScenario(
            task_id=f"adv-{request.primary_task_id}",
            difficulty="hard",
            target_score=max(0.15, base.target_score - 0.10),
            fault_type=f"adversarial({base.fault_type})",
            chaos_experiment_name=base.chaos_experiment_name,
            ground_truth_root_cause=base.ground_truth_root_cause,
            correct_mitigation_action=base.correct_mitigation_action,
            correct_mitigation_target=base.correct_mitigation_target,
            wrong_mitigation_penalty_services=base.wrong_mitigation_penalty_services,
            useful_log_keywords=base.useful_log_keywords,
            red_herrings=merged_red,
            reference_postmortem=base.reference_postmortem,
        )

    def _load_base(self, task_id: str) -> TaskScenario:
        # Find the scenario file whose task_id matches.
        for path in self._dir.glob("*.json"):
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("task_id") == task_id:
                return TaskScenario(**data)
        raise FileNotFoundError(f"scenario {task_id} not found in {self._dir}")
