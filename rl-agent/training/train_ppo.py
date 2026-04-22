"""Actor-Critic (PPO-style) trainer for IncidentCommander.

Design
------
* Actor  = Qwen2.5-0.5B-Instruct + LoRA (r=8), autoregressive token generation.
* Critic = Linear(hidden -> 1) on last hidden state of the base model.
* Rollouts via the OpenEnv HTTP client; GAE advantages; clipped PPO update.

Runs on CPU with `--tiny` (scripted policy, for pipeline validation).
Runs on CPU with `--cpu` (real PPO, slow).
Runs on 8GB GPU with `--local`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Actor-Critic (PPO) trainer")
    p.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    p.add_argument("--env-url", default=os.getenv("ENV_URL", "http://localhost:7860"))
    p.add_argument("--rollouts-per-update", type=int, default=2)
    p.add_argument("--ppo-epochs", type=int, default=2)
    p.add_argument("--updates", type=int, default=20)
    p.add_argument("--episode-limit", type=int, default=10)
    p.add_argument("--lr-actor", type=float, default=1e-5)
    p.add_argument("--lr-critic", type=float, default=3e-4)
    p.add_argument("--clip-eps", type=float, default=0.2)
    p.add_argument("--vf-coef", type=float, default=0.5)
    p.add_argument("--ent-coef", type=float, default=0.01)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--lam", type=float, default=0.95)
    p.add_argument("--max-new-tokens", type=int, default=96)
    p.add_argument("--out-dir", default="./checkpoints/ppo")
    p.add_argument("--metrics-file", default=None)
    p.add_argument("--persona", choices=["junior", "senior", "principal"], default="senior")
    p.add_argument("--use-adversarial", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--tiny", action="store_true",
                   help="Scripted policy, no model load. CPU pipeline smoke test.")
    p.add_argument("--cpu", action="store_true")
    p.add_argument("--resume", default=None)
    return p.parse_args()


class OpenEnvClient:
    def __init__(self, base_url: str, persona: str = "senior", use_llm_judge: bool = False):
        self._base = base_url.rstrip("/")
        self._persona = persona
        self._use_llm_judge = use_llm_judge
        self._c = httpx.Client(timeout=60.0)

    def reset(self, use_curriculum: bool = True, adversarial: bool = False,
              real_mode: bool = False) -> dict:
        r = self._c.post(f"{self._base}/reset", json={
            "use_curriculum": use_curriculum, "adversarial": adversarial,
            "persona": self._persona, "use_llm_judge": self._use_llm_judge,
            "real_mode": real_mode,
        })
        r.raise_for_status()
        return r.json()

    def step(self, action_type: str, params: dict) -> dict:
        r = self._c.post(f"{self._base}/step",
                         json={"action_type": action_type, "params": params})
        r.raise_for_status()
        return r.json()

    def grade(self) -> dict:
        try:
            r = self._c.post(f"{self._base}/grader"); r.raise_for_status(); return r.json()
        except httpx.HTTPStatusError:
            return {"total": 0.0}

    def state(self) -> dict:
        r = self._c.get(f"{self._base}/state"); r.raise_for_status(); return r.json()

    def curriculum(self) -> dict:
        try:
            r = self._c.get(f"{self._base}/curriculum"); r.raise_for_status(); return r.json()
        except httpx.HTTPStatusError:
            return {"tier": "warmup"}


SYSTEM_PROMPT = """You are IncidentCommander, an on-call SRE agent. Diagnose and
mitigate a production incident using only the JSON actions provided.
Always investigate (query_logs / query_metrics / get_service_dependencies)
before taking write actions. When confident, submit a postmortem.

Respond with ONE JSON object:
  {"action_type": "<action>", "params": {...}}
