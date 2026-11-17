# Model card: campus ANPR plate detector $version

| field | value |
|---|---|
| version | $version (round $round, parent $parent) |
| status | $status |
| registered | $registered |
| task | one class, `$class_name` (Frigate's plate label) |
| weights SHA-256 | `$weights_sha256` |
| git SHA (code) | `$git_sha` |
| config SHA-256 | `$config_sha256` (copy: registry/models/$version/config.json) |
| training arguments SHA-256 | `$train_args_sha256` (registry/models/$version/train_args.yaml) |
| training-data manifest SHA-256 | `$data_sha256` |
| GOLD manifest SHA-256 | `$gold_sha256` |
| registry head / audit-log head | `$registry_head` / `$audit_head` |
| base / fine-tuned from | $base |
| training | imgsz $imgsz, lr0 $lr0 ($optimizer), replay >= $replay, fliplr 0, seed $seed |
| OCR engine (reads) | $ocr_engine |

## GOLD metrics

$gold_note

| metric | value | 95% CI |
|---|---|---|
$metrics_rows

Slices (detection value = mAP50, OCR value = exact match; slices with n < $min_slice_n are reported, not gated):

| slice | n | value |
|---|---|---|
$slice_rows

Promotion gate: $gate

## Intended use

Research track only. The model **proposes** plate boxes; people review them and the campus backend's
deterministic rules decide what an observation means. It must not open, close or hold a barrier, and its
output is never treated as an identity match on its own.

Out of scope: automatic enforcement, any use outside the PEC campus research project, and deployment beyond
academic use without resolving the AGPL-3.0 licence of Ultralytics YOLO (see below).

## Data and privacy

* Training data: licence-cleared public Indian plate datasets (bootstrap) plus frames approved in the review app
  (hash-chained audit log). Model output is never used as a label without review.
* Number plates are personal data under the DPDP Act 2023. Raw frames, crops and plate text stay in the private
  data root (and, if enabled, the private SSE-KMS S3 bucket with a retention rule); share only blurred copies;
  keep plate text out of shared logs (the `anpr` CLI prints none).

## Limitations

$limitations

## Licence

Weights are trained with Ultralytics YOLO (AGPL-3.0). Using or serving them beyond academic research needs an
Ultralytics Enterprise licence or release of the complete service source under AGPL-3.0.

## Reproduce

```
git checkout ${git_sha_short}
anpr --config config.yaml run-round --round $round   # data manifest $data_sha256_short, seed $seed
anpr evaluate --weights <weights> --name check       # must match the GOLD metrics above
```
