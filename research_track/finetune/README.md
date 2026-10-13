# Fine-Tuning Preparation (G3 gated)

These artifacts are preparation only. No training, GPU use, AWS call, checkpoint creation, or production wiring is performed without the exact approval token:

`APPROVE_FINETUNE:<tracks>:<local|ec2>:<budget_usd>`

All hyperparameters in these files are unverified starting points. Data converters must preserve independent test splits and must not store real PII in the repository.
