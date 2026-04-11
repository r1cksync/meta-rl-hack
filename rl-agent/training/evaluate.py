"""Comprehensive Evaluation for IncidentCommander RL Agent.

Loads a trained model and evaluates it across all tasks,
producing detailed accuracy and performance metrics.

Usage:
    cd rl-agent
    python -m training.evaluate                          # evaluate best or final model
    python -m training.evaluate --model checkpoints/enhanced_final_model.zip
    python -m training.evaluate --episodes 50            # more episodes for tighter stats
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

CHECKPOINT_DIR = Path(__file__).resolve().parent.parent / "checkpoints"


def find_best_model() -> Path:
    """Find the best available model checkpoint."""
    candidates = [
        CHECKPOINT_DIR / "best_model.zip",
        CHECKPOINT_DIR / "enhanced_final_model.zip",
        CHECKPOINT_DIR / "final_model.zip",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"No model found in {CHECKPOINT_DIR}. Train first.")


def evaluate_model(model_path: str | None, n_episodes: int = 30):
    try:
        from stable_baselines3 import PPO
    except ImportError:
        print("ERROR: stable-baselines3 not installed.")
        return

    from training.gym_wrapper import IncidentCommanderGymEnv, DISCRETE_ACTIONS

    # Load model
    if model_path:
        mpath = Path(model_path)
    else:
        mpath = find_best_model()
    print(f"Loading model: {mpath}")
    model = PPO.load(str(mpath))

    task_ids = ["task1", "task2", "task3"]
    task_names = {
        "task1": "Redis Connection Pool Exhaustion (Easy)",
        "task2": "Cascading Failure via Payments OOM (Medium)",
        "task3": "Silent Decimal Corruption (Hard)",
    }

    all_results: dict[str, dict] = {}
    overall_rewards = []
    overall_successes = []
    action_counts_global = defaultdict(int)

    for task_id in task_ids:
        rewards = []
        lengths = []
        successes = []
        action_sequences = []
        action_counts = defaultdict(int)
        step_rewards_all = []

        for ep in range(n_episodes):
            env = IncidentCommanderGymEnv(task_ids=[task_id])
            obs, info = env.reset()
            total_reward = 0.0
            steps = 0
            done = False
            ep_actions = []
            ep_step_rewards = []

            while not done and steps < 20:
                action, _ = model.predict(obs, deterministic=True)
                action_idx = int(action)
                action_name = DISCRETE_ACTIONS[action_idx][0]
                obs, reward, terminated, truncated, info = env.step(action_idx)
                total_reward += reward
                steps += 1
                done = terminated or truncated
                ep_actions.append(action_name)
                ep_step_rewards.append(float(reward))
                action_counts[action_name] += 1
                action_counts_global[action_name] += 1

            rewards.append(total_reward)
            lengths.append(steps)
            successes.append(1.0 if total_reward > 0 else 0.0)
            action_sequences.append(ep_actions)
            step_rewards_all.append(ep_step_rewards)

        overall_rewards.extend(rewards)
        overall_successes.extend(successes)

        rewards_arr = np.array(rewards)
        lengths_arr = np.array(lengths)

        # Compute percentiles
        pct_25 = float(np.percentile(rewards_arr, 25))
        pct_50 = float(np.percentile(rewards_arr, 50))  # median
        pct_75 = float(np.percentile(rewards_arr, 75))

        # Most common action sequence
        seq_strs = [" → ".join(s) for s in action_sequences]
        seq_counts = defaultdict(int)
        for s in seq_strs:
            seq_counts[s] += 1
        most_common_seq = max(seq_counts, key=seq_counts.get)
        most_common_freq = seq_counts[most_common_seq] / n_episodes

        all_results[task_id] = {
            "task_name": task_names[task_id],
            "n_episodes": n_episodes,
            "mean_reward": float(np.mean(rewards_arr)),
            "std_reward": float(np.std(rewards_arr)),
            "median_reward": pct_50,
            "min_reward": float(np.min(rewards_arr)),
            "max_reward": float(np.max(rewards_arr)),
            "pct_25_reward": pct_25,
            "pct_75_reward": pct_75,
            "success_rate": float(np.mean(successes)),
            "mean_episode_length": float(np.mean(lengths_arr)),
            "std_episode_length": float(np.std(lengths_arr)),
            "min_episode_length": int(np.min(lengths_arr)),
            "max_episode_length": int(np.max(lengths_arr)),
            "action_distribution": dict(sorted(action_counts.items(), key=lambda x: -x[1])),
            "most_common_sequence": most_common_seq,
            "most_common_seq_frequency": most_common_freq,
        }

    # Compute overall
    overall = {
        "model": str(mpath),
        "total_episodes": n_episodes * len(task_ids),
        "mean_reward": float(np.mean(overall_rewards)),
        "std_reward": float(np.std(overall_rewards)),
        "median_reward": float(np.median(overall_rewards)),
        "success_rate": float(np.mean(overall_successes)),
        "action_distribution": dict(sorted(action_counts_global.items(), key=lambda x: -x[1])),
    }

    # ---- Print report ----
    print(f"\n{'='*70}")
    print(f"  INCIDENTCOMMANDER — MODEL EVALUATION REPORT")
    print(f"  Model: {mpath.name}")
    print(f"  Episodes per task: {n_episodes}")
    print(f"{'='*70}")

    for task_id in task_ids:
        r = all_results[task_id]
        print(f"\n┌─── {task_id}: {r['task_name']} ───")
        print(f"│")
        print(f"│  Reward Metrics:")
        print(f"│    Mean Reward:     {r['mean_reward']:+.4f} ± {r['std_reward']:.4f}")
        print(f"│    Median Reward:   {r['median_reward']:+.4f}")
        print(f"│    Min / Max:       {r['min_reward']:+.4f} / {r['max_reward']:+.4f}")
        print(f"│    25th / 75th pct: {r['pct_25_reward']:+.4f} / {r['pct_75_reward']:+.4f}")
        print(f"│")
        print(f"│  Success Metrics:")
        print(f"│    Success Rate:    {r['success_rate']:.0%} ({int(r['success_rate']*n_episodes)}/{n_episodes})")
        print(f"│")
        print(f"│  Episode Length:")
        print(f"│    Mean Steps:      {r['mean_episode_length']:.1f} ± {r['std_episode_length']:.1f}")
        print(f"│    Min / Max:       {r['min_episode_length']} / {r['max_episode_length']}")
        print(f"│")
        print(f"│  Action Distribution:")
        for action, count in list(r["action_distribution"].items())[:5]:
            pct = count / (r['mean_episode_length'] * n_episodes) * 100
            bar = "█" * int(pct / 2)
            print(f"│    {action:<35} {count:>4}x  {bar}")
        print(f"│")
        print(f"│  Most Common Strategy ({r['most_common_seq_frequency']:.0%} of episodes):")
        # Wrap long sequences
        seq = r["most_common_sequence"]
        if len(seq) > 55:
            parts = seq.split(" → ")
            line = "│    "
            for i, p in enumerate(parts):
                if i > 0:
                    line += " → "
                if len(line) + len(p) > 65:
                    print(line)
                    line = "│      "
                line += p
            print(line)
        else:
            print(f"│    {seq}")
        print(f"└{'─'*68}")

    print(f"\n{'='*70}")
    print(f"  OVERALL SUMMARY")
    print(f"{'='*70}")
    print(f"  Total Episodes:    {overall['total_episodes']}")
    print(f"  Mean Reward:       {overall['mean_reward']:+.4f} ± {overall['std_reward']:.4f}")
    print(f"  Median Reward:     {overall['median_reward']:+.4f}")
    print(f"  Success Rate:      {overall['success_rate']:.0%}")
    print(f"{'='*70}")

    # Save to JSON
    report = {
        "overall": overall,
        "per_task": all_results,
    }
    report_file = CHECKPOINT_DIR / "evaluation_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to {report_file}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate IncidentCommander RL Agent")
    parser.add_argument("--model", default=None, help="Path to model .zip file")
    parser.add_argument("--episodes", type=int, default=30, help="Episodes per task (default: 30)")
    args = parser.parse_args()

    evaluate_model(args.model, args.episodes)
