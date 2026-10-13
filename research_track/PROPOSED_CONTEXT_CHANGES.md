# Proposed context.md changes (not applied)

The existing rules require one implementation phase at a time and prohibit custom ML training. Preserve those production safeguards. Add this explicitly scoped exception:

> An isolated `research_track/` may stage third-party models, public datasets, evaluation designs, and optional fine-tuning preparation outside the production virtual environment and runtime. It is not a live phase, does not alter policy or barrier behavior, and may not load models, perform inference, train, contact production services, or apply migrations without a separately approved phase.

Also clarify that any future learned component emits evidence (text, category, confidence, bounding boxes, or candidate plate strings) only. Deterministic, versioned policy maps evidence to review context and ReasonCodes; a guard makes the operational decision.
