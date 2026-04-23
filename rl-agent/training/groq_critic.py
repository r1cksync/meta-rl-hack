"""Groq-backed strong critic for the hybrid actor-critic trainer.

The critic receives (observation, action, recent history) and returns a
shaping bonus in [-0.15, +0.15]. Groq's free-tier `llama-3.1-8b-instant`
typically returns in <500ms which keeps the training loop fast.

Usage::

    critic = GroqCritic()                # picks up GROQ_API_KEY
    critic.reset_episode()
    bonus = critic.score(observation, action, history)

When `GROQ_API_KEY` is missing or every call fails, a deterministic
heuristic fallback is used (same shape as before) so training never dies.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import httpx

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqCritic:
    HEURISTIC_ACTIONS_GOOD = {
        "query_logs", "query_metrics", "get_service_dependencies", "get_trace",
        "exec_kubectl",
    }
    HEURISTIC_ACTIONS_WRITE = {
        "rollback_deployment", "restart_pods", "scale_deployment",
        "apply_config_patch", "delete_chaos_experiment",
    }

    def __init__(self,
                 model: str = "llama-3.1-8b-instant",
                 api_key: Optional[str] = None,
                 max_calls_per_episode: int = 4,
                 timeout: float = 12.0):
        self.model = model
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.max_calls_per_episode = max_calls_per_episode
        self.timeout = timeout
        self._calls_this_episode = 0
        self._client = httpx.Client(timeout=timeout)
        self.enabled = bool(self.api_key)
        self.total_calls = 0
        self.total_failures = 0
        if self.enabled:
            log.info("GroqCritic: model=%s budget=%d/episode",
                     self.model, self.max_calls_per_episode)
        else:
            log.warning("GroqCritic: GROQ_API_KEY missing — heuristic fallback only")

    def reset_episode(self) -> None:
        self._calls_this_episode = 0

    # ------------------------------------------------------------------
    def score(self, observation: dict, action: dict, history: list[dict]) -> float:
        h = self._heuristic(action, history)
        if self.enabled and self._calls_this_episode < self.max_calls_per_episode:
            g = self._groq(observation, action, history)
            if g is not None:
                self._calls_this_episode += 1
                # Blend 70% Groq + 30% heuristic, then clip.
                return max(-0.15, min(0.15, 0.7 * g + 0.3 * h))
        return max(-0.15, min(0.15, h))

    # ------------------------------------------------------------------
    def _heuristic(self, action: dict, history: list[dict]) -> float:
        at = action.get("action_type", "")
        investigated = any(h.get("action_type", "") in self.HEURISTIC_ACTIONS_GOOD
                           for h in history)
        if at in self.HEURISTIC_ACTIONS_GOOD:
            return 0.06 if len(history) <= 4 else -0.02
        if at in self.HEURISTIC_ACTIONS_WRITE:
            return 0.13 if investigated else -0.10
        if at == "submit_postmortem":
            rc = (action.get("params", {}) or {}).get("root_cause", "")
            if investigated and isinstance(rc, str) and len(rc) > 12:
                return 0.10
            return -0.05
        return 0.0

    # ------------------------------------------------------------------
    def _groq(self, observation: dict, action: dict, history: list[dict]) -> float | None:
        # Compose a tight, structured prompt — the 8B model handles short
        # JSON well and returns a single object reliably.
        recent = [{"a": h.get("action_type"),
                   "p": (h.get("params") or {}).get("service")
                        or (h.get("params") or {}).get("deployment")
                        or (h.get("params") or {}).get("experiment_name", ""),
                   } for h in history[-4:]]
        sys = ("You are a principal SRE critiquing an on-call AI agent's "
               "next action. Reply with ONLY a JSON object: "
               "{\"score\": <float -1.0..1.0>, \"why\": <short string>}. "
               "Reward investigation before mitigation, correct service "
               "targeting, and well-written postmortems. Penalise blind "
               "writes, repeats, and chasing red herrings.")
        user = (
            f"ACTION: {json.dumps(action)[:300]}\n"
            f"RECENT_STEPS: {json.dumps(recent)}\n"
            f"BLAST_RADIUS_PCT: {observation.get('blast_radius_pct', 'n/a')}\n"
            f"PHASE: {observation.get('phase', 'n/a')}\n"
        )
        try:
            r = self._client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": sys},
                                 {"role": "user", "content": user}],
                    "temperature": 0.2,
                    "max_tokens": 80,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            self.total_calls += 1
            content = r.json()["choices"][0]["message"]["content"]
            try:
                obj = json.loads(content)
                score = float(obj.get("score", 0.0))
            except (json.JSONDecodeError, TypeError, ValueError):
                m = re.search(r'"score"\s*:\s*(-?\d*\.?\d+)', content)
                score = float(m.group(1)) if m else 0.0
            score = max(-1.0, min(1.0, score))
            return score * 0.15  # map [-1,1] -> [-0.15, 0.15]
        except Exception as e:
            self.total_failures += 1
            log.warning("groq critic call failed: %s", str(e)[:120])
            return None
