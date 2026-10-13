# Review Changelog

## 2026-10-09

- Fixed Track A `from_config()` constructor keyword drift and restored declared normalizer settings.
- Added isolated review pytest harness with network socket kill-switch and forbidden production-import assertion.
- Fixed Track B schema-rejection finding serialization by adding `VAL_SCHEMA_VIOLATION` enum handling.
- Replaced Track B shallow invoice validation with strict Draft 2020-12 JSON Schema validation and strict object properties.
- Removed Track C wall-clock dependence from lexical predictions and screening event IDs; explicit evaluation timestamps are now required.
- Canonicalized Track C rule ordering in event identity and escalated uncertain classifications that would otherwise ALLOW.
- Replaced Track B greedy line-item alignment with deterministic optimal one-to-one assignment; the 32-document synthetic metrics were unchanged.
- Added regression tests for isolation, Track A normalization/configuration, Track B schema/Decimal behavior, and Track C determinism/safety.
