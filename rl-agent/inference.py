"""IncidentCommander — Baseline Inference Script

Runs an LLM agent against the IncidentCommanderEnv to demonstrate
how the environment works and establish baseline scores for all 3 tasks.

Uses OpenAI-compatible client with environment variables:
  API_BASE_URL   — The API endpoint for the LLM
  MODEL_NAME     — The model identifier to use for inference
  HF_TOKEN       — Auth token (mapped to OPENAI_API_KEY for OpenAI client)

Usage:
    python inference.py --task task1
    python inference.py --task all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from environment.env import IncidentCommanderEnv
from environment.models import Action, ActionType, Observation

# ---------------------------------------------------------------------------
# LLM Client (OpenAI-compatible — required by competition spec)
# ---------------------------------------------------------------------------

def _get_llm_client():
    """Return an OpenAI-compatible client using competition env vars."""
    api_key = os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("API_BASE_URL")
    if not api_key:
        print("ERROR: Set HF_TOKEN or OPENAI_API_KEY environment variable.")
        sys.exit(1)

    try:
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Observation Formatter
# ---------------------------------------------------------------------------

def format_observation(obs: Observation) -> str:
    """Format observation as a clear text block for the LLM."""
    parts = []
    parts.append(f"=== INCIDENT COMMANDER — Step {obs.step_count} ===")
    parts.append(f"Timestamp: {obs.timestamp.isoformat()}")
    parts.append(f"Blast Radius: {obs.blast_radius_pct:.1f}%")
    parts.append(f"Time Pressure: {obs.simulated_time_pressure}")
    parts.append("")

    # Active Alerts
    parts.append("--- ACTIVE ALERTS ---")
    if obs.active_alerts:
        for a in obs.active_alerts:
            parts.append(f"  🚨 [{a.severity.upper()}] {a.alert_name} ({a.service}) — firing since {a.firing_since.isoformat()}")
            for k, v in a.annotations.items():
                parts.append(f"     {k}: {v}")
    else:
        parts.append("  No active alerts.")
    parts.append("")

    # Service Health
    parts.append("--- SERVICE HEALTH ---")
    parts.append(f"  {'Service':<25} {'Status':<8} {'Error%':<8} {'P99ms':<8} {'Ready':<8}")
    parts.append(f"  {'-'*57}")
    for name, svc in obs.service_health.items():
        status_icon = {"green": "✅", "yellow": "⚠️", "red": "🔴"}.get(svc.health.value, "?")
        parts.append(
            f"  {status_icon} {name:<22} {svc.health.value:<8} {svc.error_rate_2m*100:<7.1f}% {svc.p99_latency_ms:<7.0f}ms {svc.ready_replicas}/{svc.replica_count}"
        )
    parts.append("")

    # Recent Logs
    parts.append("--- RECENT LOGS ---")
    if obs.recent_logs:
        for log in obs.recent_logs[:10]:
            parts.append(f"  [{log.timestamp.strftime('%H:%M:%S')}] [{log.level:<5}] [{log.service}] {log.message}")
    else:
        parts.append("  No recent logs.")
    parts.append("")

    if obs.last_action_result:
        parts.append("--- LAST ACTION RESULT ---")
        parts.append(obs.last_action_result)
        parts.append("")

    parts.append(f"Available actions: {', '.join(obs.available_actions)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool Schema Builder
# ---------------------------------------------------------------------------

TOOLS_SCHEMA = [
    {
        "name": "query_logs",
        "description": "Read logs from Loki for a specific service. SAFE — no blast radius impact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name (e.g. payments-api, inventory-service)"},
                "last_minutes": {"type": "integer", "description": "How many minutes of logs to fetch (default: 5)"},
                "filter_text": {"type": "string", "description": "Optional text filter for log lines"},
            },
            "required": ["service"],
        },
    },
    {
        "name": "query_metrics",
        "description": "Execute a PromQL query against Prometheus. SAFE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "promql": {"type": "string", "description": "PromQL query expression"},
                "last_minutes": {"type": "integer", "description": "Time range in minutes (default: 5)"},
            },
            "required": ["promql"],
        },
    },
    {
        "name": "get_service_dependencies",
        "description": "Get the dependency graph for a service. SAFE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name"},
            },
            "required": ["service"],
        },
    },
    {
        "name": "get_trace",
        "description": "Fetch a distributed trace by trace ID from Jaeger. SAFE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "Trace ID to look up"},
            },
            "required": ["trace_id"],
        },
    },
    {
        "name": "rollback_deployment",
        "description": "Rollback a Kubernetes deployment to previous revision. DANGEROUS — only use when confident in root cause.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment": {"type": "string", "description": "Deployment name"},
                "namespace": {"type": "string", "description": "Namespace (default: ecommerce)"},
            },
            "required": ["deployment"],
        },
    },
    {
        "name": "restart_pods",
        "description": "Rolling restart of pods in a deployment. DANGEROUS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment": {"type": "string", "description": "Deployment name"},
                "namespace": {"type": "string", "description": "Namespace (default: ecommerce)"},
            },
            "required": ["deployment"],
        },
    },
    {
        "name": "scale_deployment",
        "description": "Scale a deployment to a specific replica count. DANGEROUS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment": {"type": "string", "description": "Deployment name"},
                "replicas": {"type": "integer", "description": "Target replica count (0-20)"},
                "namespace": {"type": "string", "description": "Namespace (default: ecommerce)"},
            },
            "required": ["deployment", "replicas"],
        },
    },
    {
        "name": "apply_config_patch",
        "description": "Patch a deployment's environment variable. DANGEROUS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment": {"type": "string", "description": "Deployment name"},
                "env_var": {"type": "string", "description": "Environment variable name"},
                "value": {"type": "string", "description": "New value"},
                "namespace": {"type": "string", "description": "Namespace (default: ecommerce)"},
            },
            "required": ["deployment", "env_var", "value"],
        },
    },
    {
        "name": "delete_chaos_experiment",
        "description": "Delete a Chaos Mesh experiment by name. Use when you identify an injected fault.",
        "input_schema": {
            "type": "object",
            "properties": {
                "experiment_name": {"type": "string", "description": "Chaos experiment name to delete"},
            },
            "required": ["experiment_name"],
        },
    },
    {
        "name": "submit_postmortem",
        "description": "Submit the final incident postmortem. TERMINAL ACTION — episode ends after this. Be confident before submitting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "root_cause": {"type": "string", "description": "Root cause of the incident"},
                "timeline": {"type": "string", "description": "Chronological timeline of events"},
                "mitigations": {"type": "string", "description": "Actions taken to mitigate"},
                "affected_services": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of affected service names",
                },
                "recommended_followups": {"type": "string", "description": "Recommended follow-up actions"},
            },
            "required": ["root_cause", "timeline", "mitigations", "affected_services", "recommended_followups"],
        },
    },
]

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) at AcmeCorp.
You are responding to a live production incident. You have access to the following actions:
- query_logs(service, last_minutes, filter_text?) — Read logs from Loki. SAFE, no blast radius.
- query_metrics(promql, last_minutes?) — Query Prometheus. SAFE.
- get_service_dependencies(service) — Get the dependency graph. SAFE.
- get_trace(trace_id) — Fetch a trace from Jaeger. SAFE.
- rollback_deployment(deployment) — DANGEROUS. Only use when you are confident in root cause.
- restart_pods(deployment) — DANGEROUS. Can cause duplicate events.
- scale_deployment(deployment, replicas) — DANGEROUS. Use with caution.
- apply_config_patch(deployment, env_var, value) — DANGEROUS. Patches env vars.
- delete_chaos_experiment(experiment_name) — Removes an injected fault. Use when you identify chaos.
- submit_postmortem(root_cause, timeline, mitigations, affected_services, recommended_followups) — Terminal action.

Strategy:
1. Start with read actions (logs, metrics, dependencies) to understand the situation.
2. Form a hypothesis about the root cause.
3. Take targeted write actions only when confident.
4. Submit a postmortem with clear root cause, timeline, and follow-ups.

Time matters — the blast radius grows every step you wait. But wrong actions make things worse.
Always think step by step. Identify root cause before mitigating."""


