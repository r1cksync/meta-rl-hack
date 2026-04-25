"""Internal-runbook search — the `search_internal_wiki` mechanic.

We embed a handful of markdown-flavoured runbooks that describe the *correct*
remediation for traps where the obvious action (restart, kill, redeploy)
makes the incident catastrophically worse. The agent that reads the runbook
gets a hint; the agent that brute-forces hits a -1.0 cliff.
"""

from __future__ import annotations

from dataclasses import dataclass


# Each runbook has:
#   - id (slug used for direct lookup)
#   - tags (matched by search keyword)
#   - body (the markdown text the agent reads)
#   - safe_actions: the action ids that the runbook explicitly endorses
#   - forbidden_actions: action ids that, if taken before reading, trigger a
#     catastrophic side effect (CORRUPTED status on the trap target).
RUNBOOKS: dict[str, dict] = {
    "postgres_txid_wraparound": {
        "id": "postgres_txid_wraparound",
        "tags": ["postgres", "rds", "users_db", "transaction id",
                 "wraparound", "vacuum"],
        "title": "Postgres Transaction-ID Wraparound",
        "body": (
            "# Postgres TXID Wraparound — STOP-THE-WORLD\n\n"
            "If you observe `database is not accepting commands` or "
            "`must be vacuumed within 1000000 transactions`, the cluster is "
            "approaching XID wraparound.\n\n"
            "**DO NOT RESTART THE NODE.** A restart in this state will leave "
            "the catalog corrupt and force a 4-hour rebuild.\n\n"
            "Correct procedure:\n"
            "1. Run `vacuum_freeze_db` action against the cluster.\n"
            "2. Wait until `xid_age` drops below 200,000,000.\n"
            "3. Re-enable writes via `resume_writes`.\n"
        ),
        "safe_actions":      ["vacuum_freeze_db", "resume_writes"],
        "forbidden_actions": ["platform.restart_cluster", "rds.reboot",
                              "platform.rollback_deployment"],
    },
    "redis_cache_stampede": {
        "id": "redis_cache_stampede",
        "tags": ["redis", "elasticache", "cache stampede", "session_cache",
                 "cold cache"],
        "title": "Redis Cache Stampede",
        "body": (
            "# Redis Cache Stampede — Warm Before Cutover\n\n"
            "Cold-restarting the cache cluster during peak traffic causes a "
            "stampede: every miss falls through to the primary DB and "
            "saturates connections within ~60s.\n\n"
            "**DO NOT** restart the cache cluster.\n\n"
            "Correct procedure:\n"
            "1. `enable_request_coalescing` on the upstream services.\n"
            "2. `warm_cache` from the snapshot bucket.\n"
            "3. Then `failover_replica` to swap in the warmed instance.\n"
        ),
        "safe_actions":      ["enable_request_coalescing", "warm_cache",
                              "failover_replica"],
        "forbidden_actions": ["platform.restart_cluster", "elasticache.reboot"],
    },
    "kafka_split_brain": {
        "id": "kafka_split_brain",
        "tags": ["kafka", "msk", "split brain", "isr", "controller"],
        "title": "Kafka Split-Brain Recovery",
        "body": (
            "# Kafka Split-Brain — Quorum Repair\n\n"
            "If two brokers both claim controller, ISR shrinks unpredictably "
            "and consumer offsets diverge. Restarting brokers in-place "
            "AMPLIFIES the split.\n\n"
            "Correct procedure:\n"
            "1. `fence_minority_partition` to kill the smaller side.\n"
            "2. `force_controller_election` against the surviving broker.\n"
            "3. Validate ISR with `describe_topics`.\n"
        ),
        "safe_actions":      ["fence_minority_partition",
                              "force_controller_election", "describe_topics"],
        "forbidden_actions": ["platform.restart_cluster", "msk.reboot_broker"],
    },
    "dynamodb_hot_partition": {
        "id": "dynamodb_hot_partition",
        "tags": ["dynamodb", "throttle", "hot partition",
                 "ProvisionedThroughputExceededException"],
        "title": "DynamoDB Hot Partition",
        "body": (
            "# DynamoDB Hot Partition — Add Suffix Salt\n\n"
            "If a single partition key receives >3000 RCU or >1000 WCU, you "
            "get `ProvisionedThroughputExceededException` even though the "
            "table-level capacity is fine.\n\n"
            "Correct procedure:\n"
            "1. `enable_adaptive_capacity` on the table.\n"
            "2. `add_partition_suffix` to the producer config.\n"
            "3. Scale provisioned capacity ONLY after the hot key is split.\n"
        ),
        "safe_actions":      ["enable_adaptive_capacity",
                              "add_partition_suffix", "dynamodb.scale"],
        "forbidden_actions": [],
    },
    "lambda_concurrency_starvation": {
        "id": "lambda_concurrency_starvation",
        "tags": ["lambda", "concurrency", "throttle",
                 "TooManyRequestsException", "reserved"],
        "title": "Lambda Concurrency Starvation",
        "body": (
            "# Lambda Reserved Concurrency = 0\n\n"
            "A reserved concurrency of zero hard-blocks invocations "
            "regardless of account-level concurrency.\n\n"
            "Correct procedure:\n"
            "1. `lambda.describe` to confirm reserved=0.\n"
            "2. `lambda.scale` with capacity >= expected p95 RPS.\n"
            "3. Validate by re-invoking.\n"
        ),
        "safe_actions":      ["lambda.scale", "lambda.invoke"],
        "forbidden_actions": [],
    },
}


def search(query: str, k: int = 3) -> list[dict]:
    """Return up to k runbook stubs whose tags match `query` substring."""
    q = (query or "").lower().strip()
    if not q:
        return []
    hits: list[tuple[int, dict]] = []
    for rb in RUNBOOKS.values():
        score = sum(1 for tag in rb["tags"] if tag.lower() in q
                    or q in tag.lower())
        if q in rb["title"].lower():
            score += 2
        if score > 0:
            hits.append((score, rb))
    hits.sort(key=lambda t: -t[0])
    return [{"id": rb["id"], "title": rb["title"], "score": s}
            for s, rb in hits[:k]]


def fetch(runbook_id: str) -> dict | None:
    return RUNBOOKS.get(runbook_id)


@dataclass
class RunbookTrap:
    """Per-scenario binding: this trap is armed when the simulator scenario
    declares it. Triggers a catastrophic side effect if a forbidden action
    fires before the runbook is read."""
    runbook_id:     str
    target:         str          # topology node that gets corrupted
    armed:          bool = True
    runbook_read:   bool = False
    triggered:      bool = False

    def maybe_trigger(self, action_id: str) -> bool:
        if not self.armed or self.triggered or self.runbook_read:
            return False
        rb = RUNBOOKS.get(self.runbook_id)
        if rb is None:
            return False
        if action_id in rb["forbidden_actions"]:
            self.triggered = True
            return True
        return False
