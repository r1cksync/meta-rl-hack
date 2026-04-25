"""Build the showcase data bundle consumed by /showcase.

Reads:
    * kaggle ran notebooks/shard {1,2,3}/training_kaggle{N}.json
    * rl-agent/scenarios/sim/{easy,medium,hard}/*.json
    * rl-agent/scenarios/*.json (curated)

Writes:
    * rl-agent/showcase_data.json

The bundle is deliberately *flat* and aggressive about size reduction so the
single-page dashboard can fetch and render the whole thing without paging.
Total size target: ~1-2 MB.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCEN_ROOT = ROOT / "rl-agent" / "scenarios"
SIM_ROOT = SCEN_ROOT / "sim"
TRAIN_ROOT = ROOT / "kaggle ran notebooks"
OUT_PATH = ROOT / "rl-agent" / "showcase_data.json"


# --------------------------------------------------------------------------- #
# Scenarios                                                                    #
# --------------------------------------------------------------------------- #

# ID prefix -> human-readable category + intention behind designing it.
CATEGORY_INTENT = {
    "sim_easy_lambda_throttle": (
        "Lambda Throttling",
        "easy",
        "Concurrency hitting the reserved cap. Teaches the agent to recognise "
        "ThrottledRequests / ConcurrentExecutions and raise reserved-concurrency.",
    ),
    "sim_easy_ddb_throttle": (
        "DynamoDB Throttling",
        "easy",
        "Write-capacity exhaustion on a single hot table. Teaches scale-up of "
        "provisioned WCU and recognising ProvisionedThroughputExceededException.",
    ),
    "sim_easy_apigw": (
        "API Gateway 5xx",
        "easy",
        "Origin integration timeout. Forces inspection of integration logs vs. "
        "access logs to localise the problem to the upstream Lambda or VPC link.",
    ),
    "sim_easy_eb": (
        "EventBridge Failure",
        "easy",
        "Rule mis-routes events to dead targets. Teaches the agent to inspect "
        "FailedInvocations metric and rule patterns.",
    ),
    "sim_med_eb_lambda": (
        "EventBridge → Lambda Chain",
        "medium",
        "Two-hop chain where EventBridge invokes a throttled Lambda. Forces "
        "cross-service correlation: rule + invocation + throttle metrics.",
    ),
    "sim_med_apigw_lambda": (
        "API Gateway → Lambda Chain",
        "medium",
        "Cold-start cascading 5xx. Trains compound diagnosis: latency + error "
        "rate + Lambda init duration in one trace.",
    ),
    "sim_med_sfn_lambda": (
        "Step Functions → Lambda",
        "medium",
        "State-machine exit branches mishandle Lambda errors. Teaches reading "
        "execution history and distinguishing Catch vs. Retry semantics.",
    ),
    "sim_med_ddb_lambda": (
        "DynamoDB Stream Stall",
        "medium",
        "Trigger Lambda hits provisioned cap; iterator-age climbs. Trains the "
        "agent to follow the stream from producer to consumer.",
    ),
    "sim_hard_iam_chain": (
        "IAM Permission Chain",
        "hard",
        "Missing assume-role policy two services deep. Trains chained-permission "
        "diagnosis without obvious AccessDenied at the surface.",
    ),
    "sim_hard_apigw_chain": (
        "API Gateway Multi-Stage",
        "hard",
        "Stage-variable misconfiguration cascades through 3 services. Trains "
        "the agent to compare stages and identify drift.",
    ),
    "sim_hard_ddb_chain": (
        "DynamoDB Cascade",
        "hard",
        "Hot partition + GSI throttle. Teaches identifying the underlying "
        "partition key skew rather than just scaling.",
    ),
    "sim_advanced_cascade": (
        "Cascading Failure",
        "hard",
        "Real cause is buried under a noisy symptom (e.g. frontend 504 hides "
        "users_db memory leak). Trains DAG traversal + 'don't trust the loud "
        "alert' instinct.",
    ),
    "sim_advanced_runbook_trap": (
        "Runbook Trap",
        "hard",
        "Standard runbook would make things worse (e.g. restart pod = wipe "
        "evidence). Trains deviating from default playbook based on context.",
    ),
    "sim_advanced_trolley": (
        "Trolley Problem",
        "hard",
        "Limited time-window — restoring backup vs. failing over both have "
        "downsides. Trains explicit trade-off reasoning under pressure.",
    ),
    "sim_advanced_saboteur_duel": (
        "Adversarial Saboteur",
        "hard",
        "Saboteur agent re-injects faults on a cooldown. Trains persistent "
        "remediation: one fix is not enough.",
    ),
    "sim_advanced_slack_redherring": (
        "Slack Red Herring",
        "hard",
        "Noisy Slack channel actively misdirects. Trains weighting metrics "
        "over chatter.",
    ),
    "sim_gen_app_leak": (
        "Generated · App Memory Leak",
        "medium",
        "Procedurally-generated memory-leak scenarios across all services. "
        "Forces generalisation across the topology rather than memorising "
        "specific service names.",
    ),
    "sim_gen_db_duel": (
        "Generated · DB Failover Duel",
        "medium",
        "Two databases racing during failover; only one is the real cause. "
        "Trains discriminating primary vs. replica drift.",
    ),
    "sim_gen_redherring": (
        "Generated · Red Herring",
        "medium",
        "A loud-but-irrelevant alert plus a quiet root cause. Trains "
        "ignoring eye-catching distractors.",
    ),
    "sim_gen_cascade": (
        "Generated · Cascade",
        "medium",
        "Random root-cause node propagating through the DAG. Trains DAG-walk "
        "from symptom upstream.",
    ),
    "sim_gen_cache_warm": (
        "Generated · Cache Cold-Start",
        "medium",
        "Fresh cache miss-storm under load. Trains rate-limit + warmup vs. "
        "naive scaling.",
    ),
    "sim_gen_peak": (
        "Generated · Peak Traffic",
        "medium",
        "Traffic profile spike beyond capacity. Trains autoscale tuning "
        "without over-provisioning.",
    ),
    "sim_gen_restore": (
        "Generated · DB Restore",
        "medium",
        "Schema drift after restore. Trains catching subtle integrity issues "
        "before re-pointing traffic.",
    ),
}


def categorise(task_id: str) -> tuple[str, str, str]:
    """Return (category, difficulty, intention) for a given task id."""
    for prefix, info in CATEGORY_INTENT.items():
        if task_id.startswith(prefix):
            return info
    # Fallback by id prefix tier word.
    for tier in ("easy", "med", "hard", "advanced", "gen"):
        if f"_{tier}_" in task_id or task_id.startswith(f"sim_{tier}"):
            return (
                f"Other · {tier.capitalize()}",
                "hard" if tier in ("hard", "advanced") else "medium" if tier == "med" else "easy",
                "Uncategorised scenario.",
            )
    return ("Other", "easy", "Uncategorised scenario.")


def load_scenario(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    tid = d.get("task_id") or d.get("id") or path.stem
    chain = d.get("correct_action_chain") or []
    actions = []
    for step in chain[:8]:  # cap to keep payload small
        if isinstance(step, dict):
            actions.append(
                {
                    "id": step.get("id") or step.get("action") or "?",
                    "params": step.get("params", {}),
                }
            )
    cat, diff_default, intent = categorise(tid)
    diff = d.get("difficulty") or diff_default
    return {
        "id": tid,
        "title": d.get("title", tid),
        "description": (d.get("description") or "")[:380],
        "difficulty": diff,
        "category": cat,
        "intention": intent,
        "max_steps": d.get("max_steps", 16),
        "target_score": d.get("target_score"),
        "n_actions": len(chain),
        "actions": actions,
    }


def collect_scenarios() -> list[dict]:
    out = []
    for tier in ("easy", "medium", "hard"):
        for p in sorted((SIM_ROOT / tier).glob("*.json")):
            sc = load_scenario(p)
            if sc:
                out.append(sc)
    return out


# --------------------------------------------------------------------------- #
# Training shards                                                              #
# --------------------------------------------------------------------------- #


def load_shard(n: int) -> dict:
    p = TRAIN_ROOT / f"shard {n}" / f"training_kaggle{n}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    cfg = d["config"]
    updates = d["updates"]
    # Per-task aggregate over the whole run.
    task_totals: dict[str, list[float]] = defaultdict(list)
    for u in updates:
        for tid, r in (u.get("rewards_by_task") or {}).items():
            task_totals[tid].append(r)
    task_summary = {
        tid: {
            "visits": len(rs),
            "mean_reward": round(sum(rs) / len(rs), 4),
            "first": round(rs[0], 4),
            "last": round(rs[-1], 4),
        }
        for tid, rs in task_totals.items()
    }
    return {
        "shard": n,
        "config": {
            k: v for k, v in cfg.items() if k != "tasks"  # tasks list = 127 ids; carried separately
        },
        "n_tasks": len(cfg.get("tasks") or task_summary),
        "tasks": cfg.get("tasks") or sorted(task_summary.keys()),
        "n_updates": len(updates),
        "wall_seconds": round(updates[-1]["wall_s"], 1) if updates else 0,
        "trajectory": [
            {
                "u": u["update"],
                "r": u["mean_reward"],
                "v": u["mean_value"],
                "loss": round(u["ppo"]["loss"], 4),
                "kl": round(u["ppo"]["kl"], 4),
                "policy_loss": round(u["ppo"]["policy_loss"], 4),
                "value_err": round(u["ppo"]["value_err"], 3),
                "elapsed": round(u["elapsed_s"], 1),
            }
            for u in updates
        ],
        "task_summary": task_summary,
    }


# --------------------------------------------------------------------------- #
# Compose                                                                      #
# --------------------------------------------------------------------------- #


def build() -> dict:
    scenarios = collect_scenarios()
    shards = [load_shard(n) for n in (1, 2, 3)]

    # Cross-shard task index: which shard owns each task + per-shard reward.
    cross = {}
    for sh in shards:
        for tid, summ in sh["task_summary"].items():
            cross.setdefault(tid, {"shards": []})["shards"].append(
                {"shard": sh["shard"], **summ}
            )

    # Difficulty / category breakdown across all 381 covered tasks.
    cat_counter: Counter = Counter()
    diff_counter: Counter = Counter()
    for sc in scenarios:
        cat_counter[sc["category"]] += 1
        diff_counter[sc["difficulty"]] += 1

    # Reward-progress bands (best-curve for the cleanest plot).
    return {
        "version": 1,
        "summary": {
            "n_tasks_total": len(scenarios),
            "n_tasks_trained": len(cross),
            "n_shards": len(shards),
            "n_updates_per_shard": shards[0]["n_updates"] if shards else 0,
            "rollouts_per_update": shards[0]["config"]["rollouts_per_update"]
            if shards
            else 0,
            "max_steps_per_ep": shards[0]["config"]["max_steps_per_ep"]
            if shards
            else 0,
            "actor": shards[0]["config"]["actor_model"] if shards else "",
            "critic": shards[0]["config"]["critic_model"] if shards else "",
            "lora_r": shards[0]["config"]["lora_r"] if shards else None,
            "lora_alpha": shards[0]["config"]["lora_alpha"] if shards else None,
            "lr": shards[0]["config"]["lr"] if shards else None,
            "gamma": shards[0]["config"]["gamma"] if shards else None,
            "gae_lambda": shards[0]["config"]["gae_lambda"] if shards else None,
            "clip_eps": shards[0]["config"]["clip_eps"] if shards else None,
            "kl_coef": shards[0]["config"]["kl_coef"] if shards else None,
            "wall_seconds_total": sum(sh["wall_seconds"] for sh in shards),
        },
        "category_breakdown": dict(cat_counter),
        "difficulty_breakdown": dict(diff_counter),
        "scenarios": scenarios,
        "shards": shards,
        "cross_shard_index": cross,
    }


def main() -> None:
    bundle = build()
    OUT_PATH.write_text(json.dumps(bundle, separators=(",", ":")))
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"wrote {OUT_PATH.relative_to(ROOT)}  ({size_kb:.1f} KB)")
    print(
        f"  {bundle['summary']['n_tasks_total']} scenarios | "
        f"{bundle['summary']['n_tasks_trained']} covered by training | "
        f"{bundle['summary']['n_shards']} shards"
    )


if __name__ == "__main__":
    main()
