"""Synthetic Slack channel — chaotic human chatter alongside structured signals.

Purpose: force the LLM agent to parse unstructured human text in addition to
JSON metrics. The stream is fully deterministic per `seed`, includes deliberate
red herrings (e.g. unrelated frontend hotfixes), and escalates the longer the
incident drags on.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable


# Templates: (author, severity, text). {svc} is filled with the incident's
# primary target. {min} is replaced with elapsed ticks.
_GENERIC: list[tuple[str, str, str]] = [
    ("@channel",                 "info",   "Customers reporting 500s on /checkout 🔥"),
    ("@oncall-pd",               "info",   "PagerDuty incident #INC-{tick:04d} acked."),
    ("Sara (Frontend)",          "info",   "Hey SRE, I just pushed a hotfix for the cart UI — could that be related?"),  # red herring
    ("Marketing",                "info",   "Did we change anything? The conversion funnel just dropped 22%."),
    ("VP Eng (Priya)",           "high",   "Are we back up yet? What's the ETA?"),
    ("Customer Support",         "high",   "We have 4 enterprise tickets open, can someone confirm root cause?"),
    ("Data team",                "info",   "Our nightly Athena pipeline is failing — probably unrelated, ignore for now."),
    ("Security",                 "info",   "Random ping: noticed elevated failed-auth in CloudTrail. Probably noise."),
    ("Intern (Jamal)",           "info",   "Should I just restart the cluster? My friend said that fixes everything 😅"),
    ("Comms",                    "high",   "Drafting a status-page post — what do you want to tell users?"),
    ("Sara (Frontend)",          "info",   "OK rolling back my hotfix just in case."),       # closes red herring
    ("DBA (Yuki)",               "info",   "Postgres CPU is climbing on the replica btw. FYI."),
    ("Finance",                  "info",   "Reminder: every minute of downtime is ~$8k for us."),
    ("@channel",                 "high",   "Status page just went red, the press is going to notice."),
    ("CEO",                      "high",   "I'm getting calls. Tell me what's happening in plain English."),
]

# Saboteur-coupled lines: emitted in response to a specific saboteur phase.
_PHASE_LINES: dict[str, list[tuple[str, str, str]]] = {
    "attack_primary": [
        ("Customer Support", "high",
         "Customers say {svc} is timing out — confirmed reproduction."),
    ],
    "attack_failover": [
        ("DBA (Yuki)",      "high",
         "{svc} just spiked to 90% CPU. Did someone kick off a backup job?"),
        ("On-call buddy",   "info",
         "Looks like the failover replica is now the bottleneck. Classic."),
    ],
    "attack_dependency": [
        ("Platform team",   "high",
         "{svc} latency went vertical — request queue is backing up."),
    ],
}


@dataclass
class SlackMessage:
    tick:   int
    author: str
    severity: str  # "info" | "high"
    text:   str

    def to_dict(self) -> dict:
        return {"tick": self.tick, "author": self.author,
                "severity": self.severity, "text": self.text}


@dataclass
class SlackStream:
    seed:        int = 0
    primary:     str = "service"
    msgs_per_tick: float = 1.2
    _msgs:       list[SlackMessage] = field(default_factory=list)
    _rng:        random.Random | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed ^ 0x51_AC_C0_DE)

    # ------------------------------------------------------------------
    def emit_for_tick(self, tick: int,
                      saboteur_phase: str | None = None) -> list[SlackMessage]:
        """Emit synthetic messages for this tick. Returns *new* messages only."""
        assert self._rng is not None
        new: list[SlackMessage] = []

        # Saboteur-driven escalations fire first (1 message, deterministic).
        if saboteur_phase and saboteur_phase in _PHASE_LINES:
            tmpl = self._rng.choice(_PHASE_LINES[saboteur_phase])
            new.append(SlackMessage(tick, tmpl[0], tmpl[1],
                                    tmpl[2].format(svc=self.primary)))

        # Generic chatter — Poisson-ish with a small floor.
        n_extra = max(0, int(self._rng.gauss(self.msgs_per_tick, 0.7)))
        for _ in range(n_extra):
            tmpl = self._rng.choice(_GENERIC)
            new.append(SlackMessage(tick, tmpl[0], tmpl[1],
                                    tmpl[2].format(svc=self.primary,
                                                   tick=tick)))
        self._msgs.extend(new)
        return new

    # ------------------------------------------------------------------
    def recent(self, last_n: int = 10) -> list[SlackMessage]:
        return list(self._msgs[-last_n:])

    def all(self) -> list[SlackMessage]:
        return list(self._msgs)
