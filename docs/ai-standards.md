# AI Platform Standards & Best Practices (draft)

Scope: any system in the bank that uses a large language model or other generative AI.
Owner: AI Platform / Architecture. Status: draft for review.

## 1. Access
1.1 All LLM calls go through the **AI Gateway**. Direct calls to model providers are
    blocked at network and identity level.
1.2 Each consuming application is a **tenant** with its own identity (Entra ID app
    registration in production), model allow-list, rate limit and budget.
1.3 No API keys for model services. Azure OpenAI runs with local auth disabled;
    workloads authenticate with managed / workload identity.

## 2. Data protection
2.1 Every request declares a **data classification**. Models declare a maximum
    classification. Requests above clearance are rejected; fallbacks never downgrade.
2.2 Client identifiers (birth number, IBAN, card number, e-mail, phone) are **redacted**
    at the gateway before leaving the bank boundary, regardless of classification.
2.3 Production model deployments process data inside the **EU data zone**.
2.4 Prompts and completions are **not stored** by default; audit holds hashes and metadata.
2.5 PaaS services (model, messaging, secrets, registry) are reachable via **private
    endpoints** only.

## 3. Model lifecycle
3.1 Models are onboarded by PR to the **model registry** with: owner, purpose, data
    clearance, cost, fallback, evaluation results. Security and model-risk approve.
3.2 Deployments pin model versions (`NoAutoUpgrade`). Version changes go through the
    evaluation gate (§5) before promotion.
3.3 Retired models stay in the registry as `blocked` so callers get an explicit error.

## 4. Application design
4.1 **Deterministic first.** Use rules/code for anything that can be specified exactly;
    use the LLM for judgement, language and unstructured input.
4.2 LLM output that drives a process must be **structured** (JSON mode / schema) and
    **validated**; invalid output is discarded, not "repaired" silently.
4.3 Design for **degradation**: define what the system does when the model is slow,
    unavailable, or refuses.
4.4 Treat all document and user content as **data, not instructions** — state this in
    system prompts and screen input for prompt injection.
4.5 Decisions with legal or customer impact keep a **human in the loop** and record who
    approved what.
4.6 Long-running or high-volume AI work is **asynchronous** (Kafka); interactive use is
    synchronous with timeouts.

## 5. Evaluation & monitoring
5.1 Every use case has a **golden set** with expected outcomes and a CI gate on the
    metrics that matter (e.g. recall of refusal-grade discrepancies).
5.2 The gateway emits per-request **metrics** (latency, tokens, cost, fallbacks,
    redactions, blocks) and an **audit event**; dashboards and alerts are mandatory
    for production tenants.
5.3 Fallback rate, block rate and cost per tenant are reviewed monthly.

## 6. Regulatory mapping (indicative)
| Requirement | Where it is met |
|---|---|
| EU AI Act — record-keeping, human oversight, transparency | Audit stream (§5.2), human-in-the-loop (§4.5), registry metadata (§3.1) |
| DORA — ICT risk, third-party / concentration risk, resilience | Fallback chains, registry-controlled providers, HPA/PDB/zones, DLQ |
| GDPR — minimisation, purpose limitation, records of processing | Redaction (§2.2), no content storage (§2.4), tenant purpose in registry |
| ČNB / EBA outsourcing & cloud guidelines | Private endpoints, EU data zone, Entra-only access, Key Vault |
