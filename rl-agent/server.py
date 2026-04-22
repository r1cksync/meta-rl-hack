"""OpenEnv HTTP Server — exposes step/reset/state as a FastAPI app.

This is the entry point for the Hugging Face Space deployment.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from environment.env import IncidentCommanderEnv
from environment.models import Action, ActionType, Observation, StepResult
from environment.curriculum import (
    CurriculumController,
    EpisodeOutcome,
    TIERS,
    TIER_TASKS,
)
from environment.adversarial_designer import AdversarialDesigner, DesignRequest


# ---------------------------------------------------------------------------
# Task metadata (loaded once)
# ---------------------------------------------------------------------------
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
TASK_METADATA = [
    {"id": "task1", "name": "Redis Connection Pool Exhaustion", "difficulty": "easy", "target_score": 0.80,
     "description": "Network latency injection between inventory-service and Redis causes connection pool exhaustion. Agent must identify and remove the Chaos Mesh experiment."},
    {"id": "task2", "name": "Cascading Failure via Payments OOM", "difficulty": "medium", "target_score": 0.45,
     "description": "Memory stress on payments-api causes OOM kills, cascading to Kafka consumer lag. Root cause is payments-api, not inventory-service."},
    {"id": "task3", "name": "Silent Decimal Corruption", "difficulty": "hard", "target_score": 0.20,
     "description": "Bad deployment (v2.3.2) silently truncates order totals. Postgres VACUUM ANALYZE is a red herring."},
    {"id": "task4", "name": "Kafka Broker Network Partition", "difficulty": "easy", "target_score": 0.80,
     "description": "Network partition isolates Kafka broker, causing consumer lag across order-worker and notification-service."},
    {"id": "task5", "name": "DNS Resolution Failure", "difficulty": "medium", "target_score": 0.45,
     "description": "DNS chaos injection causes NXDOMAIN errors across services. Connection refused errors are secondary symptoms."},
    {"id": "task6", "name": "TLS Certificate Expiry Cascade", "difficulty": "hard", "target_score": 0.20,
     "description": "Expired mTLS certificate breaks payments-api to postgres connection. ECONNRESET and upstream timeouts are symptoms."},
    {"id": "task7", "name": "ConfigMap Hot-Reload Race Condition", "difficulty": "hard", "target_score": 0.20,
     "description": "ConfigMap update triggers race condition — some pods load new config, others retain stale values. Redis and GC alerts are red herrings."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    mock_val = os.getenv("MOCK_MODE", os.getenv("INCIDENT_COMMANDER_MOCK", "true"))
    app.state.env = IncidentCommanderEnv(use_mock=mock_val.lower() == "true")
    app.state.curriculum = CurriculumController(seed=42)
    app.state.designer = AdversarialDesigner(base_scenarios_dir=SCENARIOS_DIR)
    app.state.last_adversarial_scenario = None
    yield


app = FastAPI(
    title="IncidentCommander — OpenEnv",
    description="SRE incident response RL environment where AI agents learn to diagnose and mitigate production incidents on a live e-commerce platform.",
    version="1.0.0",
    lifespan=lifespan,
)


class ResetRequest(BaseModel):
    task_id: str = "task1"
    # New: advanced reset options
    adversarial: bool = False               # ask designer for a novel scenario
    use_curriculum: bool = False            # auto-pick task from curriculum tier
    persona: Optional[str] = None           # junior | senior | principal
    use_llm_judge: Optional[bool] = None    # override USE_LLM_JUDGE env var


class StepRequest(BaseModel):
    action_type: str
    params: dict = {}


@app.post("/reset")
def reset(req: Optional[ResetRequest] = Body(default=None)) -> dict:
    env: IncidentCommanderEnv = app.state.env
    curriculum: CurriculumController = app.state.curriculum
    designer: AdversarialDesigner = app.state.designer
    req = req or ResetRequest()

    # Optionally override persona / judge mode for this episode.
    if req.persona in ("junior", "senior", "principal"):
        env._judge_persona = req.persona
    if req.use_llm_judge is not None:
        env._use_llm_judge = bool(req.use_llm_judge)

    scenario_override = None
    task_id = req.task_id

    if req.use_curriculum:
        pick = curriculum.sample_task()
        task_id = pick["task_id"]
        if pick["adversarial"] or req.adversarial:
            scenario_override = designer.design(DesignRequest(
                primary_task_id=task_id,
                companion_task_ids=pick["companion_task_ids"],
                mastery=curriculum.state.per_task_mastery,
                use_llm=True,
            ))
        elif pick["multi_fault"] and pick["companion_task_ids"]:
            scenario_override = designer.compose_multi_fault(
                [task_id, *pick["companion_task_ids"]]
            )
    elif req.adversarial:
        scenario_override = designer.design(DesignRequest(
            primary_task_id=task_id,
            companion_task_ids=[],
            mastery=curriculum.state.per_task_mastery,
            use_llm=True,
        ))

    app.state.last_adversarial_scenario = (
        scenario_override.model_dump() if scenario_override is not None else None
    )

    try:
        obs = env.reset(task_id, scenario=scenario_override)
        return obs.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/step")
def step(req: Optional[StepRequest] = Body(default=None)) -> dict:
    env: IncidentCommanderEnv = app.state.env
    if req is None:
        raise HTTPException(status_code=400, detail="action_type is required")
    try:
        action = Action(type=ActionType(req.action_type), params=req.params)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid action type: {req.action_type}")
    try:
        result = env.step(action)
        return result.model_dump(mode="json")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/state")
def state() -> dict:
    env: IncidentCommanderEnv = app.state.env
    return env.state()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {
        "name": "incident-commander",
        "version": "2.0.0",
        "tasks": len(TASK_METADATA),
        "curriculum_tiers": TIERS,
        "features": [
            "7 hand-authored tasks + unlimited adversarial scenarios",
            "Context-gated rewards (acting-blind, red-herring, repeat-cmd)",
            "Phase-aware rewards (triage -> investigate -> fix -> verify)",
            "3-persona LLM judge (junior / senior / principal)",
            "Curriculum controller with per-fault mastery tracking",
            "Adversarial scenario designer (LLM + procedural fallback)",
            "Holistic episode grading",
            "Live Plotly.js dashboard",
            "Optional real Kubernetes backend (REAL_K8S=true)",
            "GRPO training pipeline (TRL + vLLM)",
        ],
        "endpoints": [
            "/reset", "/step", "/state", "/health", "/tasks", "/grader", "/baseline",
            "/dashboard", "/curriculum", "/curriculum/reset", "/adversarial/design",
            "/judge/config", "/docs",
        ],
    }


# ---------------------------------------------------------------------------
# New endpoints: /tasks, /grader, /baseline, /dashboard
# ---------------------------------------------------------------------------

@app.get("/tasks")
def tasks() -> list[dict]:
    """Return metadata for all available tasks with action schema."""
    action_schema = {
        "read_actions": ["query_logs", "query_metrics", "get_service_dependencies", "get_trace"],
        "write_actions": ["rollback_deployment", "restart_pods", "scale_deployment", "apply_config_patch", "delete_chaos_experiment"],
        "terminal_actions": ["submit_postmortem"],
    }
    return [
        {**t, "action_schema": action_schema}
        for t in TASK_METADATA
    ]


class GraderRequest(BaseModel):
    task_id: str | None = None


@app.post("/grader")
def grader(req: Optional[GraderRequest] = Body(default=None)) -> dict:
    """Grade the last completed episode holistically. Returns scores in [0.001, 0.999].

    Also records the outcome to the curriculum controller so the next `/reset`
    call with `use_curriculum=true` can pick a harder or easier task.
    """
    env: IncidentCommanderEnv = app.state.env
    curriculum: CurriculumController = app.state.curriculum
    scores = env.grade_episode()

    # Record to curriculum if we have a finished episode with a task.
    task = env._task
    if task is not None and env._done and "total" in scores:
        try:
            outcome = EpisodeOutcome(
                task_id=task.task_id,
                score=float(scores["total"]),
                target_score=float(task.target_score or 0.5),
                steps=env._step_count,
                mitigation_applied=env._mitigation_applied,
                root_cause_correct=env._root_cause_identified,
                tier=curriculum.state.tier,
            )
            promo = curriculum.record_episode(outcome)
            scores["curriculum"] = {
                "tier": promo["tier"],
                "promoted": promo["promoted"],
                "episodes_in_tier": promo["episodes_in_tier"],
                "total_episodes": promo["total_episodes"],
            }
        except Exception:
            pass
    return scores


class BaselineRequest(BaseModel):
    task_id: str = "task1"


@app.post("/baseline")
def run_baseline(req: Optional[BaselineRequest] = Body(default=None)) -> dict:
    """Run the heuristic baseline agent on a task and return the full episode trace."""
    env: IncidentCommanderEnv = app.state.env
    task_id = req.task_id if req else "task1"
    return _run_heuristic_episode(env, task_id)


def _run_heuristic_episode(env: IncidentCommanderEnv, task_id: str) -> dict:
    """Execute the built-in heuristic agent and return episode data for the dashboard."""
    from environment.models import Action, ActionType

    # Heuristic strategies per task
    STRATEGIES = {
        "task1": [
            ("query_logs", {"service": "inventory-service", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "inventory-service"}),
            ("query_metrics", {"promql": "redis_connections_active"}),
            ("delete_chaos_experiment", {"experiment_name": "redis-latency-inject"}),
            ("submit_postmortem", {
                "root_cause": "redis_connection_pool_exhaustion",
                "timeline": "T+00:00 RedisConnectionPoolSaturation alert fired. T+00:01 Investigated inventory-service logs. T+00:02 Found connection pool timeout errors. T+00:03 Identified Chaos Mesh experiment. T+00:04 Deleted experiment.",
                "mitigations": "Deleted Chaos Mesh redis-latency-inject experiment. Redis connection pool recovered.",
                "affected_services": ["inventory-service"],
                "recommended_followups": "Increase Redis connection pool size, add circuit breaker around Redis calls.",
            }),
        ],
        "task2": [
            ("query_logs", {"service": "payments-api", "last_minutes": 5}),
            ("query_logs", {"service": "inventory-service", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "payments-api"}),
            ("query_metrics", {"promql": "container_memory_usage_bytes{container='payments-api'}"}),
            ("rollback_deployment", {"deployment": "payments-api"}),
            ("submit_postmortem", {
                "root_cause": "payments_api_oom_memory_leak",
                "timeline": "T+00:00 PaymentsOOMRisk alert fired. T+00:01 Investigated payments-api logs — OOMKilled errors. T+00:02 Checked inventory-service — Kafka consumer lag is secondary. T+00:03 Confirmed payments-api as root cause. T+00:04 Rolled back payments-api. T+00:05 Submitted postmortem.",
                "mitigations": "Rolled back payments-api deployment. Kafka consumer lag resolved automatically.",
                "affected_services": ["payments-api", "inventory-service", "order-worker"],
                "recommended_followups": "Set memory resource limits, implement OOM kill alerting, review Kafka consumer acknowledgment resilience.",
            }),
        ],
        "task3": [
            ("query_logs", {"service": "payments-api", "last_minutes": 5}),
            ("query_logs", {"service": "postgres", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "payments-api"}),
            ("query_metrics", {"promql": "pg_stat_user_tables_n_tup_ins{table='orders'}"}),
            ("rollback_deployment", {"deployment": "payments-api"}),
            ("submit_postmortem", {
                "root_cause": "payments_decimal_serialization_bug_v2_3_2",
                "timeline": "T+00:00 Investigated payments-api logs — found NUMERIC(12,2) truncation. T+00:01 Postgres VACUUM ANALYZE is a red herring. T+00:02 Identified v2.3.2 as the bad deployment. T+00:03 Rolled back. T+00:04 Submitted postmortem.",
                "mitigations": "Rolled back payments-api to v2.3.0. Data audit of orders is needed.",
                "affected_services": ["payments-api"],
                "recommended_followups": "Conduct full data audit of all orders between v2.3.2 deployment and rollback. Implement schema validation tests in CI/CD.",
            }),
        ],
        "task4": [
            ("query_logs", {"service": "order-worker", "last_minutes": 5}),
            ("query_logs", {"service": "notification-service", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "order-worker"}),
            ("delete_chaos_experiment", {"experiment_name": "kafka-network-partition"}),
            ("submit_postmortem", {
                "root_cause": "kafka_broker_network_partition",
                "timeline": "T+00:00 KafkaConsumerLagCritical alert on order-worker. T+00:01 Investigated logs — broker disconnect. T+00:02 Found NetworkPartition errors. T+00:03 Deleted Chaos Mesh experiment.",
                "mitigations": "Deleted kafka-network-partition Chaos Mesh experiment. Consumer lag resolved.",
                "affected_services": ["order-worker", "notification-service"],
                "recommended_followups": "Implement Kafka consumer lag alerting, add multi-broker redundancy.",
            }),
        ],
        "task5": [
            ("query_logs", {"service": "checkout-frontend", "last_minutes": 5}),
            ("query_logs", {"service": "payments-api", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "checkout-frontend"}),
            ("query_metrics", {"promql": "coredns_dns_request_count_total"}),
            ("delete_chaos_experiment", {"experiment_name": "dns-resolution-delay"}),
            ("submit_postmortem", {
                "root_cause": "dns_resolution_failure_service_discovery",
                "timeline": "T+00:00 FrontendErrorRate alert — 502 errors. T+00:01 Found DNS NXDOMAIN in logs. T+00:02 Confirmed service discovery failure. T+00:03 Deleted DNS chaos experiment.",
                "mitigations": "Deleted dns-resolution-delay experiment. DNS resolution restored.",
                "affected_services": ["checkout-frontend", "payments-api", "inventory-service"],
                "recommended_followups": "Add DNS resolution monitoring, implement service mesh sidecar, add retry with exponential backoff on DNS failures.",
            }),
        ],
        "task6": [
            ("query_logs", {"service": "payments-api", "last_minutes": 5}),
            ("query_logs", {"service": "checkout-frontend", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "payments-api"}),
            ("query_metrics", {"promql": "tls_certificate_expiry_seconds"}),
            ("apply_config_patch", {"deployment": "payments-api", "env_var": "TLS_CERT_PATH", "value": "/etc/ssl/certs/mtls-cert-renewed.pem"}),
            ("submit_postmortem", {
                "root_cause": "tls_certificate_expired_mutual_auth",
                "timeline": "T+00:00 PostgresConnectionErrors alert. T+00:01 Found x509 expired cert errors. T+00:02 ECONNRESET and upstream timeouts are symptoms. T+00:03 Patched TLS cert path.",
                "mitigations": "Rotated TLS certificate via config patch. Database connections restored.",
                "affected_services": ["payments-api", "checkout-frontend"],
                "recommended_followups": "Implement automated cert rotation with cert-manager, add 30-day advance cert expiry alerting.",
            }),
        ],
        "task7": [
            ("query_logs", {"service": "inventory-service", "last_minutes": 5}),
            ("get_service_dependencies", {"service": "inventory-service"}),
            ("query_metrics", {"promql": "inventory_price_inconsistency_total"}),
            ("restart_pods", {"deployment": "inventory-service"}),
            ("submit_postmortem", {
                "root_cause": "config_hot_reload_race_condition",
                "timeline": "T+00:00 PricingInconsistency alert. T+00:01 Found config hot-reload race — pods have different config. T+00:02 Redis and GC alerts are red herrings. T+00:03 Restarted pods for consistent config.",
                "mitigations": "Restarted inventory-service pods. All pods now have consistent config.",
                "affected_services": ["inventory-service"],
                "recommended_followups": "Implement config version checksums, switch to immutable ConfigMaps with rolling deployments.",
            }),
        ],
    }

    strategy = STRATEGIES.get(task_id, STRATEGIES["task1"])
    obs = env.reset(task_id)

    steps_list = [0]
    blast_history = [obs.blast_radius_pct]
    rewards = []
    cumulative_rewards = [0.0]
    action_labels = ["reset"]
    cumulative = 0.0
    final_obs = obs

    for action_name, params in strategy:
        action = Action(type=ActionType(action_name), params=params)
        result = env.step(action)
        reward = result.reward
        cumulative += reward

        steps_list.append(len(rewards) + 1)
        blast_history.append(result.observation.blast_radius_pct)
        rewards.append(round(reward, 4))
        cumulative_rewards.append(round(cumulative, 4))
        action_labels.append(action_name.replace("_", " "))
        final_obs = result.observation

        if result.done:
            break

    # Grade the episode
    grade = env.grade_episode()
    final_state = env.state()

    return {
        "task_id": task_id,
        "steps": steps_list,
        "blast_history": blast_history,
        "rewards": rewards,
        "cumulative_rewards": cumulative_rewards,
        "action_labels": action_labels,
        "score": grade.get("total", 0.001),
        "grade": grade,
        "final_state": final_state,
        "final_obs": final_obs.model_dump(mode="json") if hasattr(final_obs, "model_dump") else {},
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Serve the live diagnostic dashboard."""
    html_path = Path(__file__).resolve().parent / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)


