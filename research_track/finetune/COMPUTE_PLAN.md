# Compute Plan (No AWS Calls Made)

- Local RTX 4050 6 GB: potentially suitable for small OCR/LoRA smoke tests after data and compatibility checks; Qwen3-VL full training is not assumed to fit.
- EC2 g4dn.xlarge: candidate T4 16 GB host for approved smoke/full runs; pricing and spot availability must be re-verified at execution time. No AWS API calls were made.
- Current guard: available RAM was approximately 3 GB, so model loading and CPU baselines requiring large weights were deferred.
- Budget: user-supplied budget is required in the exact approval token; checkpoints/logs would go under `~/ml-assets/campus/runs/<track>/<run_id>/`, never the repository.
- Execution order after approval: Track A, then C, then B. Each run requires a smoke test, epoch validation, one final test evaluation, confidence intervals, and error analysis.
