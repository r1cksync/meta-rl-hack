"""Base-vs-trained evaluation script.

Runs both the base model and a fine-tuned checkpoint through the same set of
adversarial scenarios and prints resolution rate, average grade total, and
steps-to-fix. Used to validate that GRPO training actually helped.

Usage
-----
    python -m rl_agent.eval \\
        --base-model Qwen/Qwen2.5-1.5B-Instruct \\
        --trained-model your-name/incident-commander-grpo \\
        --env-url http://localhost:7860 \\
        --episodes 20

When no models are provided this script evaluates the built-in heuristic
baseline (same strategies as `/baseline`) against all 7 tasks — zero GPU
required. Useful for CI smoke tests.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from dataclasses import dataclass
from typing import Any, Callable

import httpx


log = logging.getLogger(__name__)


@dataclass
class EvalResult:
    label: str
    episodes: int
    solve_rate: float
    avg_grade: float
    avg_cum_reward: float
    avg_steps: float
    per_task: dict[str, float]


class EnvClient:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        self._c = httpx.Client(timeout=60.0)

    def run_baseline(self, task_id: str) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/baseline", json={"task_id": task_id})
        r.raise_for_status()
        return r.json()

    def reset(self, task_id: str, adversarial: bool = False) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/reset", json={"task_id": task_id, "adversarial": adversarial})
        r.raise_for_status()
        return r.json()

    def step(self, action_type: str, params: dict) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/step", json={"action_type": action_type, "params": params})
        r.raise_for_status()
        return r.json()

    def grade(self) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/grader")
        r.raise_for_status()
        return r.json()


def evaluate_heuristic(client: EnvClient, tasks: list[str], episodes_per_task: int) -> EvalResult:
    grades: list[float] = []
    cumulative: list[float] = []
    steps: list[int] = []
    per_task: dict[str, list[float]] = {t: [] for t in tasks}

    for t in tasks:
        for _ in range(episodes_per_task):
            ep = client.run_baseline(t)
            total = float(ep.get("score", ep.get("grade", {}).get("total", 0.0)))
            grades.append(total)
            cumulative.append(float(sum(ep.get("rewards", [])) if isinstance(ep.get("rewards"), list) else 0.0))
            steps.append(len(ep.get("steps", [])))
            per_task[t].append(total)

    return EvalResult(
        label="heuristic",
        episodes=len(grades),
        solve_rate=sum(1 for g in grades if g >= 0.5) / max(1, len(grades)),
        avg_grade=statistics.mean(grades) if grades else 0.0,
        avg_cum_reward=statistics.mean(cumulative) if cumulative else 0.0,
        avg_steps=statistics.mean(steps) if steps else 0.0,
        per_task={t: statistics.mean(v) if v else 0.0 for t, v in per_task.items()},
    )


def evaluate_model(
    client: EnvClient,
    generate: Callable[[str], str],
    label: str,
    tasks: list[str],
    episodes_per_task: int,
    adversarial: bool,
    step_limit: int = 15,
) -> EvalResult:
    from .training.train_grpo import build_prompt, parse_model_output  # local import to keep deps optional

    grades: list[float] = []
    cumulative: list[float] = []
    steps: list[int] = []
    per_task: dict[str, list[float]] = {t: [] for t in tasks}

    for t in tasks:
        for _ in range(episodes_per_task):
            obs = client.reset(t, adversarial=adversarial)
            history: list[dict[str, Any]] = []
            total_reward = 0.0
            done = False
            step_count = 0
            while not done and step_count < step_limit:
                prompt = build_prompt(obs, history)
                text = generate(prompt)
                action = parse_model_output(text)
                try:
                    result = client.step(action.get("action_type", "query_logs"), action.get("params", {}))
                except httpx.HTTPStatusError:
                    break
                total_reward += float(result.get("reward", 0.0))
                history.append({"action_type": action.get("action_type"),
                                "params": action.get("params"),
                                "reward": result.get("reward")})
                obs = result.get("observation", {})
                done = bool(result.get("done", False))
                step_count += 1
            grade = client.grade()
            total = float(grade.get("total", 0.001))
            grades.append(total)
            cumulative.append(total_reward)
            steps.append(step_count)
            per_task[t].append(total)

    return EvalResult(
        label=label, episodes=len(grades),
        solve_rate=sum(1 for g in grades if g >= 0.5) / max(1, len(grades)),
        avg_grade=statistics.mean(grades) if grades else 0.0,
        avg_cum_reward=statistics.mean(cumulative) if cumulative else 0.0,
        avg_steps=statistics.mean(steps) if steps else 0.0,
        per_task={t: statistics.mean(v) if v else 0.0 for t, v in per_task.items()},
    )


def print_result(r: EvalResult) -> None:
    print(f"\n=== {r.label} ===")
    print(f"episodes        : {r.episodes}")
    print(f"solve_rate      : {r.solve_rate:.2%}")
    print(f"avg_grade_total : {r.avg_grade:.3f}")
    print(f"avg_cum_reward  : {r.avg_cum_reward:+.3f}")
    print(f"avg_steps       : {r.avg_steps:.1f}")
    print("per_task:")
    for k, v in r.per_task.items():
        print(f"  {k}: {v:.3f}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env-url", default="http://localhost:7860")
    p.add_argument("--base-model", default=None)
    p.add_argument("--trained-model", default=None)
    p.add_argument("--adversarial", action="store_true")
    p.add_argument("--episodes-per-task", type=int, default=3)
    p.add_argument("--tasks", default="task1,task2,task3,task4,task5,task6,task7")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = EnvClient(args.env_url)
    task_list = args.tasks.split(",")

    # Always evaluate the heuristic — works with zero GPUs.
    heur = evaluate_heuristic(client, task_list, args.episodes_per_task)
    print_result(heur)

    if args.base_model or args.trained_model:
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
            import torch  # type: ignore
        except ImportError:
            raise SystemExit("transformers + torch required for model eval")

        def make_generator(model_id: str):
            tok = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.bfloat16, device_map="auto")
            def _gen(prompt: str) -> str:
                ids = tok(prompt, return_tensors="pt", truncation=True, max_length=3000).to(model.device)
                out = model.generate(**ids, max_new_tokens=256, do_sample=False, temperature=0.7)
                return tok.decode(out[0][ids.input_ids.shape[1]:], skip_special_tokens=True)
            return _gen

        if args.base_model:
            base = evaluate_model(client, make_generator(args.base_model), "base",
                                   task_list, args.episodes_per_task, args.adversarial)
            print_result(base)
        if args.trained_model:
            trained = evaluate_model(client, make_generator(args.trained_model), "trained",
                                      task_list, args.episodes_per_task, args.adversarial)
            print_result(trained)


if __name__ == "__main__":
    main()