# ---------------------------------------------------------------------------
# Curriculum, adversarial, judge — new endpoints inspired by kube-sre-gym
# ---------------------------------------------------------------------------


@app.get("/curriculum")
def curriculum_state() -> dict:
    """Return the current curriculum snapshot.

    Shows tier, mastery per task, rolling success rate, and whether the
    next reset with `use_curriculum=true` will enable adversarial/multi-fault.
    """
    return app.state.curriculum.snapshot()


class CurriculumResetRequest(BaseModel):
    tier: Optional[str] = None


@app.post("/curriculum/reset")
def curriculum_reset(req: Optional[CurriculumResetRequest] = Body(default=None)) -> dict:
    """Reset the curriculum (or jump to a specific tier)."""
    curriculum: CurriculumController = app.state.curriculum
    if req and req.tier:
        try:
            curriculum.force_tier(req.tier)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        curriculum.reset()
    return curriculum.snapshot()


class AdversarialRequest(BaseModel):
    primary_task_id: str = "task1"
    companion_task_ids: list[str] = []
    use_llm: bool = True


@app.post("/adversarial/design")
def adversarial_design(req: Optional[AdversarialRequest] = Body(default=None)) -> dict:
    """Design a novel adversarial scenario (LLM if key present, else procedural).

    Useful for inspecting what the designer produces without starting an episode.
    """
    designer: AdversarialDesigner = app.state.designer
    curriculum: CurriculumController = app.state.curriculum
    req = req or AdversarialRequest()
    try:
        scenario = designer.design(DesignRequest(
            primary_task_id=req.primary_task_id,
            companion_task_ids=req.companion_task_ids,
            mastery=curriculum.state.per_task_mastery,
            use_llm=req.use_llm,
        ))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return scenario.model_dump()


class JudgeConfigRequest(BaseModel):
    persona: Optional[str] = None            # junior | senior | principal
    use_llm: Optional[bool] = None


@app.post("/judge/config")
def judge_config(req: Optional[JudgeConfigRequest] = Body(default=None)) -> dict:
    """Configure the per-step judge for subsequent episodes.

    Sets persona (junior/senior/principal) and whether to call the LLM or use
    the heuristic fallback. State persists across resets until changed again.
    """
    env: IncidentCommanderEnv = app.state.env
    req = req or JudgeConfigRequest()
    if req.persona:
        if req.persona not in ("junior", "senior", "principal"):
            raise HTTPException(status_code=400, detail="persona must be junior|senior|principal")
        env._judge_persona = req.persona
    if req.use_llm is not None:
        env._use_llm_judge = bool(req.use_llm)
    return {
        "persona": env._judge_persona,
        "use_llm_judge": env._use_llm_judge,
        "has_api_key": bool(
            os.getenv("OPENAI_API_KEY") or os.getenv("HF_TOKEN")
        ),
    }
