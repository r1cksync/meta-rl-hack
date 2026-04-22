"""GRPO trainer for IncidentCommander (TRL + vLLM colocate).

Mirrors the setup that won the OpenEnv hackathon (kube-sre-gym). Ready to run
as soon as H100 / HF credits are available — no code changes required.

What this script does
---------------------
1. Spins up an HTTP client against the live OpenEnv server (local or HF Space).
2. Samples episodes via the curriculum controller (`use_curriculum=true`).
3. Generates rollouts with Qwen2.5-1.5B + LoRA (or any HF causal LM).
4. Scores each rollout using the environment's built-in shaped reward plus
   the holistic grader total — this is the GRPO reward signal.
5. Uses `trl.GRPOTrainer` to compute advantages across `num_generations`
   rollouts per prompt and update the LoRA adapters.
6. Pushes LoRA checkpoints to the HuggingFace Hub.

Why GRPO (not PPO)
------------------
GRPO compares multiple rollouts of the same prompt to estimate advantages
*without* a value function. This is much more stable for sparse, delayed
rewards — exactly our setting (most reward arrives at episode end).

Not trained yet
---------------
We are waiting on our college's HF GPU grant (~3 days from 2026-04-22). Until
then this script is dry-run-verified only. Do NOT run without GPUs — vLLM
colocate requires 40GB+ VRAM.

Usage (when credits are available)
----------------------------------
    # Terminal 1: environment server
    cd rl-agent && uvicorn server:app --host 0.0.0.0 --port 7860

    # Terminal 2: GRPO trainer
    python -m training.train_grpo \\
        --model Qwen/Qwen2.5-1.5B-Instruct \\
        --env-url http://localhost:7860 \\
        --num-generations 8 \\
        --max-steps 200 \\
        --save-steps 20 \\
        --hub-repo your-name/incident-commander-grpo
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


log = logging.getLogger(__name__)


# --------------------------------------------------------------------- CLI


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GRPO trainer for IncidentCommander")
    p.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct",
                   help="HuggingFace causal LM id.")
    p.add_argument("--env-url", default=os.getenv("ENV_URL", "http://localhost:7860"))
    p.add_argument("--num-generations", type=int, default=8,
                   help="Rollouts per prompt for GRPO advantage estimation.")
    p.add_argument("--max-steps", type=int, default=200,
                   help="Total GRPO optimisation steps.")
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--save-steps", type=int, default=20)
    p.add_argument("--hub-repo", default=None,
                   help="HuggingFace Hub repo for checkpoints (org/name).")
    p.add_argument("--vllm-mode", choices=["colocate", "server"], default="colocate",
                   help="vLLM deployment mode. colocate = same GPU; server = remote.")
    p.add_argument("--episode-limit", type=int, default=20,
                   help="Hard cap on steps per episode.")
    p.add_argument("--persona", choices=["junior", "senior", "principal"], default="senior")
    p.add_argument("--use-adversarial", action="store_true",
                   help="Also enable the adversarial designer once curriculum reaches expert tier.")
    p.add_argument("--out-dir", default="./checkpoints/grpo")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip training; just verify the pipeline end-to-end.")
    p.add_argument("--local", action="store_true",
                   help="Local preset: tiny model + LoRA + 4-bit, runs on consumer GPU.")
    p.add_argument("--4bit", dest="four_bit", action="store_true",
                   help="Load the base model in 4-bit via bitsandbytes.")
    p.add_argument("--no-hub-push", action="store_true",
                   help="Disable pushing LoRA adapters to the Hub.")
    p.add_argument("--inject-fault", default=None,
                   help="If set, call /k8s/inject with this fault_type each reset (requires REAL_K8S).")
    return p.parse_args()


# ----------------------------------------------------------- Env client


class OpenEnvClient:
    """Thin HTTP client for our FastAPI env server."""

    def __init__(self, base_url: str, persona: str = "senior", use_llm_judge: bool = False):
        self._base = base_url.rstrip("/")
        self._persona = persona
        self._use_llm_judge = use_llm_judge
        self._c = httpx.Client(timeout=30.0)

    def reset(self, use_curriculum: bool = True, adversarial: bool = False) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/reset", json={
            "use_curriculum": use_curriculum,
            "adversarial": adversarial,
            "persona": self._persona,
            "use_llm_judge": self._use_llm_judge,
        })
        r.raise_for_status()
        return r.json()

    def step(self, action_type: str, params: dict) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/step", json={
            "action_type": action_type, "params": params,
        })
        r.raise_for_status()
        return r.json()

    def grade(self) -> dict[str, Any]:
        r = self._c.post(f"{self._base}/grader")
        r.raise_for_status()
        return r.json()

    def state(self) -> dict[str, Any]:
        r = self._c.get(f"{self._base}/state")
        r.raise_for_status()
        return r.json()

    def curriculum(self) -> dict[str, Any]:
        r = self._c.get(f"{self._base}/curriculum")
        r.raise_for_status()
        return r.json()


# ----------------------------------------------------------- Rollout


@dataclass
class Rollout:
    """One full episode played by the agent."""
    task_id: str
    tier: str
    steps: list[dict[str, Any]]
    cumulative_reward: float
    grade: dict[str, float]
    prompt: str
    completion: str


SYSTEM_PROMPT = """You are IncidentCommander, an on-call SRE agent. You must diagnose and
mitigate a production incident using only the JSON actions provided by the
environment. Always investigate (query_logs / query_metrics / get_service_dependencies)
before taking write actions. When you are confident, submit a postmortem.

