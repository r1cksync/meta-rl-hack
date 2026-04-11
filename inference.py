"""IncidentCommander — Baseline Inference Script (OpenEnv Competition)

Uses the OpenAI Client to run an LLM agent against the IncidentCommanderEnv
and produce reproducible baseline scores on all 3 tasks.

Required env vars:
    API_BASE_URL   — The API endpoint for the LLM (default: https://api.openai.com/v1)
    MODEL_NAME     — The model identifier (default: gpt-4o)
    HF_TOKEN       — Your Hugging Face / API key (mandatory, no default)

Output format (required by competition):
    [START] task=<task_name> env=<benchmark> model=<model_name>
    [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> rewards=<r1,r2,...,rn>

Usage:
    python inference.py                       # run all tasks
    python inference.py --task task1          # run a single task
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Add rl-agent to path so we can import the environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "rl-agent"))

from environment.env import IncidentCommanderEnv
from environment.models import Action, ActionType, Observation

# ---------------------------------------------------------------------------
# Config from environment (competition-mandated variable names)
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o")
HF_TOKEN = os.getenv("HF_TOKEN")

if HF_TOKEN is None:
    raise ValueError("HF_TOKEN environment variable is required")

MAX_STEPS = 20
TEMPERATURE = 0.2
MAX_TOKENS = 1024

ENV_NAME = "incident-commander"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) at AcmeCorp.
You are responding to a live production incident. You have access to the following tools:

- query_logs(service, last_minutes, filter_text?) — Read logs from Loki. SAFE, no blast radius.
- query_metrics(promql, last_minutes?) — Query Prometheus. SAFE.
- get_service_dependencies(service) — Get the dependency graph. SAFE.
- get_trace(trace_id) — Fetch a trace from Jaeger. SAFE.
- rollback_deployment(deployment) — DANGEROUS. Only use when you are confident in root cause.
- restart_pods(deployment) — DANGEROUS. Can cause duplicate events.
- scale_deployment(deployment, replicas) — DANGEROUS. Use with caution.
- apply_config_patch(deployment, env_var, value) — DANGEROUS. Patches env vars.
- delete_chaos_experiment(experiment_name) — Removes an injected fault. Use when you identify chaos.
- submit_postmortem(root_cause, timeline, mitigations, affected_services, recommended_followups) — Terminal action. Episode ends here.

Strategy:
1. Start with read actions (logs, metrics, dependencies) to understand the situation.
2. Form a hypothesis about the root cause.
3. Take targeted write actions only when confident.
4. Submit a postmortem with clear root cause, timeline, and follow-ups.

Time matters — the blast radius grows every step you wait. But wrong actions make things worse.

Respond ONLY with a tool call (function call). Do NOT add explanation text outside of the tool call."""


