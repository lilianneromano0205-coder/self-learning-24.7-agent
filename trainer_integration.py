"""Data/recipe boundary for external trainers. No shell, weights, network or ML stack.

Recipe contracts follow Hugging Face TRL SFT/DPO/GRPO/RewardTrainer and
PEFT documentation. The trainer environment owns dependency pinning and
hardware setup; a recipe is not evidence that a training job ran.
"""
import json
from pathlib import Path
import shutil
import training
import controlplane

RECIPES = {
    "sft": {"trainer": "SFTTrainer", "format": "prompt_completion"},
    "lora": {"trainer": "SFTTrainer", "format": "prompt_completion", "peft": "LoRA"},
    "qlora": {"trainer": "SFTTrainer", "format": "prompt_completion", "peft": "LoRA", "quantization_bits": 4},
    "preference": {"trainer": "DPOTrainer", "format": "prompt_chosen_rejected"},
    "rlvr": {"trainer": "GRPOTrainer", "format": "prompt_verifiable_reward"},
    "verifier": {"trainer": "RewardTrainer", "format": "process_reward_labels"},
}


def recipe(kind, *, base_model, revision):
    if kind not in RECIPES:
        raise training.Refused("unsupported external recipe")
    import re
    if not base_model or not re.fullmatch(r"[a-fA-F0-9]{40,64}", revision):
        raise training.Refused("base model and immutable revision digest required")
    return {**RECIPES[kind], "method": kind, "external_only": True,
            "base_model": base_model, "revision": revision, "trust_remote_code": False,
            "dependencies": "owner-pinned external environment; never installed by core",
            "input": "train.jsonl", "execution": "NOT_RUN"}


def prepare(root, run_id, destination, kind, *, base_model, revision):
    controlplane.owner_only("prepare external trainer data")
    rows = training._training_rows(root, run_id)
    config = recipe(kind, base_model=base_model, revision=revision)
    # Generic exports are trajectories. The external adapter must produce
    # true preference pairs/reward labels; never fabricate them from success.
    config["input_format"] = "sanitized_verified_trajectories"
    config["required_conversion"] = config["format"]
    config["data_review_required"] = True
    dest = Path(destination).absolute()
    if dest.exists() or dest.is_symlink() or Path(root).resolve() in dest.resolve().parents:
        raise training.Refused("external staging must be a new directory outside expert")
    dest.mkdir(parents=True, exist_ok=False)
    try:
        with (dest / "train.jsonl").open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(training._sanitise(row), ensure_ascii=False) + "\n")
        (dest / "recipe.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    except Exception:
        # Only the newly created staging directory is removed on failure.
        shutil.rmtree(dest)
        raise
    return {"directory": str(dest), "rows": len(rows), "execution": "NOT_RUN", "recipe": config}


def register_checkpoint(root, run_id, name, checkpoint_path, evaluator):
    """Import a checkpoint through owner sealed paired evaluation, never trainer scores."""
    return training.evaluate_checkpoint(root, run_id, name, checkpoint_path, evaluator)