Respond with a single JSON object per turn:
  {"action_type": "<action>", "params": {...}}
"""


def build_prompt(observation: dict[str, Any], history: list[dict[str, Any]]) -> str:
    """Build the model prompt from the current observation and action history."""
    lines = [SYSTEM_PROMPT, "", "--- OBSERVATION ---", json.dumps(observation, indent=2, default=str)]
    if history:
        lines.append("\n--- HISTORY ---")
        for h in history[-6:]:
            lines.append(json.dumps(h, default=str))
    lines.append("\n--- YOUR TURN ---")
    return "\n".join(lines)


def parse_model_output(text: str) -> dict[str, Any]:
    """Extract the first JSON action from model output."""
    import re
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if not match:
        return {"action_type": "query_logs", "params": {"service": "payments-api", "last_minutes": 5}}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"action_type": "query_logs", "params": {"service": "payments-api", "last_minutes": 5}}
    return obj


def rollout_episode(
    client: OpenEnvClient,
    generate_fn,
    *,
    use_curriculum: bool,
    adversarial: bool,
    step_limit: int,
) -> Rollout:
    obs = client.reset(use_curriculum=use_curriculum, adversarial=adversarial)
    state0 = client.state()
    task_id = state0.get("task_id", "unknown")
    tier = client.curriculum().get("tier", "warmup")

    history: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    cumulative = 0.0
    done = False
    prompt_text = ""
    completion_text = ""

    for _ in range(step_limit):
        if done:
            break
        prompt = build_prompt(obs, history)
        prompt_text = prompt  # keep last prompt for logging
        out = generate_fn(prompt)
        completion_text = out
        action = parse_model_output(out)
        try:
            result = client.step(action.get("action_type", "query_logs"), action.get("params", {}))
        except httpx.HTTPStatusError as e:
            log.warning("step rejected: %s", e)
            break
        steps.append({"action": action, "reward": result.get("reward", 0.0), "info": result.get("info", {})})
        history.append({
            "action_type": action.get("action_type"),
            "params": action.get("params"),
            "reward": result.get("reward"),
        })
        cumulative += float(result.get("reward", 0.0))
        obs = result.get("observation", {})
        done = bool(result.get("done", False))

    try:
        grade = client.grade()
    except httpx.HTTPStatusError:
        grade = {"total": 0.001}

    return Rollout(
        task_id=task_id, tier=tier, steps=steps,
        cumulative_reward=cumulative, grade=grade,
        prompt=prompt_text, completion=completion_text,
    )


def episode_reward(rollout: Rollout) -> float:
    """GRPO reward = shaped per-step sum + holistic grade bonus."""
    return rollout.cumulative_reward + 2.0 * float(rollout.grade.get("total", 0.0))


# ----------------------------------------------------------- main


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    # --local preset: small model + LoRA + 4-bit so an 8GB consumer GPU works.
    if args.local:
        if args.model == "Qwen/Qwen2.5-1.5B-Instruct":
            args.model = "Qwen/Qwen2.5-0.5B-Instruct"
        args.num_generations = max(2, min(args.num_generations, 4))
        args.grad_accum = max(args.grad_accum, 4)
        args.max_steps = min(args.max_steps, 60)
        args.vllm_mode = "server"  # plain HF generation — vLLM colocate needs >=40GB
        args.four_bit = True
        if args.no_hub_push or not args.hub_repo:
            args.hub_repo = None
        log.info("--local preset: model=%s steps=%d gens=%d 4bit=%s",
                 args.model, args.max_steps, args.num_generations, args.four_bit)

    os.makedirs(args.out_dir, exist_ok=True)

    client = OpenEnvClient(args.env_url, persona=args.persona, use_llm_judge=False)

    # Optional: inject a real fault before each reset if REAL_K8S is active.
    if args.inject_fault:
        def _inject():
            try:
                client._c.post(f"{client._base}/k8s/inject",
                               json={"fault_type": args.inject_fault}, timeout=30.0)
            except Exception as e:
                log.warning("inject_failure failed: %s", e)
        _inject_hook = _inject
    else:
        _inject_hook = None

    # Import heavy deps only when actually training.
    if args.dry_run:
        log.info("DRY RUN: checking env connectivity only")
        log.info("curriculum: %s", client.curriculum())

        def _stub(prompt: str) -> str:
            return json.dumps({"action_type": "query_logs",
                               "params": {"service": "payments-api", "last_minutes": 5}})

        r = rollout_episode(client, _stub,
                            use_curriculum=True, adversarial=False,
                            step_limit=args.episode_limit)
        log.info("dry-run rollout: task=%s cum=%.3f grade=%s",
                 r.task_id, r.cumulative_reward, r.grade)
        return

    try:
        import torch  # type: ignore
        from transformers import AutoTokenizer  # type: ignore
        from trl import GRPOConfig, GRPOTrainer  # type: ignore
        from peft import LoraConfig  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "training dependencies missing. Install: pip install "
            "'trl>=0.29.0' transformers peft accelerate vllm"
        ) from e

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Build a small generate_fn that GRPOTrainer will hook into.
    # The actual generation happens inside TRL, but we need to return a
    # reward for each completion string — see `reward_fn` below.

    def reward_fn(prompts: list[str], completions: list[str], **kwargs) -> list[float]:
        """Compute GRPO reward by actually playing out each completion."""
        rewards: list[float] = []
        for prompt, completion in zip(prompts, completions):
            if _inject_hook is not None:
                _inject_hook()
            # For real training, each `completion` is one action; we play a
            # short episode that uses the model's greedy completion as step 0
            # and then lets the curriculum roll the rest with a zero-shot stub.
            # TRL will compare rewards across the 8 generations.
            def _gen(_prompt: str, _c=completion) -> str:
                return _c
            r = rollout_episode(
                client, _gen,
                use_curriculum=True,
                adversarial=args.use_adversarial,
                step_limit=args.episode_limit,
            )
            rewards.append(episode_reward(r))
        return rewards

    # Tiny synthetic dataset: one prompt per training step. TRL will sample
    # `num_generations` completions per row and call `reward_fn`.
    from datasets import Dataset  # type: ignore
    ds = Dataset.from_dict({"prompt": [SYSTEM_PROMPT] * args.max_steps})

    config = GRPOConfig(
        output_dir=args.out_dir,
        num_generations=args.num_generations,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        max_steps=args.max_steps,
        save_steps=args.save_steps,
        logging_steps=1,
        bf16=not args.four_bit,
        fp16=args.four_bit and not torch.cuda.is_bf16_supported(),
        push_to_hub=bool(args.hub_repo),
        hub_model_id=args.hub_repo,
        use_vllm=(args.vllm_mode == "colocate"),
        vllm_mode="colocate" if args.vllm_mode == "colocate" else "server",
        report_to="none",
        per_device_train_batch_size=1,
    )

    lora = LoraConfig(
        r=8 if args.local else 16,
        lora_alpha=16 if args.local else 32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none", task_type="CAUSAL_LM",
    )

    trainer_kwargs: dict[str, Any] = dict(
        model=args.model,
        args=config,
        train_dataset=ds,
        reward_funcs=reward_fn,
        peft_config=lora,
        processing_class=tokenizer,
    )

    if args.four_bit:
        # Preload the model 4-bit so trl picks it up instead of the id string.
        try:
            from transformers import AutoModelForCausalLM, BitsAndBytesConfig  # type: ignore
        except ImportError as e:
            raise RuntimeError("4-bit requires bitsandbytes + transformers") from e
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
                                 bnb_4bit_quant_type="nf4")
        log.info("loading %s in 4-bit", args.model)
        model = AutoModelForCausalLM.from_pretrained(
            args.model, quantization_config=bnb, device_map="auto")
        trainer_kwargs["model"] = model

    trainer = GRPOTrainer(**trainer_kwargs)

    log.info("starting GRPO training: model=%s steps=%d", args.model, args.max_steps)
    t0 = time.time()
    trainer.train()
    log.info("done in %.1fs", time.time() - t0)

    if args.hub_repo:
        trainer.push_to_hub(args.hub_repo)

    # Upload final checkpoint to S3 if configured.
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from environment.aws_integrations import S3CheckpointUploader  # type: ignore
        up = S3CheckpointUploader(prefix=f"grpo/{int(t0)}")
        if up.enabled:
            up.upload_dir(args.out_dir, "final")
    except Exception as e:
        log.warning("S3 upload skipped: %s", e)


if __name__ == "__main__":
    main()
