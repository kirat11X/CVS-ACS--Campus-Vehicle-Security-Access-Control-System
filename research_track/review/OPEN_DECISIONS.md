# Open Decisions

1. **Track A split protocol:** Implement and freeze the declared 30% validation / 70% test split, or replace it with a documented grouped split. No threshold tuning may use the test partition.
2. **Track B line alignment:** Replace greedy matching with a deterministic optimal one-to-one assignment and define duplicate-description tie-breaking.
3. **Track B locale policy:** Decide whether ambiguous strings such as `1,234` are rejected or interpreted under an explicit document locale.
4. **Track C uncertainty:** This review treats `is_uncertain=True` as a safety escalation to REVIEW when an ALLOW would otherwise result. Confirm this policy in the specification.
5. **Cross-track adapter ownership:** Add a pure review adapter preserving Decimal quantity, null quantity, unit vocabulary, description, and line-item IDs without importing policy code into Track B.
6. **Database contract:** Decide whether the draft schema stores complete immutable screening results and audit traces as JSON, normalized columns, or both. Do not apply the draft migration until this is resolved.
7. **Authorized data:** Supply consented invoice screenshots and authorized Indian plate images before making target-domain or PEC performance claims.
8. **Compute approval:** Fine-tuning remains stopped at G3 pending an exact approval token and, for EC2, host/key details.
