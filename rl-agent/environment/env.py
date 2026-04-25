"""IncidentCommanderEnv — OpenEnv-compatible SRE incident response environment.

The agent plays an on-call SRE at AcmeCorp. Every observation contains REAL
data from Prometheus + Loki + Alertmanager. Every write action executes REAL
kubectl/helm commands against the cluster. The reward signal is computed from
REAL Prometheus error-rate metrics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx  # used by _action_get_trace

from .adversarial_designer import AdversarialDesigner, DesignRequest
from .chaos_client import ChaosMeshClient
from .graders.blast_radius_tracker import BlastRadiusTracker
from .graders.postmortem_grader import grade_postmortem
from .k8s_backend import K8sBackend
from .llm_judge import LLMJudge, action_signature, phase_order_bonus
from .loki_client import LokiClient
from .models import (
    Action,
    ActionType,
    Alert,
    HealthStatus,
    LogLine,
    Observation,
    READ_ACTIONS,
    SERVICE_DEPENDENCIES,
    ServiceStatus,
    StepResult,
    TaskScenario,
    TimePressure,
    WRITE_ACTIONS,
)
from .prometheus_client import PrometheusClient

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
SCENARIOS_SIM_DIR = SCENARIOS_DIR / "sim"

TASK_FILE_MAP = {
    "task1": "easy_redis_exhaustion.json",
    "task2": "medium_payments_oom.json",
    "task3": "hard_decimal_corruption.json",
    "task4": "easy_kafka_consumer_lag.json",
    "task5": "medium_dns_resolution.json",
    "task6": "hard_tls_cert_expiry.json",
    "task7": "hard_config_race_condition.json",
    "task8": "medium_jwt_secret_rotation.json",
    "task9": "easy_image_pull_backoff.json",
    "task10": "medium_resource_quota.json",
    "task11": "hard_liveness_probe_regression.json",
    # AWS-themed extension tasks (task12–task20).
    "task12": "medium_sqs_dlq_growth.json",
    "task13": "hard_dynamodb_throttle.json",
    "task14": "medium_secrets_manager_rotation.json",
    "task15": "hard_s3_iam_drift.json",
    "task16": "easy_lambda_cold_start.json",
    "task17": "medium_rds_connection_pool.json",
    "task18": "hard_bedrock_throttling.json",
    "task19": "easy_cloudwatch_alarm_storm.json",
    "task20": "hard_eventbridge_silent_drop.json",
    "task21": "hard_step_functions_failure.json",
    "task22": "medium_athena_failed_query.json",
    "task23": "hard_kms_key_drift.json",
}

# Ground truth for reward computation
CORRECT_SERVICES = {
    "task1": None,  # correct action is delete_chaos_experiment, not a deploy target
    "task2": "payments-api",
    "task3": "payments-api",
    "task4": None,  # correct action is delete_chaos_experiment
    "task5": None,  # correct action is delete_chaos_experiment
    "task6": "payments-api",
    "task7": "inventory-service",
    "task8": "auth-service",
    "task9": "checkout-frontend",
    "task10": "payments-worker",
    "task11": "inventory-service",
    # New AWS-themed tasks.
    "task12": "order-worker",
    "task13": "inventory-service",
    "task14": "payments-api",
    "task15": "inventory-service",
    "task16": None,  # delete_chaos_experiment
    "task17": "payments-api",
    "task18": "notification-service",
    "task19": None,  # delete_chaos_experiment
    "task20": "order-worker",
    "task21": "order-worker",
    "task22": "inventory-service",
    "task23": "payments-api",
}

# Per-task AWS service hints — used by aws_evidence_used and security/cost
# reward signals. Each key lists the AWS terms that a *correct* postmortem
# would mention. Empty list = task is not AWS-flavoured.
TASK_AWS_HINTS: dict[str, list[str]] = {
    "task1":  [],
    "task2":  [],
    "task3":  [],
    "task4":  [],
    "task5":  [],
    "task6":  [],
    "task7":  [],
    "task8":  [],
    "task9":  ["ECR", "ImagePullSecret"],
    "task10": [],
    "task11": [],
    "task12": ["SQS", "DLQ", "CloudWatch", "IAM"],
    "task13": ["DynamoDB", "RCU", "WCU", "CloudWatch", "auto-scaling"],
    "task14": ["Secrets Manager", "RotationLambda", "EventBridge", "IAM"],
    "task15": ["S3", "IAM", "AssumeRole", "IRSA", "CloudTrail"],
    "task16": ["Lambda", "Provisioned Concurrency", "CloudWatch"],
    "task17": ["RDS", "PgBouncer", "DatabaseConnections", "IAM"],
    "task18": ["Bedrock", "InvokeModel", "Throttling", "quota", "CloudWatch"],
    "task19": ["CloudWatch", "SNS", "PagerDuty", "PutMetricAlarm"],
    "task20": ["EventBridge", "PutEvents", "DLQ", "IAM", "CloudWatch"],
    "task21": ["Step Functions", "StateMachine", "X-Ray", "IAM", "SNS", "CloudWatch"],
    "task22": ["Athena", "Glue", "S3", "IAM", "CloudWatch"],
    "task23": ["KMS", "CloudTrail", "IAM", "IRSA", "SCP", "Decrypt"],
}

ALL_AVAILABLE_ACTIONS = [a.value for a in ActionType]


class IncidentCommanderEnv:
    """OpenEnv-compatible environment for SRE incident response."""

    def __init__(
        self,
        prometheus_url: str | None = None,
        loki_url: str | None = None,
        alertmanager_url: str | None = None,
        chaos_url: str | None = None,
        use_mock: bool | None = None,
    ):
        self._prom = PrometheusClient(
            prometheus_url=prometheus_url or os.getenv("PROMETHEUS_URL", "http://localhost:9090"),
            alertmanager_url=alertmanager_url or os.getenv("ALERTMANAGER_URL", "http://localhost:9093"),
        )
        self._loki = LokiClient(
            loki_url=loki_url or os.getenv("LOKI_URL", "http://localhost:3100"),
        )
        self._chaos = ChaosMeshClient(
            chaos_url=chaos_url or os.getenv("CHAOS_API_URL", "http://localhost:2333"),
        )

        # Detect if we're in local (docker-compose) mode or k8s mode
        if use_mock is not None:
            self._mock = use_mock
        else:
            self._mock = os.getenv("INCIDENT_COMMANDER_MOCK", "false").lower() == "true"

        # Kubernetes client (lazy init)
        self._k8s_apps = None
        self._k8s_core = None

        # Episode state
        self._task: TaskScenario | None = None
        self._step_count: int = 0
        self._done: bool = False
        self._blast_tracker = BlastRadiusTracker()
        self._action_history: list[dict[str, Any]] = []
        self._root_cause_identified: bool = False
        self._mitigation_applied: bool = False
        self._cumulative_reward: float = 0.0
        # Investigation tracking (for context-gated rewards)
        self._inspected_logs: set[str] = set()        # services whose logs were queried
        self._inspected_metrics: bool = False
        self._inspected_deps: set[str] = set()        # services whose deps were queried
        self._inspected_traces: bool = False
        # Holistic grading state
        self._last_reward_breakdown: dict[str, float] = {}
        self._last_action_correct: bool = False
        self._episode_scores: dict[str, float] = {}

        # Phase tracking (triage / investigate / fix / verify) + repeat-cmd
        self._current_phase: str | None = None
        self._phase_history: list[str] = []
        self._seen_action_signatures: dict[str, int] = {}
        self._last_judge_result: dict[str, Any] | None = None

        # Simulator state — only populated when reset() is called with a
        # `sim_*` task id. Live AWS code paths remain available behind the
        # IC_USE_LIVE_AWS env flag but the simulator is the default.
        self._sim_active: bool = False
        self._sim_state = None
        self._sim_scenario: dict | None = None

        # Optional companions (k8s backend, LLM judge, adversarial designer)
        self._k8s_backend = K8sBackend()
        self._judge = LLMJudge()
        self._designer = AdversarialDesigner(base_scenarios_dir=SCENARIOS_DIR)
        self._judge_persona = os.getenv("JUDGE_PERSONA", "senior")
        self._use_llm_judge = os.getenv("USE_LLM_JUDGE", "false").lower() in ("1", "true", "yes")

        # Optional AWS — CloudWatch Logs reader. Disabled unless env vars set.
        try:
            from .aws_integrations import CloudWatchLogsReader
            self._cw_logs = CloudWatchLogsReader()
        except Exception:
            self._cw_logs = None

    # ------------------------------------------------------------------
    # OpenEnv API
    # ------------------------------------------------------------------

    def _run_async(self, coro):
        """Run an async coroutine, creating a new event loop if needed."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError
            return loop.run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

    def reset(self, task_id: str, scenario: TaskScenario | None = None) -> Observation:
        """Reset the environment for a new episode.

        If `scenario` is given it overrides the JSON-backed scenario — used for
        adversarial/multi-fault tasks produced by the AdversarialDesigner.
        """
        if self._mock:
            return self._sync_reset(task_id, scenario=scenario)
        return self._run_async(self._async_reset(task_id))

    def step(self, action: Action) -> StepResult:
        """Execute one action and return result."""
        if self._mock:
            return self._sync_step(action)
        return self._run_async(self._async_step(action))

    def _sync_reset(self, task_id: str, scenario: TaskScenario | None = None) -> Observation:
        """Fast synchronous reset for mock mode."""
        if scenario is not None:
            self._task = scenario
            self._sim_active = False
        else:
            filename = TASK_FILE_MAP.get(task_id)
            if not filename:
                # Sim scenario? task_id is the file stem under scenarios/sim/<difficulty>/.
                sim_path = self._find_sim_scenario(task_id)
                if sim_path is None:
                    raise ValueError(f"Unknown task_id: {task_id}. Must be one of {list(TASK_FILE_MAP.keys())} "
                                     f"or a simulator scenario id (sim_*).")
                self._init_simulator(sim_path)
                # Build a minimal TaskScenario shell so downstream reward
                # plumbing has something to consult.
                self._task = self._task_from_sim(sim_path)
            else:
                scenario_path = SCENARIOS_DIR / filename
                with open(scenario_path) as f:
                    self._task = TaskScenario(**json.load(f))
                self._sim_active = False
        self._step_count = 0
        self._done = False
        self._blast_tracker.reset()
        self._action_history = []
        self._root_cause_identified = False
        self._mitigation_applied = False
        self._cumulative_reward = 0.0
        self._inspected_logs = set()
        self._inspected_metrics = False
        self._inspected_deps = set()
        self._inspected_traces = False
        # Sim-mode reward bookkeeping (one-shot credits per episode).
        self._seen_sim_inspects: set[str]      = set()
        self._sim_mitigation_credited: bool    = False
        self._seen_blast: int                  = 0
        self._sim_trap_credited: bool          = False
        self._sim_trolley_credited: bool       = False
        self._seen_k8s_kicks: int              = 0
        self._aws_inspected: set[str]          = set()
        self._aws_remediated: set[str]         = set()
        self._last_reward_breakdown = {}
        self._last_action_correct = False
        self._episode_scores = {}
        self._current_phase = None
        self._phase_history = []
        self._seen_action_signatures = {}
        self._last_judge_result = None
        self._useful_log_query_count = 0
        # AWS-flavoured action tracking
        self._aws_inspected = set()
        self._aws_remediated = set()
        # Simulator state is owned by _init_simulator() when applicable; clear
        # it here for non-sim resets so a previous sim run doesn't leak.
        if not getattr(self, "_sim_active", False):
            self._sim_state = None
            self._sim_scenario = None
        return self._build_mock_observation()

    # ------------------------------------------------------------------
    # Simulator integration
    # ------------------------------------------------------------------
    def _find_sim_scenario(self, task_id: str) -> Path | None:
        """Locate a sim scenario by id (filename stem) under scenarios/sim/."""
        if not SCENARIOS_SIM_DIR.exists():
            return None
        for p in SCENARIOS_SIM_DIR.rglob(f"{task_id}.json"):
            return p
        return None

    def _init_simulator(self, scenario_path: Path) -> None:
        """Spin up a fresh SimState and load the scenario."""
        # Local import: keeps the simulator package optional.
        from simulator import SimState, load_scenario
        self._sim_state = SimState()
        self._sim_scenario = load_scenario(scenario_path, self._sim_state)
        self._sim_active = True

    def _task_from_sim(self, scenario_path: Path) -> TaskScenario:
        """Synthesise a TaskScenario shell from a sim scenario JSON.

        The shell is just enough for the reward & observation builders to run;
        actual work happens via the simulator.
        """
        scn = json.loads(scenario_path.read_text(encoding="utf-8"))
        difficulty_str = scn.get("difficulty", "medium")
        # TaskScenario has many required fields; fill them with sim-friendly
        # defaults. These are not consulted by the simulator path, but the
        # reward plumbing reads `difficulty` and `target_score`.
        return TaskScenario(
            task_id=scn["id"],
            difficulty=difficulty_str,
            target_score=scn.get("target_score", 0.55),
            fault_type="simulated",
            ground_truth_root_cause=scn.get("description", scn.get("title", "")),
            correct_mitigation_action="aws_api_call",
            correct_mitigation_target=scn["correct_action_chain"][-1]["id"]
                if scn.get("correct_action_chain") else "",
        )

    def _sync_step(self, action: Action) -> StepResult:
        """Fast synchronous step for mock mode."""
        if self._done:
            raise RuntimeError("Episode is done. Call reset() to start a new episode.")
        if self._task is None:
            raise RuntimeError("No task loaded. Call reset() first.")
        if action.type not in ActionType:
            raise ValueError(f"Invalid action type: {action.type}")

        # Track repeat commands BEFORE executing (so penalty applies this step).
        sig = action_signature(action)
        repeat_count = self._seen_action_signatures.get(sig, 0)
        self._seen_action_signatures[sig] = repeat_count + 1

        action_result = self._sync_execute_action(action)
        obs = self._build_mock_observation(action_result=action_result)
        self._blast_tracker.record(self._step_count, obs.blast_radius_pct, action.type.value)

        # LLM or heuristic judge (phase-aware).
        judge = self._judge.judge(
            action=action,
            action_result=action_result,
            step=self._step_count,
            blast_radius=obs.blast_radius_pct,
            cumulative_reward=self._cumulative_reward,
            inspected_services=len(self._inspected_logs),
            persona=self._judge_persona,  # type: ignore[arg-type]
            use_llm=self._use_llm_judge,
        )
        prev_phase = self._current_phase
        self._current_phase = judge.phase
        self._phase_history.append(judge.phase)
        self._last_judge_result = {
            "persona": judge.persona,
            "phase": judge.phase,
            "score": judge.score,
            "reason": judge.reason,
            "used_llm": judge.used_llm,
        }

        reward = self._compute_reward(
            obs, action, action_result,
            repeat_count=repeat_count,
            judge_score=judge.score,
            prev_phase=prev_phase,  # type: ignore[arg-type]
            next_phase=judge.phase,  # type: ignore[arg-type]
        )
        self._cumulative_reward += reward
        self._action_history.append({
            "step": self._step_count,
            "action_type": action.type.value,
            "params": action.params,
            "reward": reward,
            "phase": judge.phase,
            "repeat_count": repeat_count,
            "judge_score": judge.score,
        })

        # ── Phase 8: replay recording (sim mode only). ──
        if self._sim_active and self._sim_state is not None:
            from .replay import record_step
            record_step(self._sim_state,
                        action={"id": f"{action.type.value}",
                                "params": action.params},
                        action_result=str(action_result),
                        step_reward=reward)

        self._step_count += 1
        done = action.type == ActionType.SUBMIT_POSTMORTEM or self._step_count >= 20
        self._done = done

        # ── Phase 8: dump replay artifact at episode end. ──
        if done and self._sim_active and self._sim_state is not None:
            try:
                self._dump_replay()
            except Exception as exc:                          # noqa: BLE001
                logger.warning("replay dump failed: %s", exc)

        info = {
            "reward_breakdown": self._last_reward_breakdown,
            "action_was_correct": self._last_action_correct,
            "current_blast_radius": obs.blast_radius_pct,
            "cumulative_reward": self._cumulative_reward,
            "phase": judge.phase,
            "judge": self._last_judge_result,
            "repeat_count": repeat_count,
        }
        return StepResult(observation=obs, reward=reward, done=done, info=info)

    def _sync_execute_action(self, action: Action) -> str:
        """Synchronous action execution for mock mode."""
        t = action.type
        p = action.params
        if t == ActionType.QUERY_LOGS:
            svc = p.get("service", "")
            self._inspected_logs.add(svc)
            # Prefer real CloudWatch logs when available.
            cw = getattr(self, "_cw_logs", None)
            if cw is not None and cw.enabled:
                lines = cw.query(svc, last_minutes=int(p.get("last_minutes", 5)))
                if lines:
                    return "\n".join(lines[:50])
            return self._mock_query_logs(svc, p.get("filter_text"))
        elif t == ActionType.QUERY_METRICS:
            self._inspected_metrics = True
            return f"[MOCK] Metrics query result for '{p.get('promql', '')}': value=0.05 (simulated)"
        elif t == ActionType.GET_SERVICE_DEPENDENCIES:
            svc = p.get("service", "")
            self._inspected_deps.add(svc)
            return self._action_get_deps(service=svc)
        elif t == ActionType.GET_TRACE:
            self._inspected_traces = True
            return f"[MOCK] Trace {p.get('trace_id', '')}: checkout-frontend -> payments-api (45ms) -> postgres (12ms)"
        elif t == ActionType.ROLLBACK_DEPLOYMENT:
            deploy = p.get("deployment", "")
            correct = CORRECT_SERVICES.get(self._task.task_id if self._task else "")
            if deploy == correct:
                self._mitigation_applied = True
            result = self._k8s_backend.rollback(deploy)
            return result.message
        elif t == ActionType.RESTART_PODS:
            deploy = p.get("deployment", "")
            correct = CORRECT_SERVICES.get(self._task.task_id if self._task else "")
            if deploy == correct and self._task and self._task.correct_mitigation_action == "restart_pods":
                self._mitigation_applied = True
            result = self._k8s_backend.restart(deploy)
            return result.message
        elif t == ActionType.SCALE_DEPLOYMENT:
            replicas = int(p.get("replicas", 2))
            result = self._k8s_backend.scale(p.get("deployment", ""), replicas)
            return result.message
        elif t == ActionType.APPLY_CONFIG_PATCH:
            deploy = p.get("deployment", "")
            correct = CORRECT_SERVICES.get(self._task.task_id if self._task else "")
            if deploy == correct and self._task and self._task.correct_mitigation_action == "apply_config_patch":
                self._mitigation_applied = True
            result = self._k8s_backend.apply_config_patch(
                deploy, p.get("env_var", ""), p.get("value", "")
            )
            return result.message
        elif t == ActionType.DELETE_CHAOS_EXPERIMENT:
            exp = p.get("experiment_name", "")
            if self._task and self._task.chaos_experiment_name == exp:
                self._mitigation_applied = True
            return f"[MOCK] Deleted Chaos Mesh experiment '{exp}'."
        elif t == ActionType.EXEC_KUBECTL:
            cmd = p.get("command", "").strip()
            if not cmd:
                return "error: EXEC_KUBECTL requires params.command (kubectl-style string)"
            # Track read vs write via simple verb parsing for reward shaping.
            verb = cmd.replace("kubectl ", "", 1).strip().split(" ", 1)[0] if cmd else ""
            if verb in ("set", "scale", "rollout", "patch", "delete", "apply"):
                # Detect whether the agent hit the correct mitigation target.
                if self._task and self._task.correct_mitigation_target \
                        and self._task.correct_mitigation_target in cmd:
                    self._mitigation_applied = True
            return self._k8s_backend.execute(cmd)
        elif t == ActionType.SUBMIT_POSTMORTEM:
            return self._action_submit_postmortem(
                root_cause=p.get("root_cause", ""),
                timeline=p.get("timeline", ""),
                mitigations=p.get("mitigations", ""),
                affected_services=p.get("affected_services", []),
                recommended_followups=p.get("recommended_followups", ""),
            )
        # ---- AWS-flavoured non-obvious actions (sync = same impl) ----
        aws_result = self._dispatch_aws_action(action)
        if aws_result is not None:
            return aws_result
        return f"Unknown action type: {t}"

    def state(self) -> dict[str, Any]:
        """Return current environment state."""
        return {
            "task_id": self._task.task_id if self._task else None,
            "step_count": self._step_count,
            "done": self._done,
            "cumulative_reward": self._cumulative_reward,
            "blast_radius_pct": self._blast_tracker.latest,
            "action_history": self._action_history,
            "root_cause_identified": self._root_cause_identified,
            "mitigation_applied": self._mitigation_applied,
            "investigation": {
                "logs_inspected": sorted(self._inspected_logs),
                "metrics_inspected": self._inspected_metrics,
                "deps_inspected": sorted(self._inspected_deps),
                "traces_inspected": self._inspected_traces,
            },
            "last_reward_breakdown": self._last_reward_breakdown,
            "phase": self._current_phase,
            "phase_history": list(self._phase_history),
            "last_judge": self._last_judge_result,
            "repeat_signatures": {
                sig: c for sig, c in self._seen_action_signatures.items() if c > 1
            },
            "k8s_backend_real": self._k8s_backend.enabled,
        }

    # ------------------------------------------------------------------
    # Async internals
    # ------------------------------------------------------------------

    async def _async_reset(self, task_id: str) -> Observation:
        # Load scenario
        filename = TASK_FILE_MAP.get(task_id)
        if not filename:
            raise ValueError(f"Unknown task_id: {task_id}. Must be one of {list(TASK_FILE_MAP.keys())}")
        scenario_path = SCENARIOS_DIR / filename
        with open(scenario_path) as f:
            self._task = TaskScenario(**json.load(f))

        # Reset episode state
        self._step_count = 0
        self._done = False
        self._blast_tracker.reset()
        self._action_history = []
        self._root_cause_identified = False
        self._mitigation_applied = False
        self._cumulative_reward = 0.0
        self._useful_log_query_count = 0
        if not self._mock:
            # 1. Clean up previous faults
            await self._reset_cluster()
            # 2. Wait for baseline error rate < 0.01
            await self._wait_for_baseline()
            # 3. Inject the fault
            await self._inject_fault(task_id)
            # 4. Wait for fault propagation
            await asyncio.sleep(20)
        else:
            logger.info("[MOCK] Skipping cluster reset & fault injection for %s", task_id)

        return await self._build_observation()

    async def _async_step(self, action: Action) -> StepResult:
        if self._done:
            raise RuntimeError("Episode is done. Call reset() to start a new episode.")
        if self._task is None:
            raise RuntimeError("No task loaded. Call reset() first.")

        # Validate action type
        if action.type not in ActionType:
            raise ValueError(f"Invalid action type: {action.type}")

        # Log action (DEBUG in mock mode to avoid flooding during training)
        if self._mock:
            logger.debug("Action step=%d type=%s params=%s", self._step_count, action.type, action.params)
        else:
            log_level = logging.WARNING if action.type in WRITE_ACTIONS else logging.DEBUG
            logger.log(log_level, "Action step=%d type=%s params=%s", self._step_count, action.type, action.params)

        # Execute action
        action_result = await self._execute_action(action)

        # Wait for write actions to propagate
        if action.type in WRITE_ACTIONS:
            if not self._mock:
                await asyncio.sleep(10)

        # Build observation
        obs = await self._build_observation(action_result=action_result)

        # Record blast radius
        self._blast_tracker.record(self._step_count, obs.blast_radius_pct, action.type.value)

        # Compute reward
        reward = self._compute_reward(obs, action, action_result)
        self._cumulative_reward += reward

        # Record action
        self._action_history.append({
            "step": self._step_count,
            "action_type": action.type.value,
            "params": action.params,
            "reward": reward,
        })

        # Increment step
        self._step_count += 1

        # Check terminal conditions
        done = action.type == ActionType.SUBMIT_POSTMORTEM or self._step_count >= 20
        self._done = done

        info = {
            "reward_breakdown": self._last_reward_breakdown,
            "action_was_correct": self._last_action_correct,
            "current_blast_radius": obs.blast_radius_pct,
            "cumulative_reward": self._cumulative_reward,
        }

        return StepResult(observation=obs, reward=reward, done=done, info=info)

    # ------------------------------------------------------------------
    # Observation Builder
    # ------------------------------------------------------------------

    async def _build_observation(self, action_result: str = "") -> Observation:
        now = datetime.now(timezone.utc)

        if self._mock:
            return self._build_mock_observation(action_result)

        # Query all data sources in parallel
        try:
            (
                blast_num,
                blast_den,
                alerts_raw,
                logs,
                pods_info,
            ) = await asyncio.gather(
                self._prom.query_instant(
                    'sum(rate(http_requests_total{namespace="ecommerce",status_code=~"5.."}[2m]))'
                ),
                self._prom.query_instant(
                    'sum(rate(http_requests_total{namespace="ecommerce"}[2m]))'
                ),
                self._prom.get_all_active_alerts(),
                self._loki.query_logs(
                    '{namespace="ecommerce"}',
                    now - timedelta(minutes=5),
                    now,
                    limit=20,
                ),
                self._get_pod_statuses(),
            )
        except Exception as e:
            logger.warning("Failed to gather observation data: %s", e)
            return self._build_mock_observation(action_result)

        blast_radius_pct = (blast_num / blast_den * 100) if blast_den > 0 else 0.0

        # Parse alerts
        active_alerts = []
        for alert_data in (alerts_raw if isinstance(alerts_raw, list) else []):
            labels = alert_data.get("labels", {})
            annotations = alert_data.get("annotations", {})
            active_alerts.append(Alert(
                alert_name=labels.get("alertname", "Unknown"),
                severity=labels.get("severity", "info"),
                service=labels.get("service", "unknown"),
                firing_since=datetime.fromisoformat(
                    alert_data.get("startsAt", now.isoformat())
                ),
                annotations=annotations,
            ))

        # Build per-service health
        service_health = await self._build_service_health()

        # Time pressure based on step count
        if self._step_count <= 3:
            pressure = TimePressure.LOW
        elif self._step_count <= 8:
            pressure = TimePressure.MEDIUM
        elif self._step_count <= 14:
            pressure = TimePressure.HIGH
        else:
            pressure = TimePressure.CRITICAL

        return Observation(
            timestamp=now,
            active_alerts=active_alerts,
            recent_logs=logs,
            service_health=service_health,
            blast_radius_pct=blast_radius_pct,
            step_count=self._step_count,
            last_action_result=action_result,
            available_actions=ALL_AVAILABLE_ACTIONS,
            simulated_time_pressure=pressure,
        )

    async def _build_service_health(self) -> dict[str, ServiceStatus]:
        services = ["payments-api", "inventory-service", "order-worker", "notification-service", "checkout-frontend"]
        health: dict[str, ServiceStatus] = {}
        for svc in services:
            try:
                err_rate = await self._prom.query_instant(
                    f'sum(rate(http_requests_total{{app="{svc}",status_code=~"5.."}}[2m])) / '
                    f'sum(rate(http_requests_total{{app="{svc}"}}[2m]))'
                )
                p99 = await self._prom.query_instant(
                    f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{app="{svc}"}}[2m])) * 1000'
                )
            except Exception:
                err_rate = 0.0
                p99 = 0.0

            if err_rate > 0.1:
                status = HealthStatus.RED
            elif err_rate > 0.02:
                status = HealthStatus.YELLOW
            else:
                status = HealthStatus.GREEN

            health[svc] = ServiceStatus(
                name=svc,
                health=status,
                error_rate_2m=err_rate,
                p99_latency_ms=p99,
                replica_count=2,
                ready_replicas=2,
            )
        return health

    def _build_mock_observation(self, action_result: str = "") -> Observation:
        """Build a simulated observation for local dev / docker-compose mode."""
        now = datetime.now(timezone.utc)
        task = self._task

        # Simulate fault effects based on task
        blast = 15.0 if self._step_count < 3 else max(5.0, 15.0 - self._step_count * 1.5)
        if self._mitigation_applied:
            blast = max(0.5, blast - 10)

        alerts = []
        logs = []

        if task and task.task_id == "task1":
            alerts = [Alert(
                alert_name="RedisConnectionPoolSaturation",
                severity="warning",
                service="inventory-service",
                firing_since=now - timedelta(minutes=3),
                annotations={"summary": "Redis connection pool >90% saturated"},
            )]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=i * 5), service="inventory-service",
                        level="ERROR", message=f"ConnectionPoolTimeoutError: Could not get connection from pool within 5s (attempt {20-i})")
                for i in range(5)
            ]
        elif task and task.task_id == "task2":
            alerts = [
                Alert(alert_name="PaymentsOOMRisk", severity="critical", service="payments-api",
                      firing_since=now - timedelta(minutes=2),
                      annotations={"summary": "Payments API memory usage above 85%"}),
                Alert(alert_name="InventoryConsumerLag", severity="warning", service="inventory-service",
                      firing_since=now - timedelta(minutes=1),
                      annotations={"summary": "Kafka consumer lag > 1000 messages"}),
            ]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=10), service="payments-api",
                        level="ERROR", message="MemoryError: Cannot allocate 256MB for worker process"),
                LogLine(timestamp=now - timedelta(seconds=20), service="payments-api",
                        level="ERROR", message="Process killed with exit code 137 (OOMKilled)"),
                LogLine(timestamp=now - timedelta(seconds=30), service="inventory-service",
                        level="WARN", message="Kafka consumer lag increasing: 1247 messages behind"),
            ]
        elif task and task.task_id == "task3":
            alerts = [
                Alert(alert_name="PostgresHighCPU", severity="warning", service="postgres",
                      firing_since=now - timedelta(minutes=1),
                      annotations={"summary": "Postgres replica CPU spike (VACUUM ANALYZE running)"}),
            ]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=5), service="postgres",
                        level="INFO", message="VACUUM ANALYZE running on orders table - autovacuum scheduled task"),
                LogLine(timestamp=now - timedelta(seconds=15), service="payments-api",
                        level="INFO", message=f"Order created: order_id=abc-123, total_amount=49.99 (v{task.task_id})"),
                LogLine(timestamp=now - timedelta(seconds=60), service="payments-api",
                        level="DEBUG", message="Storing amount 49.9975 as NUMERIC(12,2) -> 49.99"),
            ]
        elif task and task.task_id == "task4":
            alerts = [
                Alert(alert_name="KafkaConsumerLagCritical", severity="critical", service="order-worker",
                      firing_since=now - timedelta(minutes=2),
                      annotations={"summary": "Kafka consumer lag >5000 messages on order-events topic"}),
                Alert(alert_name="KafkaConsumerLagHigh", severity="warning", service="notification-service",
                      firing_since=now - timedelta(minutes=1),
                      annotations={"summary": "Kafka consumer lag >2000 messages on notification-events topic"}),
            ]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=5), service="order-worker",
                        level="ERROR", message="KafkaConsumerError: Broker disconnected during fetch — partition rebalance in progress"),
                LogLine(timestamp=now - timedelta(seconds=10), service="order-worker",
                        level="ERROR", message="Consumer group 'order-consumers' lost partition assignment for order-events-0"),
                LogLine(timestamp=now - timedelta(seconds=20), service="notification-service",
                        level="WARN", message="Kafka consumer lag increasing: 3842 messages behind on notification-events"),
                LogLine(timestamp=now - timedelta(seconds=30), service="order-worker",
                        level="ERROR", message="KafkaConsumerError: Failed to connect to broker kafka-0:9092 — NetworkPartition"),
            ]
        elif task and task.task_id == "task5":
            alerts = [
                Alert(alert_name="FrontendErrorRate", severity="critical", service="checkout-frontend",
                      firing_since=now - timedelta(minutes=2),
                      annotations={"summary": "502 error rate >40% on checkout-frontend"}),
                Alert(alert_name="HealthCheckFailing", severity="warning", service="payments-api",
                      firing_since=now - timedelta(minutes=1),
                      annotations={"summary": "Health check endpoint returning connection refused"}),
            ]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=5), service="checkout-frontend",
                        level="ERROR", message="DNS lookup failed: NXDOMAIN for payments-api.ecommerce.svc.cluster.local"),
                LogLine(timestamp=now - timedelta(seconds=10), service="inventory-service",
                        level="ERROR", message="DNS resolution timeout: could not resolve redis.ecommerce.svc.cluster.local within 5s"),
                LogLine(timestamp=now - timedelta(seconds=15), service="checkout-frontend",
                        level="ERROR", message="HTTP 502: upstream connection refused — name resolution failed for inventory-service"),
                LogLine(timestamp=now - timedelta(seconds=25), service="payments-api",
                        level="WARN", message="Connection refused on health check — internal name resolution failure"),
            ]
        elif task and task.task_id == "task6":
            alerts = [
                Alert(alert_name="PostgresConnectionErrors", severity="critical", service="payments-api",
                      firing_since=now - timedelta(minutes=2),
                      annotations={"summary": "payments-api cannot establish database connections — all queries failing"}),
                Alert(alert_name="UpstreamTimeout", severity="warning", service="checkout-frontend",
                      firing_since=now - timedelta(minutes=1),
                      annotations={"summary": "Upstream timeout connecting to payments-api"}),
            ]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=5), service="payments-api",
                        level="ERROR", message="x509: certificate has expired or is not yet valid — TLS handshake failed to postgres"),
                LogLine(timestamp=now - timedelta(seconds=10), service="payments-api",
                        level="ERROR", message="ECONNRESET: connection reset by peer during mTLS handshake with postgres:5432"),
                LogLine(timestamp=now - timedelta(seconds=20), service="checkout-frontend",
                        level="ERROR", message="upstream timeout: payments-api did not respond within 10s"),
                LogLine(timestamp=now - timedelta(seconds=30), service="payments-api",
                        level="ERROR", message="SSL_ERROR: certificate verify failed — /etc/ssl/certs/mtls-cert.pem expired 30 minutes ago"),
            ]
        elif task and task.task_id == "task7":
            alerts = [
                Alert(alert_name="InventoryPricingInconsistency", severity="critical", service="inventory-service",
                      firing_since=now - timedelta(minutes=3),
                      annotations={"summary": "Inconsistent pricing returned across inventory-service pods"}),
                Alert(alert_name="RedisConnectionPoolWarn", severity="warning", service="inventory-service",
                      firing_since=now - timedelta(minutes=1),
                      annotations={"summary": "Redis connection pool brief saturation (recovered)"}),
                Alert(alert_name="JVMGCPause", severity="info", service="inventory-service",
                      firing_since=now - timedelta(minutes=2),
                      annotations={"summary": "GC pause >200ms detected on inventory-service pod-2"}),
            ]
            logs = [
                LogLine(timestamp=now - timedelta(seconds=5), service="inventory-service",
                        level="ERROR", message="Config hot-reload completed on pod-0 — feature flag 'pricing_in_cents' = true"),
                LogLine(timestamp=now - timedelta(seconds=10), service="inventory-service",
                        level="ERROR", message="Config reload FAILED on pod-2 — stale config retained, 'pricing_in_cents' = false"),
                LogLine(timestamp=now - timedelta(seconds=15), service="inventory-service",
                        level="WARN", message="Price mismatch: pod-0 returned $12.99 (cents mode), pod-2 returned $1299.00 (dollars mode)"),
                LogLine(timestamp=now - timedelta(seconds=25), service="inventory-service",
                        level="INFO", message="Redis connection pool recovered — transient saturation due to reconnect burst"),
                LogLine(timestamp=now - timedelta(seconds=40), service="inventory-service",
                        level="DEBUG", message="JVM GC pause 215ms — within normal parameters"),
            ]

        services = {}
        for svc in ["payments-api", "inventory-service", "order-worker", "notification-service", "checkout-frontend"]:
            err = 0.01
            if task and task.task_id == "task1" and svc == "inventory-service":
                err = 0.25 if not self._mitigation_applied else 0.02
            elif task and task.task_id == "task2" and svc == "payments-api":
                err = 0.35 if not self._mitigation_applied else 0.02
            elif task and task.task_id == "task4" and svc in ("order-worker", "notification-service"):
                err = 0.20 if not self._mitigation_applied else 0.02
            elif task and task.task_id == "task5" and svc == "checkout-frontend":
                err = 0.45 if not self._mitigation_applied else 0.02
            elif task and task.task_id == "task5" and svc in ("payments-api", "inventory-service"):
                err = 0.15 if not self._mitigation_applied else 0.02
            elif task and task.task_id == "task6" and svc == "payments-api":
                err = 0.50 if not self._mitigation_applied else 0.02
            elif task and task.task_id == "task7" and svc == "inventory-service":
                err = 0.30 if not self._mitigation_applied else 0.02
            services[svc] = ServiceStatus(
                name=svc,
                health=HealthStatus.RED if err > 0.1 else HealthStatus.GREEN,
                error_rate_2m=err,
                p99_latency_ms=150 if err < 0.1 else 2500,
                replica_count=2,
                ready_replicas=2 if err < 0.1 else 1,
            )

        pressure = TimePressure.LOW
        if self._step_count > 3:
            pressure = TimePressure.MEDIUM
        if self._step_count > 8:
            pressure = TimePressure.HIGH
        if self._step_count > 14:
            pressure = TimePressure.CRITICAL

        return Observation(
            timestamp=now,
            active_alerts=alerts,
            recent_logs=logs,
            service_health=services,
            blast_radius_pct=blast,
            step_count=self._step_count,
            last_action_result=action_result,
            available_actions=ALL_AVAILABLE_ACTIONS,
            simulated_time_pressure=pressure,
        )

    # ------------------------------------------------------------------
    # Action Execution
    # ------------------------------------------------------------------

    async def _execute_action(self, action: Action) -> str:
        t = action.type
        p = action.params

        if t == ActionType.QUERY_LOGS:
            return await self._action_query_logs(
                service=p.get("service", ""),
                last_minutes=p.get("last_minutes", 5),
                filter_text=p.get("filter_text"),
            )
        elif t == ActionType.QUERY_METRICS:
            return await self._action_query_metrics(
                promql=p.get("promql", ""),
                last_minutes=p.get("last_minutes", 5),
            )
        elif t == ActionType.GET_SERVICE_DEPENDENCIES:
            return self._action_get_deps(service=p.get("service", ""))
        elif t == ActionType.GET_TRACE:
            return await self._action_get_trace(trace_id=p.get("trace_id", ""))
        elif t == ActionType.ROLLBACK_DEPLOYMENT:
            return await self._action_rollback(
                deployment=p.get("deployment", ""),
                namespace=p.get("namespace", "ecommerce"),
            )
        elif t == ActionType.RESTART_PODS:
            return await self._action_restart(
                deployment=p.get("deployment", ""),
                namespace=p.get("namespace", "ecommerce"),
            )
        elif t == ActionType.SCALE_DEPLOYMENT:
            return await self._action_scale(
                deployment=p.get("deployment", ""),
                replicas=int(p.get("replicas", 2)),
                namespace=p.get("namespace", "ecommerce"),
            )
        elif t == ActionType.APPLY_CONFIG_PATCH:
            return await self._action_config_patch(
                deployment=p.get("deployment", ""),
                env_var=p.get("env_var", ""),
                value=str(p.get("value", "")),
                namespace=p.get("namespace", "ecommerce"),
            )
        elif t == ActionType.DELETE_CHAOS_EXPERIMENT:
            return await self._action_delete_chaos(experiment_name=p.get("experiment_name", ""))
        elif t == ActionType.EXEC_KUBECTL:
            cmd = p.get("command", "").strip()
            if not cmd:
                return "error: EXEC_KUBECTL requires params.command"
            if self._task and self._task.correct_mitigation_target \
                    and self._task.correct_mitigation_target in cmd:
                verb = cmd.replace("kubectl ", "", 1).strip().split(" ", 1)[0]
                if verb in ("set", "scale", "rollout", "patch", "delete", "apply"):
                    self._mitigation_applied = True
            return self._k8s_backend.execute(cmd)
        elif t == ActionType.SUBMIT_POSTMORTEM:
            return self._action_submit_postmortem(
                root_cause=p.get("root_cause", ""),
                timeline=p.get("timeline", ""),
                mitigations=p.get("mitigations", ""),
                affected_services=p.get("affected_services", []),
                recommended_followups=p.get("recommended_followups", ""),
            )
        else:
            aws_result = self._dispatch_aws_action(action)
            if aws_result is not None:
                return aws_result
            return f"Unknown action type: {t}"

    async def _action_query_logs(self, service: str, last_minutes: int, filter_text: str | None) -> str:
        if self._mock:
            return self._mock_query_logs(service, filter_text)
        now = datetime.now(timezone.utc)
        logql = f'{{namespace="ecommerce",app="{service}"}}'
        if filter_text:
            logql += f' |= "{filter_text}"'
        logs = await self._loki.query_logs(logql, now - timedelta(minutes=last_minutes), now)
        if not logs:
            return f"No logs found for {service} in the last {last_minutes} minutes."
        lines = [f"[{l.timestamp.isoformat()}] [{l.level}] [{l.service}] {l.message}" for l in logs[:20]]
        return "\n".join(lines)

    def _mock_query_logs(self, service: str, filter_text: str | None) -> str:
        """Return simulated logs based on the current task."""
        task = self._task
        if not task:
            return "No logs available."
        now = datetime.now(timezone.utc)
        lines = []

        if task.task_id == "task1" and service == "inventory-service":
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [ERROR] [inventory-service] ConnectionPoolTimeoutError: Could not get a connection from the Redis pool within 5.0s",
                f"[{(now - timedelta(seconds=10)).isoformat()}] [ERROR] [inventory-service] redis.exceptions.ConnectionError: Error while reading from redis pool: pool exhausted",
                f"[{(now - timedelta(seconds=15)).isoformat()}] [WARN] [inventory-service] Redis connection pool utilization at 100% (10/10 connections busy)",
                f"[{(now - timedelta(seconds=20)).isoformat()}] [ERROR] [inventory-service] ConnectionPoolTimeoutError: timeout waiting for idle connection",
                f"[{(now - timedelta(seconds=30)).isoformat()}] [INFO] [inventory-service] Falling back to PostgreSQL for product query (Redis unavailable)",
            ]
        elif task.task_id == "task2" and service == "payments-api":
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [ERROR] [payments-api] Process killed with exit code 137 (OOMKilled)",
                f"[{(now - timedelta(seconds=10)).isoformat()}] [ERROR] [payments-api] MemoryError: Unable to allocate 256MB block",
                f"[{(now - timedelta(seconds=20)).isoformat()}] [WARN] [payments-api] Memory usage at 92% of container limit (820MB/890MB)",
                f"[{(now - timedelta(seconds=30)).isoformat()}] [ERROR] [payments-api] kubernetes: Container payments-api in pod payments-api-7d8f9 was OOMKilled",
            ]
        elif task.task_id == "task2" and service == "inventory-service":
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [WARN] [inventory-service] Kafka consumer lag for group inventory-consumers: 1523 messages",
                f"[{(now - timedelta(seconds=15)).isoformat()}] [WARN] [inventory-service] Kafka consumer lag for group inventory-consumers: 987 messages",
                f"[{(now - timedelta(seconds=30)).isoformat()}] [INFO] [inventory-service] Processed order.fulfilled event for order abc-123",
            ]
        elif task.task_id == "task3" and service == "payments-api":
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [INFO] [payments-api] Order created: order_id=def-456, total_amount=149.99, version=2.3.2",
                f"[{(now - timedelta(seconds=10)).isoformat()}] [DEBUG] [payments-api] SQL: INSERT INTO orders (total_amount) VALUES (149.99) -- precision: NUMERIC(12,2)",
                f"[{(now - timedelta(seconds=15)).isoformat()}] [INFO] [payments-api] Order created: order_id=ghi-789, total_amount=49.99, version=2.3.2",
                f"[{(now - timedelta(seconds=20)).isoformat()}] [DEBUG] [payments-api] Rounding total_amount 49.9975 -> 49.99 (NUMERIC(12,2) truncation)",
            ]
        elif task.task_id == "task3" and service in ("postgres", "postgres-replica"):
            lines = [
                f"[{(now - timedelta(seconds=2)).isoformat()}] [INFO] [postgres] VACUUM ANALYZE running on public.orders (autovacuum scheduled)",
                f"[{(now - timedelta(seconds=5)).isoformat()}] [INFO] [postgres] CPU spike detected during VACUUM ANALYZE - expected behavior",
            ]
        elif task.task_id == "task4" and service == "order-worker":
            lines = [
                f"[{(now - timedelta(seconds=3)).isoformat()}] [ERROR] [order-worker] KafkaConsumerError: Broker disconnected — partition rebalance in progress",
                f"[{(now - timedelta(seconds=8)).isoformat()}] [ERROR] [order-worker] Consumer group 'order-consumers' lost all partition assignments",
                f"[{(now - timedelta(seconds=15)).isoformat()}] [ERROR] [order-worker] Failed to connect to broker kafka-0:9092 — NetworkPartition",
                f"[{(now - timedelta(seconds=20)).isoformat()}] [WARN] [order-worker] Consumer lag: 5231 messages behind on order-events",
            ]
        elif task.task_id == "task4" and service == "notification-service":
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [WARN] [notification-service] Kafka consumer lag: 3842 messages behind on notification-events",
                f"[{(now - timedelta(seconds=12)).isoformat()}] [ERROR] [notification-service] KafkaConsumerError: Broker disconnect during fetch",
            ]
        elif task.task_id == "task5" and service == "checkout-frontend":
            lines = [
                f"[{(now - timedelta(seconds=3)).isoformat()}] [ERROR] [checkout-frontend] DNS lookup failed: NXDOMAIN for payments-api.ecommerce.svc.cluster.local",
                f"[{(now - timedelta(seconds=8)).isoformat()}] [ERROR] [checkout-frontend] HTTP 502: upstream connection refused — name resolution failed",
                f"[{(now - timedelta(seconds=15)).isoformat()}] [ERROR] [checkout-frontend] DNS resolution timeout for inventory-service.ecommerce.svc.cluster.local",
            ]
        elif task.task_id == "task5" and service in ("payments-api", "inventory-service"):
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [ERROR] [{service}] DNS resolution timeout: cannot resolve dependencies",
                f"[{(now - timedelta(seconds=10)).isoformat()}] [WARN] [{service}] Service discovery lookup failed — name resolution error",
            ]
        elif task.task_id == "task6" and service == "payments-api":
            lines = [
                f"[{(now - timedelta(seconds=3)).isoformat()}] [ERROR] [payments-api] x509: certificate has expired or is not yet valid — TLS handshake failed",
                f"[{(now - timedelta(seconds=8)).isoformat()}] [ERROR] [payments-api] ECONNRESET: connection reset by peer during mTLS handshake with postgres:5432",
                f"[{(now - timedelta(seconds=15)).isoformat()}] [ERROR] [payments-api] SSL_ERROR: certificate verify failed — /etc/ssl/certs/mtls-cert.pem expired 30 minutes ago",
                f"[{(now - timedelta(seconds=20)).isoformat()}] [ERROR] [payments-api] Cannot establish any database connections — all TLS handshakes failing",
            ]
        elif task.task_id == "task6" and service == "checkout-frontend":
            lines = [
                f"[{(now - timedelta(seconds=5)).isoformat()}] [ERROR] [checkout-frontend] upstream timeout: payments-api did not respond within 10s",
                f"[{(now - timedelta(seconds=12)).isoformat()}] [ERROR] [checkout-frontend] ECONNRESET reading from payments-api",
            ]
        elif task.task_id == "task7" and service == "inventory-service":
            lines = [
                f"[{(now - timedelta(seconds=3)).isoformat()}] [ERROR] [inventory-service] Config hot-reload completed on pod-0: 'pricing_in_cents' = true",
                f"[{(now - timedelta(seconds=8)).isoformat()}] [ERROR] [inventory-service] Config reload FAILED on pod-2 — stale config retained: 'pricing_in_cents' = false",
                f"[{(now - timedelta(seconds=12)).isoformat()}] [WARN] [inventory-service] Price mismatch: pod-0 returned $12.99 (cents mode), pod-2 returned $1299.00 (dollars mode)",
                f"[{(now - timedelta(seconds=20)).isoformat()}] [INFO] [inventory-service] Redis connection pool recovered — transient saturation",
                f"[{(now - timedelta(seconds=30)).isoformat()}] [DEBUG] [inventory-service] JVM GC pause 215ms — within normal range",
            ]
        else:
            lines = [f"[{now.isoformat()}] [INFO] [{service}] Service operating normally. No errors detected."]

        if filter_text:
            lines = [l for l in lines if filter_text.lower() in l.lower()]

        return "\n".join(lines) if lines else f"No logs matching '{filter_text}' found for {service}."

    async def _action_query_metrics(self, promql: str, last_minutes: int) -> str:
        # Validate read-only PromQL
        if re.search(r"__name__\s*=", promql):
            return "ERROR: Mutation queries are not allowed. Only read-only PromQL is permitted."

        if self._mock:
            return f"[MOCK] Metrics query result for '{promql}': value=0.05 (simulated)"

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=last_minutes)
        results = await self._prom.query_range(promql, start, now)
        if not results:
            return f"No data returned for query: {promql}"
        return json.dumps(results, indent=2, default=str)

    def _action_get_deps(self, service: str) -> str:
        deps = SERVICE_DEPENDENCIES.get(service)
        if deps is None:
            return f"Unknown service: {service}. Known: {list(SERVICE_DEPENDENCIES.keys())}"
        return f"{service} depends on: {', '.join(deps)}"

    async def _action_get_trace(self, trace_id: str) -> str:
        if self._mock:
            return f"[MOCK] Trace {trace_id}: checkout-frontend -> payments-api (45ms) -> postgres (12ms) -> kafka-produce (8ms)"
        jaeger_url = os.getenv("JAEGER_URL", "http://localhost:16686")
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{jaeger_url}/api/traces/{trace_id}")
                r.raise_for_status()
                return json.dumps(r.json(), indent=2, default=str)
        except Exception as e:
            return f"Failed to fetch trace {trace_id}: {e}"

    async def _action_rollback(self, deployment: str, namespace: str) -> str:
        if self._mock:
            correct = CORRECT_SERVICES.get(self._task.task_id if self._task else "") 
            if deployment == correct:
                self._mitigation_applied = True
            logger.debug("[MOCK] Rollback deployment/%s -n %s", deployment, namespace)
            return f"[MOCK] Rolled back deployment/{deployment} in namespace {namespace} to previous revision."
        return await self._k8s_rollback(deployment, namespace)

    async def _action_restart(self, deployment: str, namespace: str) -> str:
        if self._mock:
            logger.debug("[MOCK] Restart pods for deployment/%s -n %s", deployment, namespace)
            return f"[MOCK] Restarted pods for deployment/{deployment} in namespace {namespace}."
        return await self._k8s_restart(deployment, namespace)

    async def _action_scale(self, deployment: str, replicas: int, namespace: str) -> str:
        if replicas < 0 or replicas > 20:
            return f"ERROR: replicas must be between 0 and 20, got {replicas}"
        if self._mock:
            logger.debug("[MOCK] Scale deployment/%s to %d replicas -n %s", deployment, replicas, namespace)
            return f"[MOCK] Scaled deployment/{deployment} to {replicas} replicas in namespace {namespace}."
        return await self._k8s_scale(deployment, replicas, namespace)

    async def _action_config_patch(self, deployment: str, env_var: str, value: str, namespace: str) -> str:
        if self._mock:
            logger.debug("[MOCK] Patch deployment/%s env %s=%s -n %s", deployment, env_var, value, namespace)
            return f"[MOCK] Patched deployment/{deployment}: set {env_var}={value} in namespace {namespace}."
        return await self._k8s_config_patch(deployment, env_var, value, namespace)

    async def _action_delete_chaos(self, experiment_name: str) -> str:
        if self._mock:
            if self._task and self._task.chaos_experiment_name == experiment_name:
                self._mitigation_applied = True
            logger.debug("[MOCK] Delete Chaos Mesh experiment: %s", experiment_name)
            return f"[MOCK] Deleted Chaos Mesh experiment '{experiment_name}'."
        try:
            await self._chaos.delete_experiment(experiment_name)
            if self._task and self._task.chaos_experiment_name == experiment_name:
                self._mitigation_applied = True
            return f"Deleted Chaos Mesh experiment '{experiment_name}'."
        except Exception as e:
            return f"Failed to delete experiment '{experiment_name}': {e}"

    def _action_submit_postmortem(
        self, root_cause: str, timeline: str, mitigations: str,
        affected_services: list[str], recommended_followups: str,
    ) -> str:
        if not self._task:
            return "ERROR: No task loaded."
        postmortem = {
            "root_cause": root_cause,
            "timeline": timeline,
            "mitigations": mitigations,
            "affected_services": affected_services,
            "recommended_followups": recommended_followups,
        }
        scores = grade_postmortem(
            submitted=postmortem,
            ground_truth_root_cause=self._task.ground_truth_root_cause,
            task_id=self._task.task_id,
            reference_postmortem=self._task.reference_postmortem,
        )
        return json.dumps({"postmortem_scores": scores}, indent=2)

    # ------------------------------------------------------------------
    # AWS-flavoured non-obvious action dispatch
    # ------------------------------------------------------------------

    def _dispatch_aws_action(self, action: Action) -> str | None:
        """Run an AWS-flavoured action. Returns None if the action type is
        not one of the AWS variants (caller falls through to 'Unknown').

        Side-effects on env state:
          * tracks which forensic tools have been used (rewards consult these)
          * marks `_mitigation_applied` for the AWS-write actions when the
            target matches the task's correct_mitigation_target.
        """
        from . import aws_actions as A
        t = action.type
        p = action.params or {}
        # Lazily-initialised investigation sets.
        self._aws_inspected = getattr(self, "_aws_inspected", set())
        self._aws_remediated = getattr(self, "_aws_remediated", set())

        # If a simulator scenario is active, every AWS action goes through
        # the simulator engine so live AWS is never touched.
        if getattr(self, "_sim_active", False) and self._sim_state is not None:
            sim_result = self._dispatch_sim_action(action)
            if sim_result is not None:
                return sim_result

        # ---------- read / forensic ----------
        if t == ActionType.CHECK_CLOUDTRAIL_EVENTS:
            self._aws_inspected.add("cloudtrail")
            return A.check_cloudtrail_events(
                resource_name=p.get("resource_name", ""),
                event_name=p.get("event_name", ""),
                last_minutes=int(p.get("last_minutes", 60)))
        if t == ActionType.DESCRIBE_RESOURCE_POLICY:
            self._aws_inspected.add("resource_policy")
            return A.describe_resource_policy(target=p.get("target", ""))
        if t == ActionType.GET_QUOTA_USAGE:
            self._aws_inspected.add("quota")
            return A.get_quota_usage(
                service_code=p.get("service_code", ""),
                quota_code=p.get("quota_code", ""))
        if t == ActionType.CHECK_SECRET_ROTATION:
            self._aws_inspected.add("secret_rotation")
            return A.check_secret_rotation(
                secret_name=p.get("secret_name", ""))
        if t == ActionType.VALIDATE_IAM_PERMISSION:
            self._aws_inspected.add("iam_sim")
            return A.validate_iam_permission(
                action=p.get("iam_action", ""),
                resource=p.get("resource", "*"),
                principal=p.get("principal", ""))
        if t == ActionType.ANALYZE_CLOUDWATCH_INSIGHTS:
            self._aws_inspected.add("insights")
            return A.analyze_cloudwatch_insights(
                log_group=p.get("log_group", ""),
                pattern=p.get("pattern", "ERROR"),
                last_minutes=int(p.get("last_minutes", 15)))
        if t == ActionType.INSPECT_DLQ_MESSAGES:
            self._aws_inspected.add("dlq_inspect")
            return A.inspect_dlq_messages(
                queue_name=p.get("queue_name", "ic-orders-dlq"),
                max_messages=int(p.get("max_messages", 5)))
        if t == ActionType.DIFF_CONFIG_VERSIONS:
            self._aws_inspected.add("ssm_diff")
            return A.diff_config_versions(
                parameter_name=p.get("parameter_name", ""),
                a=int(p.get("a", 0)), b=int(p.get("b", 0)))
        if t == ActionType.DESCRIBE_STATE_MACHINE_EXEC:
            self._aws_inspected.add("sfn_exec")
            return A.describe_state_machine_execution(
                execution_arn=p.get("execution_arn", ""),
                state_machine_name=p.get("state_machine_name", ""))

        # ---------- write / remediation ----------
        if t == ActionType.INVOKE_LAMBDA:
            self._aws_remediated.add("lambda")
            # Recognise correct mitigation when the agent invokes the runbook
            # lambda for a task whose correct action is invoke_lambda.
            if (self._task and
                    self._task.correct_mitigation_action == "invoke_lambda"):
                self._mitigation_applied = True
            return A.invoke_lambda(
                function_name=p.get("function_name", ""),
                payload=p.get("payload"))
        if t == ActionType.ROTATE_SECRET:
            self._aws_remediated.add("secret_rotation")
            if (self._task and
                    self._task.correct_mitigation_action == "rotate_secret"):
                self._mitigation_applied = True
            return A.rotate_secret(
                secret_name=p.get("secret_name", ""))
        if t == ActionType.PURGE_QUEUE:
            self._aws_remediated.add("purge")
            if (self._task and
                    self._task.correct_mitigation_action == "purge_queue"):
                self._mitigation_applied = True
            return A.purge_queue(queue_name=p.get("queue_name", ""))
        if t == ActionType.ENABLE_EVENTBRIDGE_RULE:
            self._aws_remediated.add("enable_rule")
            if (self._task and
                    self._task.correct_mitigation_action == "enable_eventbridge_rule"):
                self._mitigation_applied = True
            return A.enable_eventbridge_rule(
                rule_name=p.get("rule_name", ""),
                bus_name=p.get("bus_name", ""))
        return None

    # ------------------------------------------------------------------
    # Simulator dispatch
    # ------------------------------------------------------------------
    # Map ActionType variants (the "named" AWS actions) to a (service, verb)
    # tuple plus a parameter projector. The simulator engine just consumes
    # `{"id": "<service>.<verb>", "params": {...}}`, so we translate.
    _AWS_ACTION_MAP: dict = {
        # Read / forensic
        ActionType.CHECK_CLOUDTRAIL_EVENTS:
            ("cloudtrail", "list_events", lambda p: {
                "filter": p.get("event_name", ""),
                "range_minutes": int(p.get("last_minutes", 60))}),
        ActionType.DESCRIBE_RESOURCE_POLICY:
            ("s3", "get_policy", lambda p: {"resource_id": p.get("target", "")}),
        ActionType.GET_QUOTA_USAGE:
            ("cloudwatch", "get_quota", lambda p: {
                "service_code": p.get("service_code", "")}),
        ActionType.CHECK_SECRET_ROTATION:
            ("secretsmanager", "describe", lambda p: {
                "resource_id": p.get("secret_name", "")}),
        ActionType.VALIDATE_IAM_PERMISSION:
            ("iam", "simulate_policy", lambda p: {
                "principal": p.get("principal", ""),
                "action_name": p.get("iam_action", ""),
                "resource": p.get("resource", "*")}),
        ActionType.ANALYZE_CLOUDWATCH_INSIGHTS:
            ("cloudwatch", "get_logs", lambda p: {
                "log_group": p.get("log_group", ""),
                "filter": p.get("pattern", ""),
                "range_minutes": int(p.get("last_minutes", 15))}),
        ActionType.INSPECT_DLQ_MESSAGES:
            ("sqs", "receive", lambda p: {
                "resource_id": p.get("queue_name", ""),
                "limit": int(p.get("max_messages", 5))}),
        ActionType.DIFF_CONFIG_VERSIONS:
            ("ssm", "diff_versions", lambda p: {
                "resource_id": p.get("parameter_name", ""),
                "v1": p.get("v1", 1), "v2": p.get("v2", 2)}),
        ActionType.DESCRIBE_STATE_MACHINE_EXEC:
            ("stepfunctions", "describe", lambda p: {
                "resource_id": p.get("state_machine_name", "")}),
        # Write / remediation
        ActionType.INVOKE_LAMBDA:
            ("lambda", "invoke", lambda p: {
                "resource_id": p.get("function_name", ""),
                "payload": p.get("payload", "")}),
        ActionType.ROTATE_SECRET:
            ("secretsmanager", "rotate", lambda p: {
                "resource_id": p.get("secret_name", "")}),
        ActionType.PURGE_QUEUE:
            ("sqs", "purge", lambda p: {
                "resource_id": p.get("queue_name", "")}),
        ActionType.ENABLE_EVENTBRIDGE_RULE:
            ("events", "enable", lambda p: {
                "bus_name": p.get("bus_name", ""),
                "rule_name": p.get("rule_name", "")}),
    }

    def _dispatch_sim_action(self, action: Action) -> str | None:
        """Route the action through the simulator. Returns a string result, or
        None if this action variant has no simulator mapping (caller falls
        back to live-AWS code paths — which are themselves no-ops when
        IC_USE_LIVE_AWS is unset)."""
        from simulator import dispatch as sim_dispatch
        p = action.params or {}

        # Generic AWS_API_CALL — agent specifies service + verb directly.
        if action.type == ActionType.AWS_API_CALL:
            service = p.get("service")
            verb    = p.get("verb")
            if not service or not verb:
                return "[sim:error] AWS_API_CALL requires params.service and params.verb"
            inner_params = {k: v for k, v in p.items()
                            if k not in ("service", "verb")}
            result = sim_dispatch(
                {"id": f"{service}.{verb}", "params": inner_params},
                self._sim_state)
            self._sync_sim_breadcrumbs(result)
            self._tag_breadcrumbs(result, service, verb)
            return result.as_observation()

        mapping = self._AWS_ACTION_MAP.get(action.type)
        if mapping is None:
            return None
        service, verb, project = mapping
        result = sim_dispatch(
            {"id": f"{service}.{verb}", "params": project(p)},
            self._sim_state)
        self._sync_sim_breadcrumbs(result)
        self._tag_breadcrumbs(result, service, verb)
        return result.as_observation()

    def _tag_breadcrumbs(self, result, service: str, verb: str) -> None:
        """Translate simulator tags into env reward breadcrumbs."""
        # Inspection-flavoured tags from both legacy AWS handlers and the
        # `platform.*` physics handlers.
        INSPECT_TAGS = {
            "cloudtrail", "iam_sim", "insights", "dlq_inspect",
            "secret_rotation", "ssm_diff", "resource_policy", "sfn_exec",
            "investigation", "logs", "trace", "metrics", "topology",
            "runbook_read", "runbook_search", "heap_dump", "traffic",
            "slack",
        }
        for tag in result.tags:
            if tag in INSPECT_TAGS:
                self._aws_inspected.add(tag)
            if tag in ("remediation", "remediation_safe", "remediation_pending"):
                self._aws_remediated.add(f"{service}.{verb}")

    def _sync_sim_breadcrumbs(self, result) -> None:
        """Fold simulator-side breadcrumbs into env reward state."""
        if not result.ok:
            return
        if self._sim_state is not None and self._sim_state.mitigation_applied:
            self._mitigation_applied = True

    def _dump_replay(self) -> Path | None:
        """Write a standalone HTML replay artifact next to checkpoints/.

        Path: `<repo>/rl-agent/replays/{task_id}_{episode}.html`. The path is
        configurable via env var `IC_REPLAY_DIR`.
        """
        if self._sim_state is None or self._task is None:
            return None
        from .replay import build_replay
        out_dir = Path(os.environ.get("IC_REPLAY_DIR",
                                       Path(__file__).resolve().parent.parent
                                       / "replays"))
        out_dir.mkdir(parents=True, exist_ok=True)
        ep_id = f"{self._task.task_id}_{int(self._sim_state.clock_s)}"
        out = out_dir / f"{ep_id}.html"
        return build_replay(self._sim_state,
                            task_id=self._task.task_id,
                            episode_id=ep_id,
                            final_reward=self._cumulative_reward,
                            mitigated=self._mitigation_applied,
                            out_path=out)

    # ------------------------------------------------------------------
    # Reward Function
    # ------------------------------------------------------------------

    def _compute_reward(
        self,
        obs: Observation,
        action: Action,
        action_result: str,
        *,
        repeat_count: int = 0,
        judge_score: float = 0.0,
        prev_phase: str | None = None,
        next_phase: str = "investigate",
    ) -> float:
        """Deterministic shaped reward with context-gated penalties. Never uses random numbers."""
        if self._task is None:
            return 0.0

        breakdown: dict[str, float] = {}
        total = 0.0

        task = self._task
        task_id = task.task_id

        # --- Step cost: -0.01 per step (encourages efficiency) ---
        breakdown["step_cost"] = -0.01

        # --- First-time read actions (investigation bonus): +0.05 each ---
        if action.type == ActionType.QUERY_LOGS:
            svc = action.params.get("service", "")
            first_time = len([a for a in self._action_history if a["action_type"] == "query_logs" and a.get("params", {}).get("service") == svc]) == 0
            if first_time:
                breakdown["investigation_bonus"] = 0.05
        elif action.type == ActionType.QUERY_METRICS:
            if not any(a["action_type"] == "query_metrics" for a in self._action_history):
                breakdown["investigation_bonus"] = 0.05
        elif action.type == ActionType.GET_SERVICE_DEPENDENCIES:
            svc = action.params.get("service", "")
            first_time = len([a for a in self._action_history if a["action_type"] == "get_service_dependencies" and a.get("params", {}).get("service") == svc]) == 0
            if first_time:
                breakdown["investigation_bonus"] = 0.05
        elif action.type == ActionType.GET_TRACE:
            if not any(a["action_type"] == "get_trace" for a in self._action_history):
                breakdown["investigation_bonus"] = 0.05

        # --- EXEC_KUBECTL: investigation bonus for read-verbs, no bonus for writes ---
        elif action.type == ActionType.EXEC_KUBECTL:
            cmd_str = str(action.params.get("command", "")).lower()
            verb = cmd_str.replace("kubectl ", "", 1).strip().split(" ", 1)[0] if cmd_str else ""
            read_verbs = {"get", "describe", "logs", "events", "top"}
            if verb in read_verbs:
                # one-time bonus per (verb, resource) pair
                key = f"exec:{verb}:{(cmd_str.split(' ', 2)[1] if len(cmd_str.split(' ')) > 1 else '')}"
                if key not in self._inspected_logs:
                    self._inspected_logs.add(key)
                    breakdown["investigation_bonus"] = 0.05

        # --- Root cause identification (+0.3) ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            rc = action.params.get("root_cause", "")
            rc_norm = rc.lower().replace("-", "_").replace(" ", "_")
            gt_norm = task.ground_truth_root_cause.lower().replace("-", "_").replace(" ", "_")
            if gt_norm in rc_norm or rc_norm == gt_norm:
                breakdown["root_cause_correct"] = 0.3
                self._root_cause_identified = True

        # --- Correct mitigation before step 10 (+0.2) ---
        if self._step_count < 10 and not self._mitigation_applied:
            if action.type.value == task.correct_mitigation_action:
                target = action.params.get("deployment", action.params.get("experiment_name", ""))
                if target == task.correct_mitigation_target:
                    breakdown["correct_mitigation"] = 0.2
                    self._mitigation_applied = True

        # --- Useful log query (+0.1) ---
        if action.type == ActionType.QUERY_LOGS:
            keywords = task.useful_log_keywords
            if any(kw.lower() in action_result.lower() for kw in keywords):
                breakdown["useful_log_query"] = 0.1
                self._useful_log_query_count = getattr(self, "_useful_log_query_count", 0) + 1

        # --- Postmortem quality (+0.2) ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            try:
                scores = json.loads(action_result).get("postmortem_scores", {})
                pm_total = scores.get("total", 0.0)
                breakdown["postmortem_quality"] = min(0.2, pm_total)
            except (json.JSONDecodeError, AttributeError):
                pass

        # --- Context-gated penalty: acting without investigating (-0.20) ---
        # If agent takes a write action without having inspected any logs first,
        # it gets penalized for acting blind
        if action.type in WRITE_ACTIONS:
            if len(self._inspected_logs) == 0 and not self._inspected_metrics:
                breakdown["acting_blind_penalty"] = -0.20

        # --- Context-gated penalty: ignoring evidence (-0.15) ---
        # If agent saw a red herring service and targets it anyway
        if action.type in WRITE_ACTIONS and action.type != ActionType.DELETE_CHAOS_EXPERIMENT:
            target_deploy = action.params.get("deployment", "")
            if task.red_herrings:
                for herring in task.red_herrings:
                    if herring.lower() in target_deploy.lower():
                        breakdown["red_herring_penalty"] = -0.15
                        break

        # --- Wrong service penalty (-0.15) ---
        if action.type in WRITE_ACTIONS and action.type != ActionType.DELETE_CHAOS_EXPERIMENT:
            target_deploy = action.params.get("deployment", "")
            correct = CORRECT_SERVICES.get(task_id)
            if correct and target_deploy != correct:
                breakdown["wrong_service_penalty"] = -0.15

        # --- Time penalty: -0.05 * max(0, step - 5) ---
        excess = max(0, self._step_count - 5)
        if excess > 0:
            penalty = -0.05 * excess
            breakdown["time_penalty"] = penalty

        # --- Blast radius increase after write action (-0.10) ---
        if self._blast_tracker.check_action_caused_increase(self._step_count):
            breakdown["blast_radius_increase"] = -0.10

        # --- Repeat-command penalty (-0.15 per repeat, capped at -0.45) ---
        # Mirrors kube-sre-gym: discourages the agent from spamming the same
        # command when it fails. Read actions with a plausible params variation
        # (different service / filter) are tracked separately via signature.
        if repeat_count > 0:
            breakdown["repeat_command_penalty"] = max(-0.45, -0.15 * repeat_count)

        # --- Phase-order bonus/penalty ---
        # +0.10 when phase progresses (triage -> investigate -> fix -> verify)
        # -0.10 when the agent regresses phases.
        po_bonus = phase_order_bonus(prev_phase, next_phase)  # type: ignore[arg-type]
        if po_bonus != 0.0:
            breakdown["phase_order"] = po_bonus

        # --- LLM/heuristic judge contribution (scaled to [-0.1, +0.15]) ---
        # We only take a small slice of the judge score to keep dense per-step
        # rewards dominated by deterministic signals.
        if judge_score != 0.0:
            breakdown["judge"] = max(-0.1, min(0.15, judge_score * 0.15))

        # --- Evidence alignment (+0.10) ---
        # The postmortem root-cause claim is supported by a log query whose
        # result actually contained useful keywords (we track via useful_log_query).
        if action.type == ActionType.SUBMIT_POSTMORTEM and self._root_cause_identified:
            if getattr(self, "_useful_log_query_count", 0) > 0:
                breakdown["evidence_alignment"] = 0.10

        # --- Mitigation efficiency (+0.15 if fixed in <=3 write actions) ---
        if action.type == ActionType.SUBMIT_POSTMORTEM and self._mitigation_applied:
            write_count = sum(1 for a in self._action_history
                              if a.get("action_type") in {w.value for w in WRITE_ACTIONS})
            if write_count <= 3:
                breakdown["mitigation_efficiency"] = 0.15
            elif write_count > 6:
                breakdown["mitigation_thrash_penalty"] = -0.10

        # --- Recovery verified against real cluster (+0.20) ---
        # If the backend is real AND, after the agent's mitigation, pods on
        # the correct service reached the Running/Ready state, reward it.
        if (action.type == ActionType.SUBMIT_POSTMORTEM
                and self._mitigation_applied
                and getattr(self._k8s_backend, "enabled", False)):
            try:
                correct = CORRECT_SERVICES.get(task_id)
                if correct:
                    health = self._k8s_backend.check_health_detailed()
                    pods_ok = any(
                        (p.get("phase") == "Running" and not p.get("waiting_reason"))
                        for ns_pods in health.values()
                        for name, p in ns_pods.items()
                        if correct in name
                    )
                    if pods_ok:
                        breakdown["recovery_verified"] = 0.20
            except Exception:
                pass

        # --- Diverse-evidence bonus (+0.05) ---
        # Reward the agent for consulting >=3 different evidence sources
        # (logs, metrics, deps, traces, exec).
        sources = 0
        sources += int(bool(self._inspected_logs))
        sources += int(self._inspected_metrics)
        sources += int(bool(self._inspected_deps))
        sources += int(self._inspected_traces)
        sources += int(any(k.startswith("exec:") for k in self._inspected_logs))
        if action.type == ActionType.SUBMIT_POSTMORTEM and sources >= 3:
            breakdown["diverse_evidence"] = 0.05

        # =============================================================
        # Extended reward signals (added for richer credit assignment).
        # All deterministic; values are small so they don't dominate.
        # =============================================================

        # --- early_triage_bonus: first 2 steps are read actions (+0.08) ---
        if self._step_count == 2 and len(self._action_history) >= 2:
            first_two = self._action_history[:2]
            if all(a.get("action_type") in {"query_logs", "query_metrics",
                                            "get_service_dependencies", "get_trace"}
                   for a in first_two):
                breakdown["early_triage_bonus"] = 0.08

        # --- dependency_first_bonus: get_service_dependencies before any write ---
        if action.type == ActionType.GET_SERVICE_DEPENDENCIES:
            wrote_already = any(a.get("action_type") in {w.value for w in WRITE_ACTIONS}
                                for a in self._action_history)
            if not wrote_already and "dependency_first_bonus" not in breakdown:
                breakdown["dependency_first_bonus"] = 0.05

        # --- metric_correlation_bonus: same service queried in both logs & metrics ---
        if action.type == ActionType.QUERY_METRICS:
            promql = str(action.params.get("promql", ""))
            services_in_logs = {a.get("params", {}).get("service", "")
                                for a in self._action_history
                                if a.get("action_type") == "query_logs"}
            for svc in services_in_logs:
                if svc and svc in promql:
                    breakdown["metric_correlation_bonus"] = 0.05
                    break

        # --- trace_used_bonus: at least one trace lookup over the episode ---
        if action.type == ActionType.GET_TRACE and not self._inspected_traces:
            breakdown["trace_used_bonus"] = 0.04

        # --- exec_diagnostic_bonus: kubectl describe/get used (read-verb exec) ---
        if action.type == ActionType.EXEC_KUBECTL:
            cmd = str(action.params.get("command", "")).lower()
            if any(v in cmd for v in (" describe ", " get ", " events", " top ")):
                breakdown["exec_diagnostic_bonus"] = 0.05

        # --- cross_service_evidence: investigated >=2 distinct services ---
        if action.type in {ActionType.QUERY_LOGS, ActionType.GET_SERVICE_DEPENDENCIES}:
            inspected_services = {a.get("params", {}).get("service", "")
                                  for a in self._action_history
                                  if a.get("action_type") in
                                  {"query_logs", "get_service_dependencies"}}
            inspected_services.discard("")
            if len(inspected_services) >= 2 and "cross_service_evidence" not in breakdown:
                breakdown["cross_service_evidence"] = 0.04

        # --- parameter_specificity_bonus: query_logs with a filter_text ---
        if action.type == ActionType.QUERY_LOGS and action.params.get("filter_text"):
            breakdown["parameter_specificity_bonus"] = 0.03

        # --- quick_root_cause_bonus: identified root cause within 4 steps ---
        if (action.type == ActionType.SUBMIT_POSTMORTEM
                and self._root_cause_identified
                and self._step_count <= 4):
            breakdown["quick_root_cause_bonus"] = 0.10

        # --- verification_after_fix: read action AFTER a mitigation ---
        if (action.type in {ActionType.QUERY_LOGS, ActionType.QUERY_METRICS,
                            ActionType.EXEC_KUBECTL}
                and self._mitigation_applied):
            breakdown["verification_after_fix"] = 0.06

        # --- runbook_match_bonus: postmortem lists correct affected service ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            correct = CORRECT_SERVICES.get(task_id, "")
            affected = action.params.get("affected_services", []) or []
            if correct and any(correct.lower() in str(s).lower() for s in affected):
                breakdown["runbook_match_bonus"] = 0.05

        # --- low_thrash_bonus: <=2 write actions in the entire episode ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            writes = sum(1 for a in self._action_history
                         if a.get("action_type") in {w.value for w in WRITE_ACTIONS})
            if writes <= 2:
                breakdown["low_thrash_bonus"] = 0.05

        # --- fast_resolution_bonus: mitigation in <=6 total steps ---
        if (action.type == ActionType.SUBMIT_POSTMORTEM
                and self._mitigation_applied
                and self._step_count <= 6):
            breakdown["fast_resolution_bonus"] = 0.08

        # --- exploration_diversity: unique action types used (cap 0.08) ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            uniq = len({a.get("action_type") for a in self._action_history})
            breakdown["exploration_diversity"] = min(0.08, 0.015 * uniq)

        # --- consistent_postmortem_bonus: required postmortem fields present ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            required = ("root_cause", "summary", "mitigation",
                        "blast_radius", "timeline", "prevention")
            present = sum(1 for k in required
                          if isinstance(action.params.get(k), str)
                          and len(action.params.get(k, "")) > 6)
            breakdown["consistent_postmortem_bonus"] = round(0.01 * present, 3)

        # --- log_keyword_match_strength: cumulative useful log queries (cap +0.10) ---
        ulqc = getattr(self, "_useful_log_query_count", 0)
        if ulqc > 0 and action.type == ActionType.QUERY_LOGS:
            breakdown["log_keyword_match_strength"] = min(0.10, 0.025 * ulqc)

        # --- followup_quality_bonus: postmortem proposes >=3 followups ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            fu = action.params.get("recommended_followups", []) or []
            if isinstance(fu, list) and len(fu) >= 3:
                breakdown["followup_quality_bonus"] = 0.03

        # --- safe_action_bonus: avoided destructive verbs (delete/drop) ---
        if action.type == ActionType.EXEC_KUBECTL:
            cmd = str(action.params.get("command", "")).lower()
            if not any(d in cmd for d in (" delete ", " drop ", " --force ")):
                breakdown["safe_action_bonus"] = 0.02

        # =============================================================
        # AWS-aware + safety + observability reward signals (round 3).
        # All deterministic, low-magnitude, gated on action+task context.
        # =============================================================

        aws_hints = TASK_AWS_HINTS.get(task_id, [])
        # Lowercased postmortem text once, used by several signals below.
        pm_blob = ""
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            pm_blob = " ".join(
                str(v) for v in action.params.values() if isinstance(v, (str, list))
            ).lower()

        # --- aws_evidence_used (+0.06): postmortem mentions \u22651 expected AWS term ---
        if action.type == ActionType.SUBMIT_POSTMORTEM and aws_hints:
            hits = sum(1 for h in aws_hints if h.lower() in pm_blob)
            if hits >= 1:
                breakdown["aws_evidence_used"] = round(min(0.06, 0.02 * hits), 3)

        # --- iam_least_privilege_bonus (+0.05): postmortem mentions IAM scoping ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            if any(kw in pm_blob for kw in (
                    "least-privilege", "least privilege", "irsa",
                    "iam policy", "scope", "assumerole")):
                breakdown["iam_least_privilege_bonus"] = 0.05

        # --- cost_awareness_bonus (+0.03): postmortem reasons about cost ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            if any(kw in pm_blob for kw in (
                    "cost", "budget", "$", "cheaper", "pay_per_request",
                    "provisioned concurrency", "rcu", "wcu")):
                breakdown["cost_awareness_bonus"] = 0.03

        # --- security_followup_bonus (+0.04): a followup mentions security ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            fu = action.params.get("recommended_followups", []) or []
            joined = " ".join(str(x) for x in fu).lower() if isinstance(fu, list) else ""
            if any(k in joined for k in ("rotate", "audit", "rbac", "iam",
                                         "secret", "ciphertext", "encrypt")):
                breakdown["security_followup_bonus"] = 0.04

        # --- timeline_quality_bonus (+0.04): timeline has \u22653 dated entries ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            timeline = action.params.get("timeline", "")
            if isinstance(timeline, str):
                # Crude: count occurrences of T+ markers or HH:MM-style stamps.
                ts_count = len(re.findall(r"(?:T\+\d|\d{1,2}:\d{2})", timeline))
                if ts_count >= 3:
                    breakdown["timeline_quality_bonus"] = 0.04

        # --- replica_target_safe (+0.02): scale to a sane replica count ---
        if action.type == ActionType.SCALE_DEPLOYMENT:
            try:
                n = int(action.params.get("replicas", 0))
                if 1 <= n <= 20:
                    breakdown["replica_target_safe"] = 0.02
                elif n > 50:
                    breakdown["replica_target_unsafe"] = -0.05
            except (TypeError, ValueError):
                pass

        # --- correct_action_type (+0.05): right action verb even if wrong target ---
        if (action.type in WRITE_ACTIONS
                and action.type.value == task.correct_mitigation_action
                and not self._mitigation_applied):
            breakdown["correct_action_type"] = 0.05

        # --- service_dependency_traversal (+0.04): queried logs of a known dep ---
        if action.type == ActionType.QUERY_LOGS:
            svc = action.params.get("service", "")
            correct = CORRECT_SERVICES.get(task_id) or ""
            deps = SERVICE_DEPENDENCIES.get(correct, [])
            if svc and svc in deps and "service_dependency_traversal" not in breakdown:
                breakdown["service_dependency_traversal"] = 0.04

        # --- alert_triage_match (+0.05): first read targets a service in alerts ---
        if (self._step_count == 1
                and action.type in {ActionType.QUERY_LOGS,
                                    ActionType.QUERY_METRICS,
                                    ActionType.GET_SERVICE_DEPENDENCIES}
                and obs.active_alerts):
            alert_svcs = {a.service for a in obs.active_alerts}
            tgt = action.params.get("service", "") or str(action.params.get("promql", ""))
            if any(s and s in tgt for s in alert_svcs):
                breakdown["alert_triage_match"] = 0.05

        # --- progressive_investigation (+0.04): logs \u2192 metrics \u2192 trace order ---
        if action.type == ActionType.GET_TRACE:
            seen_logs    = any(a["action_type"] == "query_logs"
                               for a in self._action_history)
            seen_metrics = any(a["action_type"] == "query_metrics"
                               for a in self._action_history)
            if seen_logs and seen_metrics and not self._inspected_traces:
                breakdown["progressive_investigation"] = 0.04

        # --- specific_promql_bonus (+0.03): query uses rate()/histogram_quantile ---
        if action.type == ActionType.QUERY_METRICS:
            promql = str(action.params.get("promql", "")).lower()
            if any(fn in promql for fn in ("rate(", "histogram_quantile",
                                           "increase(", "sum by", "max_over_time")):
                breakdown["specific_promql_bonus"] = 0.03

        # --- avoided_red_herring (+0.05): never wrote to a red-herring service ---
        if action.type == ActionType.SUBMIT_POSTMORTEM and task.red_herrings:
            wrote_herring = any(
                a.get("action_type") in {w.value for w in WRITE_ACTIONS}
                and any(h.lower() in str(a.get("params", {}).get("deployment", "")).lower()
                        for h in task.red_herrings)
                for a in self._action_history
            )
            if not wrote_herring:
                breakdown["avoided_red_herring"] = 0.05

        # --- evidence_diversity_bonus (+0.05): \u22654 distinct evidence sources ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            n_src = (
                int(bool(self._inspected_logs))
                + int(self._inspected_metrics)
                + int(bool(self._inspected_deps))
                + int(self._inspected_traces)
                + int(any(k.startswith("exec:") for k in self._inspected_logs))
            )
            if n_src >= 4:
                breakdown["evidence_diversity_bonus"] = 0.05

        # --- mitigation_target_match (+0.04): write target equals correct service ---
        correct_for_task = CORRECT_SERVICES.get(task_id)
        if (correct_for_task
                and action.type in WRITE_ACTIONS
                and action.type != ActionType.DELETE_CHAOS_EXPERIMENT):
            target_deploy = action.params.get("deployment", "")
            if target_deploy == correct_for_task:
                breakdown["mitigation_target_match"] = 0.04

        # --- chaos_detection_bonus (+0.04): probed chaos for a chaos task ---
        if (task.chaos_experiment_name
                and action.type == ActionType.EXEC_KUBECTL):
            cmd = str(action.params.get("command", "")).lower()
            if "chaos" in cmd or "podchaos" in cmd or "networkchaos" in cmd:
                breakdown["chaos_detection_bonus"] = 0.04

        # --- timely_acknowledgment (+0.03): first action within 2 steps ---
        if self._step_count <= 1 and action.type in READ_ACTIONS:
            breakdown["timely_acknowledgment"] = 0.03

        # --- summary_brevity_penalty (-0.02): postmortem summary is empty ---
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            summary_text = str(action.params.get("summary", "")).strip()
            if len(summary_text) < 20:
                breakdown["summary_brevity_penalty"] = -0.02

        # =============================================================
        # ROUND-4 REWARDS \u2014 dense, non-obvious AWS-aware signals.
        # Goal: push the actor to PICK THE RIGHT FORENSIC TOOL FOR THE
        # SYMPTOMS rather than fall back on logs+kubectl every time.
        # All values are deterministic and small (\u22640.10).
        # =============================================================

        aws_inspected  = getattr(self, "_aws_inspected",  set())
        aws_remediated = getattr(self, "_aws_remediated", set())

        # Tasks where each forensic tool yields the *non-obvious* clue.
        # These are intentionally not 1:1 with task ids \u2014 the agent has
        # to learn the mapping by trial.
        cloudtrail_tasks       = {"task14", "task15", "task19", "task20",
                                  "task23"}
        resource_policy_tasks  = {"task14", "task15", "task20", "task23"}
        quota_tasks            = {"task13", "task16", "task18"}
        secret_rotation_tasks  = {"task14", "task23"}
        iam_sim_tasks          = {"task15", "task20", "task23"}
        insights_tasks         = {"task9", "task12", "task16", "task17",
                                  "task22"}
        dlq_inspect_tasks      = {"task12", "task20"}
        ssm_diff_tasks         = {"task17", "task7"}
        sfn_exec_tasks         = {"task21"}

        # ---- 1. cloudtrail_for_drift_task (+0.07) ------------------------
        # Used cloudtrail on a task whose root cause is an operator action.
        if (action.type == ActionType.CHECK_CLOUDTRAIL_EVENTS
                and task_id in cloudtrail_tasks
                and "cloudtrail_first_use" not in breakdown):
            breakdown["cloudtrail_for_drift_task"] = 0.07
        # ---- 2. cloudtrail_irrelevant_penalty (-0.03) -------------------
        elif (action.type == ActionType.CHECK_CLOUDTRAIL_EVENTS
              and task_id not in cloudtrail_tasks):
            breakdown["cloudtrail_irrelevant_penalty"] = -0.03

        # ---- 3. policy_inspection_for_drift (+0.06) ---------------------
        if (action.type == ActionType.DESCRIBE_RESOURCE_POLICY
                and task_id in resource_policy_tasks):
            breakdown["policy_inspection_for_drift"] = 0.06

        # ---- 4. quota_check_for_throttle_task (+0.07) -------------------
        if (action.type == ActionType.GET_QUOTA_USAGE
                and task_id in quota_tasks):
            breakdown["quota_check_for_throttle_task"] = 0.07

        # ---- 5. secret_rotation_inspected_for_secret_task (+0.06) -------
        if (action.type == ActionType.CHECK_SECRET_ROTATION
                and task_id in secret_rotation_tasks):
            breakdown["secret_rotation_inspected_for_secret_task"] = 0.06

        # ---- 6. iam_simulation_used_for_iam_task (+0.06) ---------------
        if (action.type == ActionType.VALIDATE_IAM_PERMISSION
                and task_id in iam_sim_tasks):
            breakdown["iam_simulation_used_for_iam_task"] = 0.06

        # ---- 7. insights_query_used (+0.05) ----------------------------
        if (action.type == ActionType.ANALYZE_CLOUDWATCH_INSIGHTS
                and task_id in insights_tasks):
            breakdown["insights_query_used"] = 0.05

        # ---- 8. dlq_inspect_before_purge (+0.06) -----------------------
        if (action.type == ActionType.PURGE_QUEUE
                and "dlq_inspect" in aws_inspected):
            breakdown["dlq_inspect_before_purge"] = 0.06
        # ---- 9. blind_purge_penalty (-0.10) ----------------------------
        if (action.type == ActionType.PURGE_QUEUE
                and "dlq_inspect" not in aws_inspected):
            breakdown["blind_purge_penalty"] = -0.10

        # ---- 10. ssm_diff_for_config_task (+0.06) ----------------------
        if (action.type == ActionType.DIFF_CONFIG_VERSIONS
                and task_id in ssm_diff_tasks):
            breakdown["ssm_diff_for_config_task"] = 0.06

        # ---- 11. sfn_exec_for_sfn_task (+0.07) -------------------------
        if (action.type == ActionType.DESCRIBE_STATE_MACHINE_EXEC
                and task_id in sfn_exec_tasks):
            breakdown["sfn_exec_for_sfn_task"] = 0.07

        # ---- 12. forensic_chain_bonus (+0.08) -------------------------
        # Agent ran \u22653 distinct AWS forensic actions in one episode.
        if (action.type == ActionType.SUBMIT_POSTMORTEM
                and len(aws_inspected) >= 3):
            breakdown["forensic_chain_bonus"] = min(0.08,
                                                    0.025 * len(aws_inspected))

        # ---- 13. minimal_invasive_recovery (+0.05) ---------------------
        # Used a soft AWS remediation (lambda invoke / rotate / enable rule)
        # instead of the heavy hammer (rollback / restart) when softer was
        # appropriate.
        soft = {"lambda", "secret_rotation", "enable_rule"}
        if (action.type == ActionType.SUBMIT_POSTMORTEM
                and aws_remediated & soft
                and not any(a.get("action_type") in
                            {"rollback_deployment", "restart_pods"}
                            for a in self._action_history)):
            breakdown["minimal_invasive_recovery"] = 0.05

        # ---- 14. evidence_supports_root_cause (+0.06) ------------------
        # The submitted root cause names a CloudTrail/quota/policy/dlq
        # concept that the agent ACTUALLY inspected this episode.
        if action.type == ActionType.SUBMIT_POSTMORTEM:
            rc = str(action.params.get("root_cause", "")).lower()
            link = {
                "cloudtrail":   "cloudtrail" in rc or "scheduled_for_deletion" in rc,
                "resource_policy": "policy" in rc or "denies" in rc,
                "quota":        "quota" in rc or "throttl" in rc or "limit" in rc,
                "secret_rotation": "rotation" in rc or "stale" in rc,
                "iam_sim":      "iam" in rc or "least-privilege" in rc,
                "insights":     "log" in rc or "pattern" in rc,
                "dlq_inspect":  "dlq" in rc or "dead-letter" in rc or "poison" in rc,
                "ssm_diff":     "config" in rc or "ssm" in rc or "parameter" in rc,
                "sfn_exec":     "state" in rc or "execution" in rc or "saga" in rc,
            }
            matches = sum(1 for k, v in link.items()
                          if v and k in aws_inspected)
            if matches >= 1:
                breakdown["evidence_supports_root_cause"] = round(
                    min(0.08, 0.04 * matches), 3)

        # ---- 15. obvious_action_penalty (-0.04) ------------------------
        # First two actions on an AWS task were both query_logs+kubectl
        # without ever consulting any AWS-specific tool. Pushes the agent
        # to LOOK before reaching for k8s primitives.
        if (action.type in WRITE_ACTIONS
                and self._step_count >= 2
                and aws_hints
                and not aws_inspected
                and not self._inspected_metrics):
            breakdown["obvious_action_penalty"] = -0.04

        # ---- 16. correct_runbook_lambda (+0.07) ------------------------
        if (action.type == ActionType.INVOKE_LAMBDA
                and "runbook" in str(action.params.get("function_name", "")).lower()
                and task_id in {"task1", "task2", "task11"}):
            breakdown["correct_runbook_lambda"] = 0.07

        # ---- 17. enable_rule_after_disable (+0.06) ---------------------
        if (action.type == ActionType.ENABLE_EVENTBRIDGE_RULE
                and task_id == "task20"):
            breakdown["enable_rule_after_disable"] = 0.06

        # ---- 18. tool_diversity_bonus (+0.04 cap) ----------------------
        # Per-step micro-bonus for using a forensic tool the agent has not
        # used yet this episode.
        forensic_types = {ActionType.CHECK_CLOUDTRAIL_EVENTS,
                          ActionType.DESCRIBE_RESOURCE_POLICY,
                          ActionType.GET_QUOTA_USAGE,
                          ActionType.CHECK_SECRET_ROTATION,
                          ActionType.VALIDATE_IAM_PERMISSION,
                          ActionType.ANALYZE_CLOUDWATCH_INSIGHTS,
                          ActionType.INSPECT_DLQ_MESSAGES,
                          ActionType.DIFF_CONFIG_VERSIONS,
                          ActionType.DESCRIBE_STATE_MACHINE_EXEC}
        if action.type in forensic_types:
            already_used = sum(1 for a in self._action_history
                               if a.get("action_type") == action.type.value)
            if already_used == 0:                     # first time this episode
                breakdown["tool_diversity_bonus"] = 0.04

        # ---- 19. wrong_tool_for_obvious_clue (-0.03) -------------------
        # If the alerts already mention "Throttl" / "PendingDeletion" /
        # "ExecutionFailed" but the agent fires query_logs as its FIRST
        # forensic action instead of the dedicated AWS tool.
        if (self._step_count == 0
                and action.type == ActionType.QUERY_LOGS
                and obs.active_alerts):
            alert_text = " ".join(a.alert_name + " " +
                                  " ".join(a.annotations.values())
                                  for a in obs.active_alerts).lower()
            if any(kw in alert_text for kw in ("throttl", "pendingdeletion",
                                               "executionfailed",
                                               "schemanotfound")):
                breakdown["wrong_tool_for_obvious_clue"] = -0.03

        # ---- 20. cross_aws_correlation (+0.05) -------------------------
        # Used \u22652 different AWS forensic tools that target the SAME
        # resource within the episode (cloudtrail+policy on KMS, etc).
        if (action.type == ActionType.SUBMIT_POSTMORTEM
                and len({"cloudtrail", "resource_policy"} & aws_inspected) == 2):
            breakdown["cross_aws_correlation"] = 0.05

        # ---- 21. simulator-mode breadcrumbs ----------------------------
        # When a sim_* scenario is active, fold the simulator's physics
        # signals into the reward. These compose with the K8s-shaped
        # rewards above; magnitudes stay within the \u00b10.10 envelope per
        # category to respect the project-wide cap.
        if getattr(self, "_sim_active", False) and self._sim_state is not None:
            sim = self._sim_state
            # Investigation bonus: every NEW physics-inspect tag the
            # simulator marks (heap_dump, runbook, hc_paused, …) is worth
            # +0.02, capped at +0.10 / step.
            sim_inspect_tags = sim.inspected - getattr(self, "_seen_sim_inspects", set())
            if sim_inspect_tags:
                bonus = min(0.10, 0.02 * len(sim_inspect_tags))
                breakdown["sim_investigation"] = bonus
                self._seen_sim_inspects = set(sim.inspected)
            # Mitigation: simulator says the world is healed -> +0.10.
            if sim.mitigation_applied and not getattr(self, "_sim_mitigation_credited", False):
                breakdown["sim_mitigation"] = 0.10
                self._sim_mitigation_credited = True
            # Blast radius: brute-force action knocked over N services -> -0.01 / hop.
            blast = sim.blast_ledger.total_radius()
            seen_blast = getattr(self, "_seen_blast", 0)
            if blast > seen_blast:
                breakdown["sim_blast_penalty"] = -min(0.10, 0.01 * (blast - seen_blast))
                self._seen_blast = blast
            # Runbook trap: the agent crossed a tripwire -> hard -0.10.
            tripped = any(t.triggered for t in sim.runbook_traps)
            if tripped and not getattr(self, "_sim_trap_credited", False):
                breakdown["sim_runbook_trap"] = -0.10
                self._sim_trap_credited = True
            # Trolley trade-off: subtract the cost only once on resolve.
            if sim.trolley.chosen_path and not getattr(self, "_sim_trolley_credited", False):
                cost = sim.trolley.cost()
                breakdown["sim_trolley_cost"] = -min(0.10, 0.10 * cost)
                self._sim_trolley_credited = True
            # K8s controller restart that destroyed evidence -> -0.02 each.
            n_restarts = len(sim.controller.restart_log)
            seen_kicks = getattr(self, "_seen_k8s_kicks", 0)
            if n_restarts > seen_kicks:
                breakdown["sim_controller_kick"] = -min(0.10,
                    0.02 * (n_restarts - seen_kicks))
                self._seen_k8s_kicks = n_restarts

        total = sum(breakdown.values())
        self._last_reward_breakdown = breakdown
        self._last_action_correct = breakdown.get("correct_mitigation", 0) > 0

        return total

    # ------------------------------------------------------------------
    # Holistic Episode Grading
    # ------------------------------------------------------------------

    def grade_episode(self) -> dict[str, float]:
        """Grade the full episode holistically (separate from per-step reward).
        Returns a score dict with component scores and total in [0.001, 0.999].
        """
        scores: dict[str, float] = {}
        if not self._task or not self._done:
            return {"total": 0.001, "error": "episode not complete"}

        task = self._task

        # 1. Investigation thoroughness (0-0.25)
        investigation_score = 0.0
        if len(self._inspected_logs) > 0:
            investigation_score += 0.05
        if len(self._inspected_logs) >= 2:
            investigation_score += 0.05
        if self._inspected_metrics:
            investigation_score += 0.05
        if len(self._inspected_deps) > 0:
            investigation_score += 0.05
        if self._inspected_traces:
            investigation_score += 0.05
        scores["investigation"] = investigation_score

        # 2. Correct mitigation (0 or 0.25)
        scores["mitigation"] = 0.25 if self._mitigation_applied else 0.0

        # 3. Root cause identification (0 or 0.25)
        scores["root_cause"] = 0.25 if self._root_cause_identified else 0.0

        # 4. Efficiency (0-0.15) — faster is better
        steps = self._step_count
        if steps <= 5:
            scores["efficiency"] = 0.15
        elif steps <= 10:
            scores["efficiency"] = 0.10
        elif steps <= 15:
            scores["efficiency"] = 0.05
        else:
            scores["efficiency"] = 0.0

        # 5. No unnecessary damage (0-0.10)
        wrong_actions = sum(1 for a in self._action_history
                          if a.get("reward", 0) < -0.1)
        if wrong_actions == 0:
            scores["no_damage"] = 0.10
        elif wrong_actions == 1:
            scores["no_damage"] = 0.05
        else:
            scores["no_damage"] = 0.0

        raw_total = sum(scores.values())
        scores["total"] = float(max(0.001, min(0.999, raw_total)))
        self._episode_scores = scores
        return scores

    # ------------------------------------------------------------------
    # Kubernetes Helpers (real cluster)
    # ------------------------------------------------------------------

    def _init_k8s(self) -> None:
        if self._k8s_apps is None:
            try:
                from kubernetes import client, config
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()
                self._k8s_apps = client.AppsV1Api()
                self._k8s_core = client.CoreV1Api()
            except ImportError:
                logger.warning("kubernetes package not installed; using mock mode")
                self._mock = True

    async def _get_pod_statuses(self) -> list[dict[str, Any]]:
        self._init_k8s()
        if self._mock or self._k8s_core is None:
            return []
        try:
            pods = self._k8s_core.list_namespaced_pod("ecommerce")
            return [
                {"name": p.metadata.name, "status": p.status.phase, "ready": all(
                    c.ready for c in (p.status.container_statuses or [])
                )}
                for p in pods.items
            ]
        except Exception as e:
            logger.warning("Failed to list pods: %s", e)
            return []

    async def _k8s_rollback(self, deployment: str, namespace: str) -> str:
        self._init_k8s()
        if self._k8s_apps is None:
            return "ERROR: Kubernetes client not available."
        try:
            # Trigger rollback by patching with rollout undo annotation
            body = {"spec": {"template": {"metadata": {"annotations": {
                "kubectl.kubernetes.io/rollback-to": "0"
            }}}}}
            self._k8s_apps.patch_namespaced_deployment(deployment, namespace, body)
            correct = CORRECT_SERVICES.get(self._task.task_id if self._task else "")
            if deployment == correct:
                self._mitigation_applied = True
            return f"Rolled back deployment/{deployment} in namespace {namespace}."
        except Exception as e:
            return f"Rollback failed: {e}"

    async def _k8s_restart(self, deployment: str, namespace: str) -> str:
        self._init_k8s()
        if self._k8s_apps is None:
            return "ERROR: Kubernetes client not available."
        try:
            now = datetime.now(timezone.utc).isoformat()
            body = {"spec": {"template": {"metadata": {"annotations": {
                "kubectl.kubernetes.io/restartedAt": now
            }}}}}
            self._k8s_apps.patch_namespaced_deployment(deployment, namespace, body)
            return f"Restarted pods for deployment/{deployment} in namespace {namespace}."
        except Exception as e:
            return f"Restart failed: {e}"

    async def _k8s_scale(self, deployment: str, replicas: int, namespace: str) -> str:
        self._init_k8s()
        if self._k8s_apps is None:
            return "ERROR: Kubernetes client not available."
        try:
            body = {"spec": {"replicas": replicas}}
            self._k8s_apps.patch_namespaced_deployment(deployment, namespace, body)
            return f"Scaled deployment/{deployment} to {replicas} replicas."
        except Exception as e:
            return f"Scale failed: {e}"

    async def _k8s_config_patch(self, deployment: str, env_var: str, value: str, namespace: str) -> str:
        self._init_k8s()
        if self._k8s_apps is None:
            return "ERROR: Kubernetes client not available."
        try:
            dep = self._k8s_apps.read_namespaced_deployment(deployment, namespace)
            containers = dep.spec.template.spec.containers
            for container in containers:
                if container.env is None:
                    container.env = []
                found = False
                for env in container.env:
                    if env.name == env_var:
                        env.value = value
                        found = True
                        break
                if not found:
                    from kubernetes.client import V1EnvVar
                    container.env.append(V1EnvVar(name=env_var, value=value))
            self._k8s_apps.replace_namespaced_deployment(deployment, namespace, dep)
            return f"Patched deployment/{deployment}: {env_var}={value}."
        except Exception as e:
            return f"Config patch failed: {e}"

    # ------------------------------------------------------------------
    # Cluster Lifecycle
    # ------------------------------------------------------------------

    async def _reset_cluster(self) -> None:
        """Clean up any previous faults."""
        try:
            experiments = await self._chaos.list_experiments()
            for exp in experiments:
                eid = exp.get("uid", exp.get("id", ""))
                if eid:
                    await self._chaos.delete_experiment(eid)
        except Exception as e:
            logger.warning("Failed to clean chaos experiments: %s", e)

    async def _wait_for_baseline(self, timeout: int = 120) -> None:
        """Wait until error rate drops below 1%."""
        for _ in range(timeout // 5):
            try:
                rate = await self._prom.query_instant(
                    'sum(rate(http_requests_total{namespace="ecommerce",status_code=~"5.."}[2m])) / '
                    'sum(rate(http_requests_total{namespace="ecommerce"}[2m]))'
                )
                if rate < 0.01:
                    return
            except Exception:
                pass
            await asyncio.sleep(5)
        raise RuntimeError("Baseline error rate did not drop below 1% within timeout")

    async def _inject_fault(self, task_id: str) -> None:
        """Inject the fault for the given task."""
        chaos_dir = Path(__file__).resolve().parent.parent.parent / "chaos"
        if task_id == "task1":
            yaml_path = chaos_dir / "easy-redis-latency.yaml"
            await self._apply_chaos_yaml(yaml_path)
        elif task_id == "task2":
            yaml_path = chaos_dir / "medium-payments-memory-stress.yaml"
            await self._apply_chaos_yaml(yaml_path)
        elif task_id == "task3":
            # Bad deployment — patch image tag
            if not self._mock:
                await self._k8s_config_patch(
                    "payments-api", "SERVICE_VERSION", "2.3.2-buggy", "ecommerce"
                )

    async def _apply_chaos_yaml(self, yaml_path: Path) -> None:
        try:
            import yaml as pyyaml
            with open(yaml_path) as f:
                experiment = pyyaml.safe_load(f)
            await self._chaos.create_experiment(experiment)
        except Exception as e:
            logger.warning("Failed to apply chaos experiment from %s: %s", yaml_path, e)
