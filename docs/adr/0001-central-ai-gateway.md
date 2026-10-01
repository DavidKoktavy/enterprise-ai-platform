# ADR-0001: All LLM access goes through a central AI Gateway

**Status:** Accepted · **Date:** 2026-09

## Context
Several teams want to use LLMs (chatbots, document processing, developer tooling).
If each team integrates Azure OpenAI directly we get N copies of authentication,
PII handling, logging and cost tracking — and no single place to enforce policy,
retire a model, or answer the regulator's question *"which systems sent client data
to which model, and when?"* (DORA, EU AI Act record-keeping, GDPR Art. 30).

## Decision
Introduce a platform-owned **AI Gateway** service as the only path to any LLM:

* OpenAI-compatible API, so teams can use standard SDKs and switch models by alias.
* A version-controlled **model registry** (`models.yaml`) defines aliases, deployments,
  data-classification clearance, cost, owner, status and fallback.
* Cross-cutting controls live in the gateway: tenant auth, model allow-lists, PII
  redaction, prompt-injection screening, rate limits, budgets, metrics, audit events.
* Enforced at the network and identity layer, not by convention: NetworkPolicies
  block LLM egress from all other pods, and only the gateway's managed identity has
  the Azure OpenAI RBAC role (`local_auth_enabled = false` on the account).

## Alternatives considered
* **Azure API Management (AI gateway policies)** — strong for quotas, token limits and
  load-balancing across Azure OpenAI instances. Lacks bank-specific logic (Czech PII
  validators, classification routing, domain audit schema). *Complementary:* APIM in
  front of this gateway is the target for global rate limiting and external consumers.
* **Direct SDK use + shared library** — cannot be enforced; library versions drift.
* **Open-source proxies (e.g. LiteLLM)** — good routing, but bank policy would still
  have to be bolted on; adds a third-party component to the regulated path.

## Consequences
+ One audit trail, one cost view, one place to change models.
+ Teams onboard in minutes (tenant entry + key / Entra app registration).
− The gateway is critical-path: ≥2 replicas, PDB, zone spreading, HPA, fallback chains.
− Rate limits are per replica today; move to APIM/Redis for a hard global limit.
