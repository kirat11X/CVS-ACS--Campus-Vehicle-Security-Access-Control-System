"""Track C: Qwen3-1.7B 4-bit QLoRA (PEFT + TRL SFTTrainer) proposing one of 8 taxonomy codes.

All hyperparameter defaults are UNVERIFIED STARTING POINTS; tune only on the validation split.
The model proposes a category only. Policy (ALLOW/REVIEW/ALERT) stays in the deterministic engine.

Resumable: re-running with the same --run-id resumes from the last checkpoint in <run_dir>/checkpoints.
Stops cleanly (checkpoint + exit) when <run_dir>/STOP appears (watchdog) or the wall-time cap is hit.

Usage:
  c_train_lora.py --run-id smoke --max-samples 50 --max-steps 20
  c_train_lora.py --run-id full_lr2e-4 --lr 2e-4 --epochs 8
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    EarlyStoppingCallback,
    TrainerCallback,
)
from transformers.trainer_utils import get_last_checkpoint
from trl import SFTConfig, SFTTrainer

from c_common import (
    QWEN_PATH,
    RUNS_C,
    load_split,
    render_prompt,
    seed_everything,
    sha256_file,
    sha256_json,
    write_run_manifest,
)
from c_infer import predict_codes, quick_metrics


class GuardCallback(TrainerCallback):
    """Wall-time cap, watchdog stop file, and peak-VRAM tracking."""

    def __init__(self, stop_file: Path, wall_s: float, t0: float):
        self.stop_file, self.wall_s, self.t0 = stop_file, wall_s, t0
        self.stop_reason = None

    def on_step_end(self, args, state, control, **kw):
        reason = None
        if self.stop_file.exists():
            reason = "watchdog: " + self.stop_file.read_text().strip()
        elif time.time() - self.t0 > self.wall_s:
            reason = f"wall-time cap {self.wall_s / 60:.0f} min"
        if reason:
            self.stop_reason = reason
            control.should_save = True
            control.should_training_stop = True
        return control


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split-dir", type=Path, default=RUNS_C / "split_v1")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, default=42)
    # UNVERIFIED starting points:
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--epochs", type=float, default=8)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=1)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--warmup", type=float, default=0.05)
    ap.add_argument("--patience", type=int, default=2)
    # Smoke / caps:
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--wall-time-min", type=float, default=60.0)
    ap.add_argument("--skip-val-generation", action="store_true")
    args = ap.parse_args()

    assert torch.cuda.is_available(), "CUDA required (set CUDA_VISIBLE_DEVICES=0)"
    t0 = time.time()
    seed_everything(args.seed)
    run_dir = RUNS_C / args.run_id
    ckpt_dir = run_dir / "checkpoints"
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_file = run_dir / "STOP"
    if stop_file.exists():
        stop_file.unlink()

    splits = load_split(args.split_dir)
    train_df, val_df = splits["train"], splits["val"]  # test split is never read here
    if args.max_samples:
        train_df = train_df.sample(n=min(args.max_samples, len(train_df)), random_state=args.seed)
        val_df = val_df.sample(n=min(max(10, args.max_samples // 3), len(val_df)), random_state=args.seed)

    tok = AutoTokenizer.from_pretrained(QWEN_PATH)
    tok.padding_side = "right"

    def to_ds(df):
        return Dataset.from_list(
            [{"prompt": render_prompt(tok, t), "completion": c} for t, c in zip(df["item_text"], df["category"])]
        )

    train_ds, val_ds = to_ds(train_df), to_ds(val_df)
    config = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()}
    config_sha = sha256_json(config)

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        QWEN_PATH, quantization_config=bnb, dtype=torch.bfloat16, device_map={"": 0}
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    trainable, total = model.get_nb_trainable_parameters()

    sft_args = SFTConfig(
        output_dir=str(ckpt_dir),
        seed=args.seed,
        data_seed=args.seed,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        lr_scheduler_type="cosine",
        warmup_steps=args.warmup,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        max_length=args.max_length,
        completion_only_loss=True,
        eval_strategy="steps" if args.max_steps > 0 else "epoch",
        eval_steps=max(1, args.max_steps // 2) if args.max_steps > 0 else None,
        save_strategy="steps" if args.max_steps > 0 else "epoch",
        save_steps=max(1, args.max_steps // 2) if args.max_steps > 0 else None,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=5,
        report_to="none",
        dataloader_num_workers=0,
    )
    guard = GuardCallback(stop_file, args.wall_time_min * 60, t0)
    trainer = SFTTrainer(
        model=model,
        args=sft_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tok,
        callbacks=[guard, EarlyStoppingCallback(early_stopping_patience=args.patience)],
    )
    last = get_last_checkpoint(str(ckpt_dir)) if ckpt_dir.exists() else None
    write_run_manifest(
        run_dir, run_id=args.run_id, kind="train_lora", status="RUNNING", seed=args.seed, config=config,
        config_sha256=config_sha, data_sha256={s: sha256_file(args.split_dir / f"{s}.csv") for s in ("train", "val")},
        base_model=str(QWEN_PATH), base_model_license="Apache-2.0", resumed_from=last,
        n_train=len(train_ds), n_val=len(val_ds), trainable_params=trainable, total_params=total,
        hyperparameters_status="UNVERIFIED starting points; tuned on validation only",
        test_evaluated_once=False,
    )
    torch.cuda.reset_peak_memory_stats()
    train_out = trainer.train(resume_from_checkpoint=last)
    peak_alloc = torch.cuda.max_memory_allocated() / 2**30
    peak_reserved = torch.cuda.max_memory_reserved() / 2**30

    adapter_dir = run_dir / "adapter"
    trainer.model.save_pretrained(str(adapter_dir))  # best (load_best_model_at_end) adapter
    tok.save_pretrained(str(adapter_dir))

    val_metrics = None
    if not args.skip_val_generation:
        trainer.model.eval()
        trainer.model.config.use_cache = True
        preds, raws, valid = predict_codes(trainer.model, tok, val_df["item_text"].tolist(), batch_size=16)
        val_metrics = quick_metrics(val_df["category"].tolist(), preds, valid)

    history = [h for h in trainer.state.log_history]
    status = "STOPPED: " + guard.stop_reason if guard.stop_reason else "COMPLETED"
    write_run_manifest(
        run_dir, status=status, wall_time_s=round(time.time() - t0, 1),
        peak_vram_allocated_gib=round(peak_alloc, 3), peak_vram_reserved_gib=round(peak_reserved, 3),
        global_steps=trainer.state.global_step, epochs_done=trainer.state.epoch,
        best_checkpoint=trainer.state.best_model_checkpoint, best_eval_loss=trainer.state.best_metric,
        train_loss=train_out.training_loss, val_generation_metrics=val_metrics, adapter_dir=str(adapter_dir),
    )
    (run_dir / "log_history.json").write_text(json.dumps(history, indent=1))
    print(json.dumps({"status": status, "wall_s": round(time.time() - t0, 1), "peak_alloc_gib": round(peak_alloc, 3),
                      "peak_reserved_gib": round(peak_reserved, 3), "best_eval_loss": trainer.state.best_metric,
                      "val": val_metrics}, indent=1))


if __name__ == "__main__":
    main()