"""


def build_prompt(observation: dict, history: list[dict]) -> str:
    lines = [SYSTEM_PROMPT, "", "--- OBSERVATION ---",
             json.dumps(observation, indent=2, default=str)[:2000]]
    if history:
        lines.append("\n--- HISTORY ---")
        for h in history[-4:]:
            lines.append(json.dumps(h, default=str))
    lines.append("\n--- YOUR TURN ---")
    return "\n".join(lines)


def parse_action(text: str) -> dict:
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    default = {"action_type": "query_logs",
               "params": {"service": "payments-api", "last_minutes": 5}}
    if not m:
        return default
    try:
        obj = json.loads(m.group(0))
        if not isinstance(obj, dict) or "action_type" not in obj:
            return default
        obj.setdefault("params", {})
        return obj
    except json.JSONDecodeError:
        return default


@dataclass
class Transition:
    prompt: str
    completion: str
    logprob: float
    value: float
    reward: float
    done: bool


@dataclass
class EpisodeStats:
    task_id: str
    tier: str
    cumulative_reward: float
    grade_total: float
    n_steps: int
    mitigation_applied: bool
    root_cause_identified: bool
    reward_breakdown: dict = field(default_factory=dict)


def compute_gae(rewards, values, gamma, lam):
    advs = [0.0] * len(rewards)
    gae, next_v = 0.0, 0.0
    for t in reversed(range(len(rewards))):
        delta = rewards[t] + gamma * next_v - values[t]
        gae = delta + gamma * lam * gae
        advs[t] = gae
        next_v = values[t]
    returns = [a + v for a, v in zip(advs, values)]
    return advs, returns


def _rollout(client: OpenEnvClient,
             policy_fn: Callable[[str], tuple[str, float]],
             value_fn: Callable[[str], float],
             *, use_adversarial: bool, step_limit: int):
    obs = client.reset(use_curriculum=True, adversarial=use_adversarial)
    state0 = client.state()
    task_id = state0.get("task_id", "unknown")
    tier = client.curriculum().get("tier", "warmup")

    history, transitions = [], []
    cumulative = 0.0
    done = False
    last_breakdown: dict = {}
    mit_applied = False
    rc_id = False

    for _ in range(step_limit):
        if done:
            break
        prompt = build_prompt(obs, history)
        value = value_fn(prompt)
        completion, logp = policy_fn(prompt)
        action = parse_action(completion)
        try:
            result = client.step(action.get("action_type", "query_logs"),
                                 action.get("params", {}))
        except httpx.HTTPStatusError as e:
            log.warning("step rejected: %s", e)
            break

        reward = float(result.get("reward", 0.0))
        done   = bool(result.get("done", False))
        info   = result.get("info", {}) or {}
        last_breakdown = info.get("reward_breakdown", last_breakdown) or last_breakdown
        mit_applied = mit_applied or info.get("mitigation_applied", False)
        rc_id       = rc_id       or info.get("root_cause_identified", False)

        transitions.append(Transition(prompt, completion, logp, value, reward, done))
        history.append({"action_type": action.get("action_type"),
                        "params": action.get("params"), "reward": reward})
        cumulative += reward
        obs = result.get("observation", {})

    grade = client.grade().get("total", 0.0)
    stats = EpisodeStats(task_id, tier, cumulative, float(grade),
                         len(transitions), mit_applied, rc_id, last_breakdown)
    return transitions, stats


def _load_actor_critic(model_name: str, local: bool, device: str):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model

    tok = AutoTokenizer.from_pretrained(model_name)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype).to(device)

    lora_cfg = LoraConfig(
        r=8 if local else 16, lora_alpha=16, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none", task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    hidden = model.base_model.model.config.hidden_size
    critic = torch.nn.Linear(hidden, 1).to(device=device, dtype=dtype)
    torch.nn.init.zeros_(critic.bias)
    torch.nn.init.normal_(critic.weight, std=0.01)
    return tok, model, critic


def _actor_generate(tok, model, prompt, max_new_tokens, device):
    import torch
    inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(device)
    p_len = inputs.input_ids.shape[1]
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens,
                             do_sample=True, top_p=0.95, temperature=0.8,
                             pad_token_id=tok.pad_token_id,
                             return_dict_in_generate=True, output_scores=True)
    seq = out.sequences[0]
    gen = seq[p_len:]
    log_sum = 0.0
    for i, logits in enumerate(out.scores):
        if i >= gen.shape[0]:
            break
        lp = torch.log_softmax(logits[0], dim=-1)
        log_sum += lp[gen[i]].item()
    return tok.decode(gen, skip_special_tokens=True), float(log_sum)


def _critic_value(tok, model, critic, prompt, device):
    import torch
    with torch.no_grad():
        inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(device)
        out = model(**inputs, output_hidden_states=True, return_dict=True)
        last = out.hidden_states[-1][0, -1, :]
        return float(critic(last).item())


def _policy_logprob(tok, model, prompt, completion, device):
    import torch
    full = prompt + completion
    full_ids = tok(full, return_tensors="pt", truncation=True, max_length=2048).input_ids.to(device)
    prompt_ids = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).input_ids.to(device)
    p_len = prompt_ids.shape[1]
    out = model(full_ids, return_dict=True)
    logits = out.logits[0]
    log_sum = torch.tensor(0.0, device=device, dtype=logits.dtype)
    for i in range(p_len, full_ids.shape[1]):
        tgt = full_ids[0, i]
        lp = torch.log_softmax(logits[i - 1], dim=-1)
        log_sum = log_sum + lp[tgt]
    return log_sum


def _critic_value_grad(tok, model, critic, prompt, device):
    inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(device)
    out = model(**inputs, output_hidden_states=True, return_dict=True)
    last = out.hidden_states[-1][0, -1, :]
    return critic(last).squeeze()


def _save_checkpoint(out_dir, actor, critic, tag):
    import torch
    p = Path(out_dir) / f"ckpt-{tag}"
    p.mkdir(parents=True, exist_ok=True)
    try:
        actor.save_pretrained(str(p))
    except Exception as e:
        log.warning("actor save failed: %s", e)
    torch.save(critic.state_dict(), p / "critic.pt")
    log.info("saved checkpoint -> %s", p)


def _write_summary(stats, out_dir, *, mode):
    by_task: dict = {}
    for s in stats:
        by_task.setdefault(s.task_id, []).append(s)
    n = max(1, len(stats))
    summary = {
        "mode": mode,
        "total_episodes": len(stats),
        "mean_reward": sum(s.cumulative_reward for s in stats) / n,
        "mean_grade":  sum(s.grade_total for s in stats) / n,
        "mitigation_rate": sum(int(s.mitigation_applied) for s in stats) / n,
        "root_cause_rate": sum(int(s.root_cause_identified) for s in stats) / n,
        "per_task": {
            tid: {
                "n": len(st),
                "mean_reward": sum(x.cumulative_reward for x in st) / len(st),
                "mean_grade":  sum(x.grade_total for x in st) / len(st),
                "mitigation_rate": sum(int(x.mitigation_applied) for x in st) / len(st),
                "root_cause_rate": sum(int(x.root_cause_identified) for x in st) / len(st),
            }
            for tid, st in by_task.items()
        },
        "tiers": sorted({s.tier for s in stats}),
        "timestamp": time.time(),
    }
    Path(out_dir, "summary.json").write_text(json.dumps(summary, indent=2))
    log.info("wrote summary: %s/summary.json", out_dir)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    metrics_file = Path(args.metrics_file or Path(args.out_dir) / "metrics.jsonl")
    metrics_file.parent.mkdir(parents=True, exist_ok=True)

    client = OpenEnvClient(args.env_url, persona=args.persona, use_llm_judge=False)

    if args.tiny:
        log.info("--tiny: scripted rollouts for pipeline validation")
        canned = [
            '{"action_type":"query_logs","params":{"service":"payments-api","last_minutes":5}}',
            '{"action_type":"query_metrics","params":{"promql":"rate(http_errors[1m])"}}',
            '{"action_type":"get_service_dependencies","params":{"service":"payments-api"}}',
            '{"action_type":"rollback_deployment","params":{"deployment":"payments-api"}}',
            '{"action_type":"submit_postmortem","params":{"root_cause":"invalid_container_image_tag","summary":"x","mitigation":"rollback","blast_radius":"payments","timeline":"t","prevention":"p"}}',
        ]
        idx = {"i": 0}
        def policy(_):
            c = canned[idx["i"] % len(canned)]; idx["i"] += 1
            return c, -2.3
        def value(_): return 0.0

        all_stats: list = []
        for u in range(args.updates):
            for _ in range(args.rollouts_per_update):
                _tx, st = _rollout(client, policy, value,
                                   use_adversarial=args.use_adversarial,
                                   step_limit=args.episode_limit)
                all_stats.append(st)
            recent = all_stats[-args.rollouts_per_update:]
            m = {
                "update": u, "mode": "scripted",
                "mean_reward": sum(s.cumulative_reward for s in recent) / len(recent),
                "mean_grade":  sum(s.grade_total for s in recent) / len(recent),
                "mitigation_rate": sum(int(s.mitigation_applied) for s in recent) / len(recent),
                "root_cause_rate": sum(int(s.root_cause_identified) for s in recent) / len(recent),
                "tier": recent[-1].tier,
                "ts": time.time(),
            }
            with metrics_file.open("a") as f: f.write(json.dumps(m) + "\n")
            log.info("u=%d r=%.3f g=%.3f mit=%.2f rc=%.2f",
                     u, m["mean_reward"], m["mean_grade"],
                     m["mitigation_rate"], m["root_cause_rate"])
        _write_summary(all_stats, args.out_dir, mode="scripted")
        return

    import torch
    device = "cpu" if args.cpu or not torch.cuda.is_available() else "cuda"
    log.info("device=%s  model=%s", device, args.model)

    tok, actor, critic = _load_actor_critic(args.model, args.local, device)

    optim_actor  = torch.optim.AdamW(
        (p for p in actor.parameters() if p.requires_grad), lr=args.lr_actor)
    optim_critic = torch.optim.AdamW(critic.parameters(), lr=args.lr_critic)

    def policy_fn(prompt): return _actor_generate(tok, actor, prompt, args.max_new_tokens, device)
    def value_fn(prompt):  return _critic_value(tok, actor, critic, prompt, device)

    all_stats: list = []
    for u in range(args.updates):
        batch, batch_stats = [], []
        for _ in range(args.rollouts_per_update):
            tx, st = _rollout(client, policy_fn, value_fn,
                              use_adversarial=args.use_adversarial,
                              step_limit=args.episode_limit)
            advs, rets = compute_gae([t.reward for t in tx], [t.value for t in tx],
                                     args.gamma, args.lam)
            for t, a, r in zip(tx, advs, rets):
                t.adv = a; t.ret = r  # type: ignore[attr-defined]
            batch.extend(tx)
            batch_stats.append(st)
            all_stats.append(st)
        if not batch:
            continue

        advs_t = torch.tensor([getattr(t, "adv", 0.0) for t in batch],
                              dtype=torch.float32, device=device)
        advs_t = (advs_t - advs_t.mean()) / (advs_t.std() + 1e-8)

        pol_losses, val_losses, ent_sums = [], [], []
        for _ in range(args.ppo_epochs):
            for i, t in enumerate(batch):
                new_logp = _policy_logprob(tok, actor, t.prompt, t.completion, device)
                ratio = torch.exp(new_logp - torch.tensor(
                    t.logprob, device=device, dtype=new_logp.dtype))
                adv = advs_t[i].to(dtype=ratio.dtype)
                unc = ratio * adv
                clp = torch.clamp(ratio, 1 - args.clip_eps, 1 + args.clip_eps) * adv
                pol_loss = -torch.min(unc, clp)

                v_pred = _critic_value_grad(tok, actor, critic, t.prompt, device)
                ret = torch.tensor(getattr(t, "ret", 0.0), device=device, dtype=v_pred.dtype)
                val_loss = (v_pred - ret).pow(2)

                ent = -new_logp.detach()
                loss = pol_loss + args.vf_coef * val_loss - args.ent_coef * ent

                optim_actor.zero_grad(set_to_none=True)
                optim_critic.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [p for p in actor.parameters() if p.requires_grad], 1.0)
                torch.nn.utils.clip_grad_norm_(critic.parameters(), 1.0)
                optim_actor.step(); optim_critic.step()

                pol_losses.append(pol_loss.item())
                val_losses.append(val_loss.item())
                ent_sums.append(ent.item())

        n = len(batch_stats)
        m = {
            "update": u, "mode": "ppo",
            "mean_reward": sum(s.cumulative_reward for s in batch_stats) / n,
            "mean_grade":  sum(s.grade_total for s in batch_stats) / n,
            "mitigation_rate": sum(int(s.mitigation_applied) for s in batch_stats) / n,
            "root_cause_rate": sum(int(s.root_cause_identified) for s in batch_stats) / n,
            "policy_loss": sum(pol_losses) / max(1, len(pol_losses)),
            "value_loss":  sum(val_losses) / max(1, len(val_losses)),
            "entropy":     sum(ent_sums)   / max(1, len(ent_sums)),
            "tier": batch_stats[-1].tier,
            "ts": time.time(),
        }
        with metrics_file.open("a") as f: f.write(json.dumps(m) + "\n")
        log.info("u=%d r=%.3f g=%.3f pol=%.4f val=%.4f",
                 u, m["mean_reward"], m["mean_grade"],
                 m["policy_loss"], m["value_loss"])

        if (u + 1) % max(1, args.updates // 4) == 0:
            _save_checkpoint(args.out_dir, actor, critic, u)

    _save_checkpoint(args.out_dir, actor, critic, "final")
    _write_summary(all_stats, args.out_dir, mode="ppo")

    try:
        from environment.aws_integrations import S3CheckpointUploader  # type: ignore
        up = S3CheckpointUploader(prefix=f"ppo/{int(time.time())}")
        if up.enabled:
            up.upload_dir(args.out_dir, "final")
    except Exception as e:
        log.warning("S3 upload skipped: %s", e)


if __name__ == "__main__":
    main()
