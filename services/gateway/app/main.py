"""AI Gateway — the single, governed entry point to LLMs for every bank application.

POST /v1/chat/completions   OpenAI-compatible chat API (+ x-data-classification header)
GET  /v1/models             models the calling tenant may use
GET  /healthz, /readyz      Kubernetes probes
GET  /metrics               Prometheus metrics
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from .audit import AuditSink, KafkaAuditSink, MemoryAuditSink
from .config import Settings, get_settings
from .guardrails import detect_prompt_injection, redact
from .providers.base import Provider, ProviderError
from .providers.mock import MockProvider
from .ratelimit import BudgetTracker, RateLimiter
from .registry import Classification, Registry, RoutingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gateway")


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(0.0, ge=0, le=2)
    max_tokens: int = Field(800, ge=1, le=16000)
    response_format: dict | None = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_providers(settings: Settings) -> dict[str, Provider]:
    providers: dict[str, Provider] = {"mock": MockProvider()}
    if settings.force_mock:
        providers["azure_openai"] = MockProvider()
    elif settings.azure_openai_endpoint:
        from .providers.azure_openai import AzureOpenAIProvider

        providers["azure_openai"] = AzureOpenAIProvider(
            settings.azure_openai_endpoint,
            settings.azure_openai_api_version,
            settings.azure_openai_api_key,
            settings.request_timeout_s,
        )
    return providers


def build_audit_sink(settings: Settings) -> AuditSink:
    if settings.kafka_bootstrap:
        return KafkaAuditSink(
            settings.kafka_bootstrap,
            settings.kafka_audit_topic,
            settings.kafka_security_protocol,
            settings.kafka_sasl_password,
        )
    return MemoryAuditSink()


def create_app(
    settings: Settings | None = None,
    registry: Registry | None = None,
    providers: dict[str, Provider] | None = None,
    audit: AuditSink | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    registry = registry or Registry.load(settings.registry_path)
    providers = providers if providers is not None else build_providers(settings)
    audit = audit or build_audit_sink(settings)
    limiter, budgets = RateLimiter(), BudgetTracker()

    metrics = CollectorRegistry()
    m_requests = Counter(
        "gateway_requests_total", "LLM requests", ["tenant", "model", "outcome"], registry=metrics
    )
    m_tokens = Counter(
        "gateway_tokens_total", "Tokens processed", ["tenant", "model", "kind"], registry=metrics
    )
    m_cost = Counter("gateway_cost_eur_total", "Spend in EUR", ["tenant", "model"], registry=metrics)
    m_latency = Histogram(
        "gateway_upstream_latency_seconds", "Upstream LLM latency", ["model"], registry=metrics
    )
    m_redactions = Counter(
        "gateway_pii_redactions_total", "PII entities redacted", ["type"], registry=metrics
    )
    m_fallbacks = Counter(
        "gateway_fallbacks_total", "Fallback activations", ["from_model", "to_model"], registry=metrics
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            await audit.start()
        except Exception:
            log.exception("audit sink failed to start — continuing with degraded audit")
        yield
        await audit.stop()

    app = FastAPI(title="Enterprise AI Gateway", version="1.0.0", lifespan=lifespan)
    app.state.audit = audit
    app.state.registry = registry

    def _tenant(api_key: str | None):
        t = registry.tenant_for_key(api_key)
        if t is None:
            raise HTTPException(401, {"code": "unauthorized", "message": "invalid API key"})
        return t

    @app.exception_handler(RoutingError)
    async def _routing_error(_: Request, exc: RoutingError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, exc.status)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        missing = sorted(
            {m.provider for m in registry.models.values() if m.status == "active"} - providers.keys()
        )
        return {"status": "ready", "unconfigured_providers": missing}

    @app.get("/metrics")
    async def prom():
        return PlainTextResponse(generate_latest(metrics), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/models")
    async def list_models(x_api_key: str | None = Header(default=None)):
        tenant = _tenant(x_api_key)
        return {
            "object": "list",
            "data": [
                {
                    "id": m.alias,
                    "description": m.description,
                    "max_classification": m.max_classification.name,
                    "context_window": m.context_window,
                    "status": m.status,
                }
                for m in registry.models.values()
                if m.alias in tenant.allowed_models
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat(
        req: ChatRequest,
        x_api_key: str | None = Header(default=None),
        x_data_classification: str = Header(default="internal"),
        x_request_id: str | None = Header(default=None),
    ):
        request_id = x_request_id or str(uuid.uuid4())
        tenant = _tenant(x_api_key)
        try:
            classification = Classification.parse(x_data_classification)
        except ValueError as exc:
            raise HTTPException(400, {"code": "bad_classification", "message": str(exc)}) from exc

        if not limiter.allow(tenant.id, tenant.requests_per_minute):
            m_requests.labels(tenant.id, req.model, "rate_limited").inc()
            raise HTTPException(429, {"code": "rate_limited", "message": "tenant RPM exceeded"})
        if budgets.spent(tenant.id) >= tenant.monthly_budget_eur:
            m_requests.labels(tenant.id, req.model, "budget_exceeded").inc()
            raise HTTPException(402, {"code": "budget_exceeded", "message": "monthly budget used"})

        chain = registry.resolve(tenant, req.model, classification)

        # ---- input guardrails ------------------------------------------------
        messages: list[dict] = []
        pii: dict[str, int] = {}
        for msg in req.messages:
            content = msg.content
            if msg.role == "user" and settings.block_prompt_injection:
                hit = detect_prompt_injection(content)
                if hit:
                    m_requests.labels(tenant.id, req.model, "blocked_injection").inc()
                    await audit.emit(
                        {
                            "event": "llm.blocked",
                            "request_id": request_id,
                            "tenant": tenant.id,
                            "model": req.model,
                            "reason": "prompt_injection",
                            "ts": time.time(),
                        }
                    )
                    raise HTTPException(
                        400, {"code": "prompt_injection", "message": "request blocked by policy"}
                    )
            if settings.redact_pii and msg.role != "system":
                r = redact(content)
                content = r.text
                for k, v in r.findings.items():
                    pii[k] = pii.get(k, 0) + v
                    m_redactions.labels(k).inc(v)
            messages.append({"role": msg.role, "content": content})

        # ---- routing with fallback ------------------------------------------
        last_error: ProviderError | None = None
        for i, spec in enumerate(chain):
            provider = providers.get(spec.provider)
            if provider is None:
                last_error = ProviderError(f"provider '{spec.provider}' not configured", 503)
                continue
            if i > 0:
                m_fallbacks.labels(chain[0].alias, spec.alias).inc()
                log.warning("fallback %s -> %s (%s)", chain[0].alias, spec.alias, last_error)
            t0 = time.perf_counter()
            try:
                completion = await provider.chat(
                    spec.deployment,
                    messages,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    response_format=req.response_format,
                )
            except ProviderError as exc:
                last_error = exc
                if exc.retryable:
                    continue
                break
            latency = time.perf_counter() - t0
            m_latency.labels(spec.alias).observe(latency)

            cost = spec.cost_eur(completion.prompt_tokens, completion.completion_tokens)
            budgets.add(tenant.id, cost)
            m_requests.labels(tenant.id, spec.alias, "ok").inc()
            m_tokens.labels(tenant.id, spec.alias, "prompt").inc(completion.prompt_tokens)
            m_tokens.labels(tenant.id, spec.alias, "completion").inc(completion.completion_tokens)
            m_cost.labels(tenant.id, spec.alias).inc(cost)

            prompt_text = "\n".join(m["content"] for m in messages)
            event = {
                "event": "llm.completion",
                "request_id": request_id,
                "ts": time.time(),
                "tenant": tenant.id,
                "requested_model": req.model,
                "served_model": spec.alias,
                "deployment": spec.deployment,
                "region": spec.region,
                "classification": classification.name,
                "fallback_used": i > 0,
                "pii_redacted": pii,
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
                "cost_eur": cost,
                "latency_ms": round(latency * 1000, 1),
                "prompt_sha256": _sha(prompt_text),
                "completion_sha256": _sha(completion.content),
            }
            if settings.audit_store_content:
                event["prompt"], event["completion"] = prompt_text, completion.content
            await audit.emit(event)

            return JSONResponse(
                {
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": spec.alias,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": completion.content},
                            "finish_reason": completion.finish_reason,
                        }
                    ],
                    "usage": {
                        "prompt_tokens": completion.prompt_tokens,
                        "completion_tokens": completion.completion_tokens,
                        "total_tokens": completion.prompt_tokens + completion.completion_tokens,
                    },
                },
                headers={
                    "x-request-id": request_id,
                    "x-served-model": spec.alias,
                    "x-pii-redacted": str(sum(pii.values())),
                },
            )

        m_requests.labels(tenant.id, req.model, "upstream_error").inc()
        status = last_error.status if last_error and not last_error.retryable else 503
        raise HTTPException(
            status, {"code": "upstream_unavailable", "message": str(last_error)}
        )

    return app
