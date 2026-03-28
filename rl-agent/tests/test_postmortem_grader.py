"""Tests for the postmortem grader."""

import pytest

from environment.graders.postmortem_grader import (
    grade_postmortem,
    score_root_cause,
    score_timeline,
    score_mitigations,
)


class TestRootCauseScoring:
    def test_exact_match(self):
        score = score_root_cause(
            "Redis connection pool exhaustion due to network latency",
            "Redis connection pool exhaustion",
        )
        assert score >= 0.25  # High similarity

    def test_partial_match(self):
        score = score_root_cause(
            "Redis connection issue",
            "Redis connection pool exhaustion due to network latency injection",
        )
        assert score > 0

    def test_no_match(self):
        score = score_root_cause(
            "Database schema migration failure",
            "Redis connection pool exhaustion",
        )
        assert score < 0.15


class TestTimelineScoring:
    def test_good_timeline(self):
        timeline = (
            "t=0: Network latency injected to Redis\n"
            "t=2m: Pool utilization hit 100%\n"
            "t=3m: Inventory-service 5xx spike\n"
            "t=5m: Chaos experiment deleted\n"
            "t=8m: Pool recovered"
        )
        score = score_timeline(timeline)
        assert score >= 0.05

    def test_empty_timeline(self):
        score = score_timeline("")
        assert score == 0.0

    def test_minimal_timeline(self):
        score = score_timeline("Something happened")
        assert score >= 0.0


class TestMitigationScoring:
    def test_correct_mitigation_task1(self):
        score = score_mitigations(
            "Deleted the redis-latency-injection chaos experiment to remove latency",
            "task1",
        )
        assert score >= 0.05

    def test_wrong_mitigation(self):
        score = score_mitigations(
            "Rebooted the database server",
            "task1",
        )
        assert score < 0.1


class TestGradePostmortem:
    def test_full_postmortem(self):
        postmortem = {
            "root_cause": "Redis connection pool exhaustion caused by 500ms network latency",
            "timeline": "t=0: Chaos injected\nt=2m: Alerts fired\nt=5m: Mitigated",
            "mitigations": "Deleted redis-latency-injection chaos experiment",
            "affected_services": ["inventory-service", "order-worker"],
            "recommended_followups": "Add circuit breaker, increase pool timeout",
        }
        scores = grade_postmortem(
            submitted=postmortem,
            ground_truth_root_cause="Redis connection pool exhaustion",
            task_id="task1",
        )
        assert "total" in scores
        assert scores["total"] >= 0
        assert scores["total"] <= 1.0

    def test_empty_postmortem(self):
        postmortem = {
            "root_cause": "",
            "timeline": "",
            "mitigations": "",
        }
        scores = grade_postmortem(
            submitted=postmortem,
            ground_truth_root_cause="Redis connection pool exhaustion",
            task_id="task1",
        )
        assert scores["total"] == pytest.approx(0.0, abs=0.05)