def build_tools_schema_openai() -> list[dict]:
    """Convert tools to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS_SCHEMA
    ]


# ---------------------------------------------------------------------------
# Agent Runner
# ---------------------------------------------------------------------------

def parse_action_openai(response) -> Action | None:
    """Extract Action from OpenAI function-call response."""
    msg = response.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        params = json.loads(tc.function.arguments) if tc.function.arguments else {}
        return Action(type=ActionType(tc.function.name), params=params)
    return None


def run_episode(task_id: str, verbose: bool = True) -> float:
    """Run one episode of the IncidentCommander environment with an LLM agent."""
    client = _get_llm_client()
    model_name = os.getenv("MODEL_NAME", "gpt-4o")

    env = IncidentCommanderEnv(use_mock=True)
    obs = env.reset(task_id)
    total_reward = 0.0

    if verbose:
        print(f"\n{'='*60}")
        print(f"  INCIDENT COMMANDER — Task: {task_id}")
        print(f"{'='*60}\n")

    messages = []

    for step in range(20):
        obs_text = format_observation(obs)
        if verbose:
            print(f"\n--- Step {step} ---")
            print(obs_text[:500] + "..." if len(obs_text) > 500 else obs_text)

        messages.append({"role": "user", "content": obs_text})

        # Call LLM via OpenAI-compatible client
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                tools=build_tools_schema_openai(),
                tool_choice="auto",
            )
            msg = response.choices[0].message
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})
            action = parse_action_openai(response)

            # Handle tool call response format
            if action and msg.tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_calls[0].id,
                    "content": "Action submitted to environment.",
                })
        except Exception as e:
            print(f"LLM call failed: {e}")
            break

        if action is None:
            if verbose:
                print("  Agent did not select an action. Ending episode.")
            break

        if verbose:
            print(f"  Action: {action.type.value}({action.params})")

        result = env.step(action)
        total_reward += result.reward

        if verbose:
            print(f"  Reward: {result.reward:+.3f} (cumulative: {total_reward:+.3f})")
            print(f"  Done: {result.done}")

        if result.done:
            break

        obs = result.observation

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Episode complete — Total reward: {total_reward:+.3f}")
        print(f"{'='*60}\n")

    return total_reward


def main():
    parser = argparse.ArgumentParser(description="IncidentCommander Baseline Inference")
    parser.add_argument("--task", default="all", help="Task ID (task1, task2, task3, or all)")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    args = parser.parse_args()

    tasks = ["task1", "task2", "task3"] if args.task == "all" else [args.task]
    results: dict[str, float] = {}

    for task_id in tasks:
        print(f"\n🏥 Running episode for {task_id}...")
        score = run_episode(task_id, verbose=not args.quiet)
        results[task_id] = score

    print("\n" + "=" * 40)
    print("  BASELINE SCORES")
    print("=" * 40)
    for tid, score in results.items():
        print(f"  {tid}: {score:+.3f}")
    print(f"  Average: {sum(results.values()) / len(results):+.3f}")
    print("=" * 40)


if __name__ == "__main__":
    main()
