# ADR-0005: Hybrid rules + LLM, with mandatory human review, for LC examination

**Status:** Accepted · **Date:** 2026-09

## Context
Documentary credit examination (UCP 600) is a legally consequential decision:
a wrongful refusal or a wrongful honour creates liability for the bank. The bank
has at most five banking days to examine (Art. 14(b)). Most checks are mechanical
(dates, amounts, tolerances, parties, ports); a few are judgement-based (does the
invoice goods description *correspond* with the credit — Art. 18(c)).

## Decision
1. **Deterministic rules are the system of record** for mechanical checks; each finding
   cites the UCP 600 article.
2. **The LLM may only add findings**, never remove one, and only for judgement areas.
   Its output is constrained to JSON and schema-validated; anything malformed is dropped.
3. **Graceful degradation:** if the gateway or model is unavailable, the result is
   produced from rules alone (`llm_used=false`).
4. **Human in the loop:** every result has `needs_human_review=true`. The system
   recommends; a qualified examiner decides (four-eyes principle).
5. **Evaluation gate:** a labelled golden set runs in CI; recall on refusal-grade rules
   must stay at 100 %. The same harness runs with `--with-llm` before any model or
   prompt version change.

## Consequences
+ Explainable, article-referenced output for auditors and for the presenter.
+ Model changes cannot silently weaken hard checks.
− Rule maintenance requires trade-finance expertise; ISBP 821 nuances (e.g. Art. 20(c)(ii)
  container transhipment) are flagged as warnings for the examiner rather than decided.
