# ADR-0002: Kafka for AI audit events and long-running AI workloads

**Status:** Accepted · **Date:** 2026-09

## Context
LLM calls are slow (seconds) and occasionally unavailable. Core banking and
back-office systems must not block on them. Every AI interaction also needs to
reach several consumers: SIEM, FinOps, model-risk monitoring, analytics.

## Decision
* **Audit:** the gateway publishes one immutable `llm.completion` / `llm.blocked`
  event per request to `ai.gateway.audit`, keyed by tenant. Events carry metadata,
  token counts, cost, PII statistics and SHA-256 hashes of prompt and completion —
  not the content itself (GDPR minimisation; content storage is an explicit, non-prod
  switch).
* **Workloads:** document-centric use cases are event-driven. The LC examiner consumes
  `trade.lc.presentations` and produces `trade.lc.examinations`.
* **Delivery semantics:** at-least-once; producer `acks=all` + idempotence; offsets
  committed only after the result is acknowledged; results keyed by business id so
  consumers can de-duplicate; poison messages go to a DLQ instead of blocking a partition.
* **Scaling:** KEDA scales the worker on consumer lag, capped at the partition count.

## Consequences
+ Core systems publish and move on; AI capacity scales independently.
+ Audit stream is replayable into new consumers (e.g. a future model-drift monitor).
− Eventual consistency: callers must handle results arriving later.
− Audit emit is best-effort with local buffering if Kafka is down; a transactional
  outbox would be needed for a strict "no audit, no answer" policy.