# ---------------------------------------------------------------------------
# Tools (OpenAI function calling format)
# ---------------------------------------------------------------------------
TOOLS = [
    {"type": "function", "function": {"name": "query_logs", "description": "Read logs from Loki for a specific service. SAFE.", "parameters": {"type": "object", "properties": {"service": {"type": "string", "description": "Service name (e.g. payments-api, inventory-service)"}, "last_minutes": {"type": "integer", "description": "Minutes of logs (default: 5)"}, "filter_text": {"type": "string", "description": "Optional text filter"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "query_metrics", "description": "Execute PromQL query. SAFE.", "parameters": {"type": "object", "properties": {"promql": {"type": "string", "description": "PromQL expression"}, "last_minutes": {"type": "integer", "description": "Time range in minutes"}}, "required": ["promql"]}}},
    {"type": "function", "function": {"name": "get_service_dependencies", "description": "Get dependency graph. SAFE.", "parameters": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "get_trace", "description": "Fetch distributed trace by ID. SAFE.", "parameters": {"type": "object", "properties": {"trace_id": {"type": "string"}}, "required": ["trace_id"]}}},
    {"type": "function", "function": {"name": "rollback_deployment", "description": "Rollback deployment. DANGEROUS.", "parameters": {"type": "object", "properties": {"deployment": {"type": "string"}, "namespace": {"type": "string"}}, "required": ["deployment"]}}},
    {"type": "function", "function": {"name": "restart_pods", "description": "Rolling restart. DANGEROUS.", "parameters": {"type": "object", "properties": {"deployment": {"type": "string"}, "namespace": {"type": "string"}}, "required": ["deployment"]}}},
    {"type": "function", "function": {"name": "scale_deployment", "description": "Scale deployment. DANGEROUS.", "parameters": {"type": "object", "properties": {"deployment": {"type": "string"}, "replicas": {"type": "integer"}, "namespace": {"type": "string"}}, "required": ["deployment", "replicas"]}}},
    {"type": "function", "function": {"name": "apply_config_patch", "description": "Patch env var. DANGEROUS.", "parameters": {"type": "object", "properties": {"deployment": {"type": "string"}, "env_var": {"type": "string"}, "value": {"type": "string"}, "namespace": {"type": "string"}}, "required": ["deployment", "env_var", "value"]}}},
    {"type": "function", "function": {"name": "delete_chaos_experiment", "description": "Delete Chaos Mesh experiment.", "parameters": {"type": "object", "properties": {"experiment_name": {"type": "string"}}, "required": ["experiment_name"]}}},
    {"type": "function", "function": {"name": "submit_postmortem", "description": "Submit incident postmortem. TERMINAL: episode ends.", "parameters": {"type": "object", "properties": {"root_cause": {"type": "string"}, "timeline": {"type": "string"}, "mitigations": {"type": "string"}, "affected_services": {"type": "array", "items": {"type": "string"}}, "recommended_followups": {"type": "string"}}, "required": ["root_cause", "timeline", "mitigations", "affected_services", "recommended_followups"]}}},
]

# ---------------------------------------------------------------------------
# Observation formatter
# ---------------------------------------------------------------------------

def format_observation(obs: Observation) -> str:
    parts = [
        f"=== INCIDENT COMMANDER — Step {obs.step_count} ===",
        f"Blast Radius: {obs.blast_radius_pct:.1f}%  |  Time Pressure: {obs.simulated_time_pressure.value}",
        "",
        "--- ACTIVE ALERTS ---",
    ]
    if obs.active_alerts:
        for a in obs.active_alerts:
            parts.append(f"  [{a.severity.value.upper()}] {a.alert_name} on {a.service}")
            for k, v in a.annotations.items():
                parts.append(f"    {k}: {v}")
    else:
        parts.append("  None.")
    parts.append("")

    parts.append("--- SERVICE HEALTH ---")
    parts.append(f"  {'Service':<25} {'Status':<8} {'Err%':<8} {'P99ms':<8} {'Ready'}")
    for name, svc in obs.service_health.items():
        parts.append(
            f"  {name:<25} {svc.health.value:<8} {svc.error_rate_2m*100:<7.1f}% {svc.p99_latency_ms:<7.0f}ms {svc.ready_replicas}/{svc.replica_count}"
        )
    parts.append("")

    parts.append("--- RECENT LOGS ---")
    if obs.recent_logs:
        for log in obs.recent_logs[:10]:
            parts.append(f"  [{log.level:<5}] [{log.service}] {log.message}")
    else:
        parts.append("  None.")
    parts.append("")

    if obs.last_action_result:
        parts.append("--- LAST ACTION RESULT ---")
        parts.append(obs.last_action_result)
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parse LLM response
# ---------------------------------------------------------------------------

def parse_model_action(response) -> Action | None:
    msg = response.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        try:
            params = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            params = {}
        try:
            return Action(type=ActionType(tc.function.name), params=params)
        except ValueError:
            return None
    # Try parsing from content as fallback
    if msg.content:
        try:
            data = json.loads(msg.content)
            action_name = data.get("action", data.get("name", ""))
            params = data.get("params", data.get("parameters", {}))
            return Action(type=ActionType(action_name), params=params)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# Run episode with competition-mandated output format
# ---------------------------------------------------------------------------

def run_episode(task_id: str) -> tuple[bool, int, list[float]]:
    """Run one episode. Returns (success, steps, rewards_list)."""
    from openai import OpenAI

    client = OpenAI(api_key=HF_TOKEN, base_url=API_BASE_URL)

    env = IncidentCommanderEnv(use_mock=True)
    rewards: list[float] = []
    success = False
    step_num = 0

    # --- [START] ---
    print(f"[START] task={task_id} env={ENV_NAME} model={MODEL_NAME}")

    try:
        obs = env.reset(task_id)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        for step_num in range(1, MAX_STEPS + 1):
            obs_text = format_observation(obs)
            messages.append({"role": "user", "content": obs_text})

            # Call LLM
            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    stream=False,
                )
            except Exception as exc:
                # Fallback: submit a generic postmortem
                action = Action(
                    type=ActionType.SUBMIT_POSTMORTEM,
                    params={
                        "root_cause": "unknown - LLM call failed",
                        "timeline": "investigation could not be completed",
                        "mitigations": "none taken",
                        "affected_services": [],
                        "recommended_followups": "escalate to senior SRE",
                    },
                )
                result = env.step(action)
                action_str = f"submit_postmortem(fallback)"
                error_str = str(exc).replace("\n", " ")[:200]
                print(f"[STEP] step={step_num} action={action_str} reward={result.reward:.2f} done=true error={error_str}")
                rewards.append(result.reward)
                success = result.reward > 0
                break

            action = parse_model_action(response)

            if action is None:
                # No valid action parsed — retry prompt
                content = (response.choices[0].message.content or "")[:200]
                messages.append({"role": "assistant", "content": response.choices[0].message.content or ""})
                messages.append({"role": "user", "content": "Please respond with a tool call to take your next action."})
                print(f"[STEP] step={step_num} action=parse_error reward=0.00 done=false error=null")
                rewards.append(0.0)
                continue

            # Build assistant message with tool calls
            msg = response.choices[0].message
            assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            # Execute action
            result = env.step(action)
            reward = result.reward
            rewards.append(reward)

            action_str = f"{action.type.value}({json.dumps(action.params, separators=(',', ':'))})"
            error_str = "null"
            done_str = "true" if result.done else "false"

            print(f"[STEP] step={step_num} action={action_str} reward={reward:.2f} done={done_str} error={error_str}")

            # Add tool response
            if msg.tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_calls[0].id,
                    "content": result.observation.last_action_result or "Action executed.",
                })

            if result.done:
                success = sum(rewards) > 0
                break

            obs = result.observation

    except Exception as exc:
        error_str = str(exc).replace("\n", " ")[:200]
        print(f"[STEP] step={step_num} action=error reward=0.00 done=true error={error_str}")
        rewards.append(0.0)

    # --- [END] ---
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    success_str = "true" if success else "false"
    print(f"[END] success={success_str} steps={len(rewards)} rewards={rewards_str}")

    return success, len(rewards), rewards


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="IncidentCommander Baseline Inference")
    parser.add_argument("--task", default="all", help="Task ID: task1, task2, task3, or all")
    args = parser.parse_args()

    tasks = ["task1", "task2", "task3"] if args.task == "all" else [args.task]

    for task_id in tasks:
        run_episode(task_id)


if __name__ == "__main__":
    main()
