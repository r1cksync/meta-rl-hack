"""PPO Training Loop for IncidentCommander.

Uses stable-baselines3 to train a PPO agent on the Gymnasium-wrapped environment.
Logs to Weights & Biases.

Usage:
    python training/train_ppo.py
"""

from __future__ import annotations

import os
from pathlib import Path

CHECKPOINT_DIR = Path(__file__).resolve().parent.parent / "checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)


def main():
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_util import make_vec_env
        from stable_baselines3.common.callbacks import CheckpointCallback
    except ImportError:
        print("ERROR: stable-baselines3 not installed. Run: pip install stable-baselines3")
        return

    # Optional W&B integration
    use_wandb = bool(os.getenv("WANDB_API_KEY"))
    if use_wandb:
        try:
            import wandb
            from wandb.integration.sb3 import WandbCallback

            wandb.init(
                project=os.getenv("WANDB_PROJECT", "incident-commander"),
                name="ppo-training",
                config={
                    "algorithm": "PPO",
                    "total_timesteps": 100_000,
                    "n_envs": 4,
                },
            )
        except ImportError:
            use_wandb = False
            print("WARNING: wandb not installed. Training without W&B logging.")

    from training.gym_wrapper import IncidentCommanderGymEnv

    # Create 4 parallel environments cycling through tasks
    env = make_vec_env(
        IncidentCommanderGymEnv,
        n_envs=4,
        env_kwargs={"task_ids": ["task1", "task2", "task3"]},
    )

    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
    )

    callbacks = [
        CheckpointCallback(
            save_freq=10_000,
            save_path=str(CHECKPOINT_DIR),
            name_prefix="incident_commander_ppo",
        ),
    ]
    if use_wandb:
        callbacks.append(WandbCallback(verbose=2))

    print("Starting PPO training (100,000 timesteps)...")
    model.learn(total_timesteps=100_000, callback=callbacks)

    model.save(CHECKPOINT_DIR / "final_model")
    print(f"Training complete. Model saved to {CHECKPOINT_DIR / 'final_model'}")

    if use_wandb:
        wandb.finish()


if __name__ == "__main__":
    main()
