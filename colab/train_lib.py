"""IncidentCommander — Colab training driver.

This module is imported by `train_incident_commander.ipynb`. It contains:

    * `IncidentRolloutCollector` — drives the env, gets the actor's action,
      asks the critic for a value estimate, and produces (s, a, r, s', V).
    * `ClaudeHaikuCritic`         — value-function head powered by Anthropic
      Claude Haiku 4.5. The critic returns a scalar in [-1, 1] estimating the
      expected episode return. Cached + batched.
    * `QwenActor`                 — Qwen3-1.7B loaded via Unsloth + 4-bit
      QLoRA. Generates a JSON action proposal from the env observation.
    * `PPOTrainer`                — advanced actor-critic update loop with
      GAE, value-baseline subtraction, KL penalty, and entropy bonus.
    * `train_loop()`              — the public entry point used by the
      notebook. Streams metrics to `logs/training_<run>.json` for downstream
      Hugging Face Space visualisations.

The implementation is deliberately framework-light so it runs on a free Colab
T4. If a non-T4 GPU is available it will be used automatically.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import torch

# ---------------------------------------------------------------------------
# Repository wiring — assumes you cloned the repo and the notebook lives in
# /content/incident-commander/ on Colab.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]                  # repo root
RL_AGENT = ROOT / "rl-agent"
sys.path.insert(0, str(RL_AGENT))

from environment.env    import IncidentCommanderEnv          # noqa: E402
from environment.models import Action, ActionType            # noqa: E402

LOGS_DIR = ROOT / "colab" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Configuration. Override via `CFG.update({...})` from the notebook.
# ---------------------------------------------------------------------------
CFG: dict[str, Any] = {
    "actor_model":         "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit",
    # ↑ Closest publicly available 1.5–1.7B Qwen model with a stable
    # Unsloth 4-bit checkpoint. Swap to "unsloth/Qwen3-1.7B-bnb-4bit" if/when
    # the official 4-bit Qwen3-1.7B repo is published.
    "max_seq_len":         3072,
    "lora_r":              16,
    "lora_alpha":          32,
    "lora_dropout":        0.0,

    # Critic — uses the Hugging Face Inference Providers router (free with a
    # standard HF_TOKEN). Default is Qwen2.5-72B-Instruct: 48× larger than the
    # actor, strong instruction-following, and routinely provisioned on the
    # router for free credits. Alternates: meta-llama/Meta-Llama-3.1-70B-Instruct,
    # mistralai/Mistral-Large-2407.
    "critic_provider":     "hf",
    "critic_model":        "Qwen/Qwen2.5-72B-Instruct",
    "critic_cache":        True,
    "critic_max_tokens":   24,
    "critic_temperature":  0.0,

    "rollouts_per_update": 4,
    "max_steps_per_ep":    16,
    "ppo_epochs":          2,
    "minibatch_size":      4,
    "gamma":               0.95,
    "gae_lambda":          0.92,
    "clip_eps":            0.20,
    "kl_coef":             0.02,
    "entropy_coef":        0.01,
    "lr":                  1e-5,
    "max_grad_norm":       1.0,

    "tasks":               [
        "sim_easy_lambda_throttle_001",
        "sim_med_eb_lambda_016",
        "sim_hard_apigw_chain_001",
        "sim_advanced_cascade_users_db_001",
        "sim_advanced_runbook_trap_postgres_001",
        "sim_advanced_trolley_orders_db_001",
        "sim_advanced_saboteur_duel_001",
        "sim_advanced_slack_redherring_001",
    ],
    "total_updates":       80,
    "checkpoint_every":    20,
    "run_name":            None,        # auto-generated if None
    "seed":                42,
}


# ---------------------------------------------------------------------------
# Critic — large LLM as a learned value head, served free via HF Inference.
# ---------------------------------------------------------------------------

@dataclass
class LLMCritic:
    """Score (state, action) → V-estimate ∈ [-1, 1] with a frozen large LLM.

    Default routing uses the **Hugging Face Inference Providers** API which is
    free for any HF account (rate-limited but generous). It transparently
    routes Qwen / Llama / Mistral 70B-class models through Together, Nebius,
    HF-Inference, etc.

    Two routing modes are kept for flexibility:
        * `provider="hf"`        — the recommended path. Uses HF_TOKEN.
        * `provider="anthropic"` — kept as a stub for users with their own
          Anthropic key. Not the default.

    The critic is intentionally asymmetric — it is much larger than the actor
    (Qwen2.5-72B vs the 1.5B QLoRA actor), giving the value estimate genuine
    compute headroom while keeping the actor fast to fine-tune.
    """
    provider:    str   = "hf"
    model:       str   = "Qwen/Qwen2.5-72B-Instruct"
    max_tokens:  int   = 24
    temperature: float = 0.0
    cache:       bool  = True
    _cache:      dict  = field(default_factory=dict)

    _SYSTEM = (
        "You are a senior SRE evaluating an incident-response action. "
        "Given a JSON observation and the action just taken, respond with a "
        "single number in [-1, 1] estimating the expected total episode "
        "reward. Use -1 for catastrophic moves (data loss, brute-force kills, "
        "ignoring runbooks), 0 for neutral inspection, +1 for textbook fixes. "
        "Output ONLY the number, no commentary."
    )

    # -----------------------------------------------------
    def __post_init__(self):
        self.provider = self.provider.lower()
        if self.provider == "hf":
            try:
                from huggingface_hub import InferenceClient
            except ImportError:                                 # pragma: no cover
                raise RuntimeError("pip install huggingface_hub")
            token = os.environ.get("HF_TOKEN", "")
            if not token:
                print("[critic] WARNING: HF_TOKEN not set — calls will fail.",
                      file=sys.stderr)
            self._client = InferenceClient(token=token, timeout=60)
        elif self.provider == "local":
            # Run the critic on the same GPU in 4-bit. `model` here may be a
            # HF repo id OR a local path (e.g. /kaggle/input/...).
            from transformers import (AutoModelForCausalLM, AutoTokenizer,
                                      BitsAndBytesConfig)
            import torch as _torch
            print(f"[critic] loading LOCAL model: {self.model}")
            bnb = BitsAndBytesConfig(load_in_4bit=True,
                                     bnb_4bit_compute_dtype=_torch.bfloat16,
                                     bnb_4bit_use_double_quant=True,
                                     bnb_4bit_quant_type="nf4")
            self._tok   = AutoTokenizer.from_pretrained(self.model, trust_remote_code=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model, quantization_config=bnb, device_map="auto",
                trust_remote_code=True)
            self._model.eval()
            self._client = None
            print(f"[critic] local critic ready ({self.model})")
        elif self.provider == "anthropic":
            try:
                import anthropic
            except ImportError:                                 # pragma: no cover
                raise RuntimeError(
                    "pip install anthropic (also set ANTHROPIC_API_KEY)")
            key = os.environ.get("ANTHROPIC_API_KEY", "")
            self._client = anthropic.Anthropic(api_key=key) if key else None
        else:
            raise ValueError(f"Unknown critic provider: {self.provider}")

    # -----------------------------------------------------
    def value(self, observation: str, action: dict) -> float:
        prompt = f"OBSERVATION:\n{observation[:1500]}\n\nACTION:\n{json.dumps(action)}"
        if self.cache and prompt in self._cache:
            return self._cache[prompt]

        text = "0"
        try:
            if self.provider == "hf":
                out = self._client.chat_completion(
                    model=self.model,
                    messages=[{"role": "system", "content": self._SYSTEM},
                              {"role": "user",   "content": prompt}],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                text = out.choices[0].message.content or "0"
            elif self.provider == "local":
                import torch as _torch
                msgs = [{"role": "system", "content": self._SYSTEM},
                        {"role": "user",   "content": prompt}]
                tmpl = self._tok.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=True)
                ids = self._tok(tmpl, return_tensors="pt",
                                truncation=True, max_length=2048
                                ).to(self._model.device)
                with _torch.inference_mode():
                    out_ids = self._model.generate(
                        **ids, max_new_tokens=self.max_tokens,
                        do_sample=False,
                        pad_token_id=self._tok.eos_token_id)
                text = self._tok.decode(
                    out_ids[0, ids.input_ids.shape[1]:],
                    skip_special_tokens=True)
            elif self._client is not None:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self._SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.content[0].text
        except Exception as exc:                                # noqa: BLE001
            print(f"[critic] call failed ({self.model}): {exc}",
                  file=sys.stderr)

        v = self._parse_score(text)
        if self.cache:
            self._cache[prompt] = v
        return v

    @staticmethod
    def _parse_score(text: str) -> float:
        m = re.search(r"-?\d+(?:\.\d+)?", text or "")
        if m is None:
            return 0.0
        try:
            return max(-1.0, min(1.0, float(m.group())))
        except ValueError:
            return 0.0


# Backwards-compat alias so old notebook cells keep working.
ClaudeHaikuCritic = LLMCritic


# ---------------------------------------------------------------------------
# Actor — Qwen3-1.7B / Qwen2.5-1.5B via Unsloth + QLoRA.
# ---------------------------------------------------------------------------

class QwenActor:
    """Unsloth-accelerated 4-bit Qwen with LoRA adapters trainable in PPO."""

    SYSTEM_PROMPT = (
        "You are IncidentCommander, an autonomous SRE. Given the current "
        "observation, decide the next action. Respond with a single JSON "
        "object on one line:\n"
        '  {"id": "<service>.<verb>", "params": {...}}\n'
        "where <service>.<verb> is one of the platform.* verbs "
        "(search_runbook, read_runbook, get_logs, get_metrics, get_trace, "
        "read_slack, pause_health_checks, resume_health_checks, "
        "failover_replica, vacuum_freeze_db, warm_cache, "
        "rollback_deployment, rebuild_index, restore_from_backup, "
        "capture_memory_dump) or any AWS service.verb action. NO prose."
    )

    def __init__(self, *, model_name: str, max_seq_len: int,
                 lora_r: int, lora_alpha: int, lora_dropout: float,
                 init_adapter_path: str | None = None):
        # Prefer unsloth (2x faster). Fall back to plain HF transformers if
        # the runtime image's torch is incompatible (HF Jobs hits this).
        try:
            from unsloth import FastLanguageModel
            self.model, self.tokenizer = FastLanguageModel.from_pretrained(
                model_name=model_name,
                max_seq_length=max_seq_len,
                dtype=None,                # auto (bf16 on A100, fp16 on T4)
                load_in_4bit=True,
            )
            self.model = FastLanguageModel.get_peft_model(
                self.model,
                r=lora_r,
                lora_alpha=lora_alpha,
                lora_dropout=lora_dropout,
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                "gate_proj", "up_proj", "down_proj"],
                bias="none",
                use_gradient_checkpointing="unsloth",
                random_state=3407,
            )
            FastLanguageModel.for_inference(self.model)
            self._unsloth = True
            print("[actor] using unsloth backend")
        except Exception as exc:                                # noqa: BLE001
            print(f"[actor] unsloth unavailable ({exc.__class__.__name__}): "
                  f"falling back to HF transformers", file=sys.stderr)
            from transformers import (AutoModelForCausalLM, AutoTokenizer,
                                      BitsAndBytesConfig)
            from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
            # If model_name is a local path (e.g. /kaggle/input/...) keep it
            # verbatim; otherwise translate the unsloth slug to its HF origin.
            if os.path.isdir(model_name):
                hf_name = model_name
            else:
                hf_name = model_name.replace("unsloth/", "Qwen/").replace(
                    "-bnb-4bit", "")
            bnb = BitsAndBytesConfig(load_in_4bit=True,
                                     bnb_4bit_compute_dtype=torch.bfloat16,
                                     bnb_4bit_use_double_quant=True,
                                     bnb_4bit_quant_type="nf4")
            self.tokenizer = AutoTokenizer.from_pretrained(
                hf_name, trust_remote_code=True)
            base = AutoModelForCausalLM.from_pretrained(
                hf_name, quantization_config=bnb, device_map="auto",
                trust_remote_code=True)
            base = prepare_model_for_kbit_training(base)
            # Pick LoRA target modules that actually exist in this arch.
            # Qwen / Llama use split q/k/v/gate/up. Phi-3 uses fused
            # qkv_proj + gate_up_proj. Detect by introspecting param names.
            param_names = {n.rsplit(".", 1)[-1]
                           for n, _ in base.named_modules()}
            if {"qkv_proj", "gate_up_proj"}.issubset(param_names):
                target_modules = ["qkv_proj", "o_proj",
                                  "gate_up_proj", "down_proj"]
            elif {"q_proj", "k_proj", "v_proj"}.issubset(param_names):
                target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                                  "gate_proj", "up_proj", "down_proj"]
            else:
                # Last-resort: regex match every linear named *_proj.
                target_modules = r".*_proj$"
            print(f"[actor] LoRA target_modules = {target_modules}")
            self.model = get_peft_model(base, LoraConfig(
                r=lora_r, lora_alpha=lora_alpha,
                lora_dropout=lora_dropout, bias="none",
                task_type="CAUSAL_LM",
                target_modules=target_modules))
            self._unsloth = False
            print(f"[actor] using HF transformers backend ({hf_name})")
        self._train_mode = False
        self.max_seq_len = max_seq_len

        # Warm-start: load LoRA weights from a prior checkpoint dir.
        if init_adapter_path:
            try:
                from pathlib import Path as _P
                from safetensors.torch import load_file as _load_st
                from peft import set_peft_model_state_dict
                p = _P(init_adapter_path)
                st_file = p / "adapter_model.safetensors"
                bin_file = p / "adapter_model.bin"
                if st_file.exists():
                    state = _load_st(str(st_file))
                elif bin_file.exists():
                    import torch as _t
                    state = _t.load(str(bin_file), map_location="cpu")
                else:
                    raise FileNotFoundError(
                        f"no adapter_model.safetensors|.bin in {p}")
                set_peft_model_state_dict(self.model, state)
                print(f"[actor] warm-started from {p}")
            except Exception as exc:                            # noqa: BLE001
                print(f"[actor] warm-start FAILED ({exc}); training from scratch",
                      file=sys.stderr)

        # Silence the noisy `Both max_new_tokens and max_length seem to have
        # been set` FutureWarning. Qwen ships a default max_length=32768 in
        # its generation_config; we always pass max_new_tokens at call time,
        # so dropping the inherited max_length is correct.
        try:
            self.model.generation_config.max_length = None
        except Exception:                                       # noqa: BLE001
            pass
        import warnings as _w
        _w.filterwarnings("ignore", category=FutureWarning,
                          module="transformers")
        _w.filterwarnings("ignore", message=".*max_new_tokens.*max_length.*")
        _w.filterwarnings("ignore", message=".*attention mask API.*")

    # -----------------------------------------------------
    def _format(self, observation: str) -> str:
        msgs = [{"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user",   "content": observation}]
        return self.tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True)

    # -----------------------------------------------------
    @torch.inference_mode()
    def act(self, observation: str, *, temperature: float = 0.7) \
            -> tuple[dict, dict]:
        """Sample an action from the actor. Returns (action, meta) where
        meta contains the prompt/response strings + log-prob sum used by PPO."""
        prompt = self._format(observation)
        ids = self.tokenizer(prompt, return_tensors="pt",
                             truncation=True, max_length=self.max_seq_len - 96
                             ).to(self.model.device)
        out = self.model.generate(
            **ids,
            max_new_tokens=96,
            temperature=temperature,
            do_sample=temperature > 0.0,
            top_p=0.95,
            pad_token_id=self.tokenizer.eos_token_id,
            return_dict_in_generate=True,
            output_scores=True,
        )
        gen_ids   = out.sequences[0, ids.input_ids.shape[1]:]
        text      = self.tokenizer.decode(gen_ids, skip_special_tokens=True)
        action    = self._extract_json(text)

        # Sum of token-level log-probs of the sampled response — used as the
        # behaviour-policy "old log prob" by PPO.
        scores = torch.stack(out.scores, dim=0).log_softmax(-1)
        chosen = gen_ids.unsqueeze(-1)
        # Trim score steps to the actual generated length.
        scores = scores[: chosen.shape[0]]
        logp_tok = scores.gather(-1, chosen.unsqueeze(0).transpose(0, 1)
                                  .squeeze(-1).unsqueeze(-1)).squeeze(-1)
        old_logp = float(logp_tok.sum().item())
        return action, {"prompt": prompt, "response": text,
                        "old_logp": old_logp,
                        "n_tokens": int(gen_ids.shape[0])}

    # -----------------------------------------------------
    @staticmethod
    def _extract_json(text: str) -> dict:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m is None:
            return {"id": "platform.get_logs", "params": {"service": "frontend"}}
        try:
            obj = json.loads(m.group())
            if "id" not in obj:
                return {"id": "platform.get_logs", "params": {"service": "frontend"}}
            obj.setdefault("params", {})
            return obj
        except json.JSONDecodeError:
            return {"id": "platform.get_logs", "params": {"service": "frontend"}}

    # -----------------------------------------------------
    def logp_of(self, prompt: str, response: str) -> torch.Tensor:
        """Compute log-prob of `response` under the *current* policy. Used
        for the PPO ratio. Differentiable."""
        if self._unsloth:
            from unsloth import FastLanguageModel
            FastLanguageModel.for_training(self.model)
        else:
            self.model.train()
        text = prompt + response
        ids = self.tokenizer(text, return_tensors="pt",
                             truncation=True, max_length=self.max_seq_len
                             ).to(self.model.device)
        plen = self.tokenizer(prompt, return_tensors="pt",
                              truncation=True, max_length=self.max_seq_len
                              ).input_ids.shape[1]
        labels = ids.input_ids.clone()
        labels[:, :plen] = -100                # don't score the prompt
        out = self.model(**ids, labels=labels)
        # `loss` is mean over response tokens; convert to summed log-prob.
        n = (labels != -100).sum().item()
        return -out.loss * n


# ---------------------------------------------------------------------------
# Rollout collection.
# ---------------------------------------------------------------------------

@dataclass
class Transition:
    task_id:    str
    step:       int
    obs:        str
    prompt:     str
    response:   str
    action:     dict
    reward:     float
    value:      float
    old_logp:   float
    done:       bool


@dataclass
class IncidentRolloutCollector:
    actor:  QwenActor
    critic: LLMCritic
    tasks:  list[str]
    max_steps_per_ep: int = 16

    def collect(self, n_episodes: int) -> list[Transition]:
        env = IncidentCommanderEnv(use_mock=True)
        transitions: list[Transition] = []
        for ep in range(n_episodes):
            tid = self.tasks[ep % len(self.tasks)]
            obs_struct = env.reset(tid)
            obs_text   = self._obs_to_text(env, obs_struct)
            for t in range(self.max_steps_per_ep):
                action, meta = self.actor.act(obs_text)
                value        = self.critic.value(obs_text, action)
                step_result  = self._step_action(env, action)
                done = step_result.done or t == self.max_steps_per_ep - 1
                transitions.append(Transition(
                    task_id=tid, step=t, obs=obs_text,
                    prompt=meta["prompt"], response=meta["response"],
                    action=action, reward=float(step_result.reward),
                    value=value, old_logp=meta["old_logp"], done=done))
                obs_text = self._obs_to_text(env, step_result.observation)
                if done:
                    break
        return transitions

    # -----------------------------------------------------
    @staticmethod
    def _obs_to_text(env, obs) -> str:
        """Compact textual observation for the LLM."""
        info = {
            "task_id": env._task.task_id if env._task else None,
            "step":    env._step_count,
            "blast":   getattr(obs, "blast_radius_pct", 0.0),
            "alerts":  [a.title for a in getattr(obs, "alerts", [])][:3],
        }
        if env._sim_active and env._sim_state is not None:
            topo = env._sim_state.topology
            info["unhealthy"] = [n for n, x in topo.nodes.items()
                                 if x.status != "healthy"]
            if env._sim_state.slack is not None:
                info["slack"] = [m.text for m in env._sim_state.slack.recent(3)]
            info["sab_phase"] = (env._sim_state.saboteur._phase
                                 if env._sim_state.saboteur else None)
        return json.dumps(info)

    # -----------------------------------------------------
    @staticmethod
    def _step_action(env, action: dict):
        sid = action.get("id", "")
        svc, _, verb = sid.partition(".")
        params = {"service": svc, "verb": verb, **action.get("params", {})}
        return env.step(Action(type=ActionType.AWS_API_CALL, params=params))


# ---------------------------------------------------------------------------
# Advantage computation.
# ---------------------------------------------------------------------------
def compute_gae(transitions: list[Transition],
                gamma: float, lam: float) -> list[tuple[float, float]]:
    """Returns list of (advantage, return) per transition."""
    advs:    list[float] = [0.0] * len(transitions)
    returns: list[float] = [0.0] * len(transitions)
    gae = 0.0
    next_v = 0.0
    for i in reversed(range(len(transitions))):
        tr = transitions[i]
        if tr.done:
            next_v, gae = 0.0, 0.0
        delta = tr.reward + gamma * next_v - tr.value
        gae   = delta + gamma * lam * gae
        advs[i]    = gae
        returns[i] = gae + tr.value
        next_v     = tr.value
    return list(zip(advs, returns))


# ---------------------------------------------------------------------------
# PPO update.
# ---------------------------------------------------------------------------
class PPOTrainer:
    def __init__(self, actor: QwenActor, *, lr: float, clip_eps: float,
                 entropy_coef: float, kl_coef: float, max_grad_norm: float):
        self.actor       = actor
        self.opt         = torch.optim.AdamW(
            [p for p in actor.model.parameters() if p.requires_grad], lr=lr)
        self.clip_eps    = clip_eps
        self.kl_coef     = kl_coef
        self.entropy_coef= entropy_coef
        self.max_grad_norm = max_grad_norm

    def update(self, transitions: list[Transition],
               adv_ret: list[tuple[float, float]],
               *, ppo_epochs: int, minibatch_size: int) -> dict:
        if self.actor._unsloth:
            from unsloth import FastLanguageModel
            FastLanguageModel.for_training(self.actor.model)
        else:
            self.actor.model.train()
        device = self.actor.model.device

        # Normalise advantages.
        advs = torch.tensor([a for a, _ in adv_ret], device=device)
        rets = torch.tensor([r for _, r in adv_ret], device=device)
        advs = (advs - advs.mean()) / (advs.std() + 1e-6)
        old_logps = torch.tensor([t.old_logp for t in transitions], device=device)

        idxs = list(range(len(transitions)))
        stats: dict[str, list[float]] = {"loss": [], "kl": [],
                                          "policy_loss": [], "value_err": []}
        for _ in range(ppo_epochs):
            torch.manual_seed(int(time.time()) & 0xFFFF)
            torch.utils._pytree.tree_map(lambda x: x, idxs)  # noop for type-checker
            torch.randperm(len(idxs))   # not strictly needed; left as marker
            for start in range(0, len(idxs), minibatch_size):
                batch = idxs[start: start + minibatch_size]
                logps = []
                for i in batch:
                    tr = transitions[i]
                    logps.append(self.actor.logp_of(tr.prompt, tr.response))
                logp = torch.stack(logps)
                ratio = torch.exp(logp - old_logps[batch])
                a = advs[batch]
                surr1 = ratio * a
                surr2 = torch.clamp(ratio, 1 - self.clip_eps,
                                    1 + self.clip_eps) * a
                policy_loss = -torch.min(surr1, surr2).mean()
                kl          = (old_logps[batch] - logp).mean()
                value_err   = ((rets[batch] - torch.tensor(
                    [transitions[i].value for i in batch], device=device)) ** 2
                ).mean().detach()
                loss = policy_loss + self.kl_coef * kl

                self.opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [p for p in self.actor.model.parameters()
                     if p.requires_grad],
                    self.max_grad_norm)
                self.opt.step()

                stats["loss"].append(float(loss.item()))
                stats["policy_loss"].append(float(policy_loss.item()))
                stats["kl"].append(float(kl.item()))
                stats["value_err"].append(float(value_err.item()))
        return {k: float(sum(v) / max(len(v), 1)) for k, v in stats.items()}


def _fmt_dur(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    if h:  return f"{h}h{m:02d}m{s:02d}s"
    if m:  return f"{m}m{s:02d}s"
    return f"{s}s"


def _make_hf_pusher(cfg: dict, run_name: str):
    """Return a callable(local_dir, path_in_repo) that uploads a folder to a
    private HF model repo. No-op if HF push isn't configured."""
    push_user = os.environ.get("IC_PUSH_USER", "").strip()
    if not push_user or not os.environ.get("HF_TOKEN"):
        print("[ckpt-push] disabled (set IC_PUSH_USER + HF_TOKEN to enable).")
        return lambda *_a, **_kw: None

    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:                                         # pragma: no cover
        print("[ckpt-push] huggingface_hub missing — skipping push.")
        return lambda *_a, **_kw: None

    repo  = f"{push_user}/incident-commander-actor"
    token = os.environ["HF_TOKEN"]
    create_repo(repo, exist_ok=True, repo_type="model", token=token,
                private=False)
    api = HfApi(token=token)
    print(f"[ckpt-push] enabled → https://huggingface.co/{repo}")

    def _push(local_dir: Path, path_in_repo: str) -> None:
        try:
            api.upload_folder(
                folder_path=str(local_dir),
                repo_id=repo,
                repo_type="model",
                path_in_repo=path_in_repo,
                commit_message=f"{run_name}: {path_in_repo}",
                run_as_future=False,
            )
            print(f"[ckpt-push] uploaded {path_in_repo}")
        except Exception as exc:                                # noqa: BLE001
            print(f"[ckpt-push] upload failed for {path_in_repo}: {exc}",
                  file=sys.stderr)

    return _push


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
def train_loop(cfg: dict | None = None) -> Path:
    """Run the full training loop. Returns the path to the JSON log.

    Progress + ETA are printed every update. If `IC_PUSH_USER` and `HF_TOKEN`
    are set, every checkpoint **and** the live JSON log are streamed to
    `<user>/incident-commander-actor` on HF Hub — so the moment your compute
    credits run out, the latest checkpoint is already safe in the cloud.
    """
    cfg = {**CFG, **(cfg or {})}
    run_name = cfg["run_name"] or f"run_{int(time.time())}"
    log_path = LOGS_DIR / f"training_{run_name}.json"
    print(f"[train] run={run_name}  log={log_path}")
    print(f"[train] device CUDA?: {torch.cuda.is_available()}  "
          f"name: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'}")

    push_ckpt = _make_hf_pusher(cfg, run_name)

    actor  = QwenActor(model_name=cfg["actor_model"],
                       max_seq_len=cfg["max_seq_len"],
                       lora_r=cfg["lora_r"], lora_alpha=cfg["lora_alpha"],
                       lora_dropout=cfg["lora_dropout"],
                       init_adapter_path=cfg.get("init_adapter_path"))
    critic = LLMCritic(provider=cfg["critic_provider"],
                       model=cfg["critic_model"],
                       max_tokens=cfg["critic_max_tokens"],
                       temperature=cfg.get("critic_temperature", 0.0),
                       cache=cfg["critic_cache"])
    collector = IncidentRolloutCollector(actor, critic, cfg["tasks"],
                                          max_steps_per_ep=cfg["max_steps_per_ep"])
    trainer   = PPOTrainer(actor, lr=cfg["lr"], clip_eps=cfg["clip_eps"],
                            entropy_coef=cfg["entropy_coef"],
                            kl_coef=cfg["kl_coef"],
                            max_grad_norm=cfg["max_grad_norm"])

    log: dict[str, Any] = {"config": cfg, "updates": []}
    log_path.write_text(json.dumps(log, indent=2))

    # tqdm if available, otherwise a no-op shim.
    try:
        from tqdm.auto import tqdm
        bar = tqdm(total=cfg["total_updates"], desc=f"PPO[{run_name}]",
                   unit="upd", dynamic_ncols=True)
    except Exception:                                            # noqa: BLE001
        class _Shim:
            def update(self, *_a, **_kw): pass
            def set_postfix_str(self, *_a, **_kw): pass
            def close(self): pass
        bar = _Shim()

    total = cfg["total_updates"]
    train_t0 = time.time()
    rolling: list[float] = []                                    # last-N step times

    for upd in range(1, total + 1):
        t0 = time.time()
        trans   = collector.collect(cfg["rollouts_per_update"])
        adv_ret = compute_gae(trans, cfg["gamma"], cfg["gae_lambda"])
        stats   = trainer.update(trans, adv_ret,
                                  ppo_epochs=cfg["ppo_epochs"],
                                  minibatch_size=cfg["minibatch_size"])
        ep_rewards: dict[str, list[float]] = {}
        for tr in trans:
            ep_rewards.setdefault(tr.task_id, []).append(tr.reward)
        per_ep = {tid: round(sum(rs), 3) for tid, rs in ep_rewards.items()}
        elapsed = time.time() - t0

        rolling.append(elapsed)
        rolling = rolling[-10:]                                  # last 10 updates
        avg_per_upd = sum(rolling) / len(rolling)
        remaining   = total - upd
        eta_s       = remaining * avg_per_upd
        wall        = time.time() - train_t0

        entry = {
            "update":          upd,
            "elapsed_s":       round(elapsed, 2),
            "wall_s":          round(wall, 1),
            "eta_s":           round(eta_s, 1),
            "n_transitions":   len(trans),
            "mean_reward":     round(sum(t.reward for t in trans) / max(len(trans), 1), 4),
            "mean_value":      round(sum(t.value  for t in trans) / max(len(trans), 1), 4),
            "ppo":             stats,
            "rewards_by_task": per_ep,
        }
        log["updates"].append(entry)
        log_path.write_text(json.dumps(log, indent=2))

        bar.set_postfix_str(
            f"r={entry['mean_reward']:+.3f} "
            f"V={entry['mean_value']:+.3f} "
            f"kl={stats['kl']:+.4f} "
            f"upd={_fmt_dur(elapsed)} "
            f"ETA={_fmt_dur(eta_s)}")
        bar.update(1)
        # Always print a line too so non-tty environments (HF Jobs logs,
        # nohup) still show progress.
        print(f"[upd {upd:03d}/{total:03d}] reward={entry['mean_reward']:+.3f} "
              f"V̄={entry['mean_value']:+.3f} loss={stats['loss']:+.3f} "
              f"kl={stats['kl']:+.4f}  upd={_fmt_dur(elapsed)} "
              f"wall={_fmt_dur(wall)}  ETA={_fmt_dur(eta_s)}",
              flush=True)

        # Stream the JSON log to HF every update so even if the pod dies
        # mid-step you can recover the metrics.
        push_ckpt(log_path.parent, "logs")

        if upd % cfg["checkpoint_every"] == 0 or upd == total:
            ckpt_name = (f"adapter_{run_name}_u{upd:04d}"
                         if upd != total else f"adapter_{run_name}_final")
            ckpt = LOGS_DIR / ckpt_name
            actor.model.save_pretrained(str(ckpt))
            actor.tokenizer.save_pretrained(str(ckpt))
            print(f"[ckpt] saved {ckpt}", flush=True)
            push_ckpt(ckpt, ckpt_name)

    bar.close()
    final_ckpt = LOGS_DIR / f"adapter_{run_name}_final"
    if not final_ckpt.exists():
        actor.model.save_pretrained(str(final_ckpt))
        actor.tokenizer.save_pretrained(str(final_ckpt))
        push_ckpt(final_ckpt, final_ckpt.name)

    total_wall = time.time() - train_t0
    print(f"[done] total wall: {_fmt_dur(total_wall)}")
    print(f"[done] final adapter -> {final_ckpt}")
    print(f"[done] JSON log     -> {log_path}")
    return log_path
