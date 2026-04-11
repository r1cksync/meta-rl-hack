"""Postmortem grader — scores the agent's incident postmortem."""

from __future__ import annotations

import re
import string
from typing import Any


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


def score_root_cause(submitted: str, ground_truth: str) -> float:
    """Exact match after normalization: 0.3 or 0.0."""
    if _normalize(submitted) == _normalize(ground_truth):
        return 0.3
    # Also accept if ground truth is contained within the submitted text
    if _normalize(ground_truth) in _normalize(submitted):
        return 0.3
    return 0.0


def score_timeline(timeline: str) -> float:
    """0.1 if timeline mentions ≥3 distinct time references AND ≥2 services."""
    # Look for time patterns: T+00:XX, HH:MM, "X minutes", "X seconds", timestamps
    time_patterns = re.findall(
        r"T\+\d{2}:\d{2}|"
        r"\d{1,2}:\d{2}(?::\d{2})?|"
        r"\d+ (?:second|minute|hour|sec|min)s?|"
        r"step \d+",
        timeline,
        re.IGNORECASE,
    )
    services = set()
    known_services = [
        "payments-api", "payments", "inventory-service", "inventory",
        "order-worker", "notification-service", "notification",
        "checkout-frontend", "frontend", "redis", "postgres", "kafka",
    ]
    tl_lower = timeline.lower()
    for svc in known_services:
        if svc in tl_lower:
            services.add(svc)

    if len(time_patterns) >= 3 and len(services) >= 2:
        return 0.1
    return 0.0


def score_mitigations(mitigations: str, task_id: str) -> float:
    """Task-specific keyword scoring. Returns up to 0.1."""
    m_lower = mitigations.lower()

    if task_id == "task1":
        keywords = ["chaos", "delete", "remove", "redis", "connection pool", "pool size"]
        if sum(1 for k in keywords if k in m_lower) >= 2:
            return 0.1
    elif task_id == "task2":
        keywords = ["rollback", "memory", "oom", "payments", "resource limit"]
        if sum(1 for k in keywords if k in m_lower) >= 2:
            return 0.1
    elif task_id == "task3":
        # REQUIRES mention of data audit
        if "data audit" in m_lower or "transaction audit" in m_lower:
            keywords = ["rollback", "decimal", "numeric", "v2.3.2", "truncat"]
            if sum(1 for k in keywords if k in m_lower) >= 1:
                return 0.1
    return 0.0


_ST_MODEL = None


def score_writing_quality(text: str, reference: str) -> float:
    """Cosine similarity using sentence-transformers.

    Returns 0.1 if sim > 0.6, 0.05 if sim > 0.4, else 0.0.
    Falls back to keyword overlap if sentence-transformers unavailable.
    """
    global _ST_MODEL
    try:
        from sentence_transformers import SentenceTransformer, util

        if _ST_MODEL is None:
            _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        emb_a = _ST_MODEL.encode(text, convert_to_tensor=True)
        emb_b = _ST_MODEL.encode(reference, convert_to_tensor=True)
        sim = float(util.cos_sim(emb_a, emb_b)[0][0])
    except ImportError:
        # Fallback: simple word-overlap Jaccard similarity
        words_a = set(_normalize(text).split())
        words_b = set(_normalize(reference).split())
        if not words_a or not words_b:
            return 0.0
        sim = len(words_a & words_b) / len(words_a | words_b)

    if sim > 0.6:
        return 0.1
    if sim > 0.4:
        return 0.05
    return 0.0


def grade_postmortem(
    submitted: dict[str, Any],
    ground_truth_root_cause: str,
    task_id: str,
    reference_postmortem: str,
) -> dict[str, float]:
    """Grade a full postmortem submission.

    Returns a dict with component scores and total.
    """
    rc = score_root_cause(submitted.get("root_cause", ""), ground_truth_root_cause)
    tl = score_timeline(submitted.get("timeline", ""))
    mt = score_mitigations(submitted.get("mitigations", ""), task_id)

    full_text = " ".join(str(v) for v in submitted.values())
    wq = score_writing_quality(full_text, reference_postmortem)

    return {
        "root_cause_score": rc,
        "timeline_score": tl,
        "mitigations_score": mt,
        "writing_quality_score": wq,
        "total": rc + tl + mt + wq,
    }
