# ADR-0004: Route LLM requests by data classification

**Status:** Accepted · **Date:** 2026-09

## Context
Not every model deployment is approved for every type of data. Data residency
(EU data zone vs global), contractual terms and model-risk approval differ.

## Decision
* Every request carries `x-data-classification`
  (`public < internal < confidential < strictly_confidential`, default `internal`).
* Each registry entry declares `max_classification`. The gateway rejects (403) requests
  above a model's clearance.
* **Fallbacks may never downgrade protection:** when building the fallback chain, any
  candidate that is not cleared for the request's classification — or not allowed for the
  tenant — is skipped. Availability never wins over data protection.
* Production deployments use `DataZoneStandard` so processing stays in the EU data zone.

## Consequences
+ Classification is explicit and auditable on every event.
+ Model onboarding becomes a registry PR reviewed by security / model-risk.
− Relies on callers labelling correctly; mitigated by defaulting to `internal`,
  PII redaction regardless of label, and per-tenant default classifications (roadmap).
