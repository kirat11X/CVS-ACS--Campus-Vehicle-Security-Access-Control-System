"""Track C inference helpers: greedy generation restricted to the 8 codes (invalid -> UNKNOWN)."""

from __future__ import annotations

import torch

from c_common import CODES, FORBIDDEN_OUTPUTS, parse_output, render_prompt


@torch.no_grad()
def predict_codes(model, tok, texts: list[str], batch_size: int = 16, max_new_tokens: int = 10):
    """Returns (codes, raw_outputs, valid_flags). Never returns a policy outcome."""
    old_side = tok.padding_side
    tok.padding_side = "left"
    codes, raws, valid = [], [], []
    for i in range(0, len(texts), batch_size):
        prompts = [render_prompt(tok, t) for t in texts[i : i + batch_size]]
        enc = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to(model.device)
        out = model.generate(
            **enc, max_new_tokens=max_new_tokens, do_sample=False, temperature=None, top_p=None, top_k=None,
            pad_token_id=tok.pad_token_id, use_cache=True,
        )
        for row in out[:, enc["input_ids"].shape[1] :]:
            raw = tok.decode(row, skip_special_tokens=True)
            code, ok = parse_output(raw)
            assert code in CODES and code not in FORBIDDEN_OUTPUTS
            codes.append(code)
            raws.append(raw)
            valid.append(ok)
    tok.padding_side = old_side
    return codes, raws, valid


def quick_metrics(gold: list[str], pred: list[str], valid: list[bool] | None = None) -> dict:
    from sklearn.metrics import accuracy_score, f1_score

    m = {
        "n": len(gold),
        "accuracy": round(accuracy_score(gold, pred), 4),
        "macro_f1": round(f1_score(gold, pred, labels=CODES, average="macro", zero_division=0), 4),
        "unknown_rate": round(sum(p == "UNKNOWN" for p in pred) / len(pred), 4),
    }
    if valid is not None:
        m["invalid_output_rate"] = round(1 - sum(valid) / len(valid), 4)
    return m
