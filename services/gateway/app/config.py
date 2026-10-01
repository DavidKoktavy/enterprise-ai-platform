"""Runtime settings, read from environment variables (12-factor).

In Kubernetes these come from a ConfigMap + Azure Key Vault via the
Secrets Store CSI driver; locally from docker-compose / .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    registry_path: str = field(
        default_factory=lambda: os.getenv("REGISTRY_PATH", "config/models.yaml")
    )
    # Azure OpenAI
    azure_openai_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "")
    )
    azure_openai_api_version: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    )
    # If set, key auth is used (local dev only). Otherwise Entra ID via
    # workload identity (DefaultAzureCredential) — the production path.
    azure_openai_api_key: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", "")
    )
    force_mock: bool = field(default_factory=lambda: _bool("FORCE_MOCK_PROVIDER", False))
    request_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT_S", "30"))
    )
    # Kafka (Azure Event Hubs Kafka endpoint in Azure, plain Kafka locally)
    kafka_bootstrap: str = field(default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP", ""))
    kafka_audit_topic: str = field(
        default_factory=lambda: os.getenv("KAFKA_AUDIT_TOPIC", "ai.gateway.audit")
    )
    kafka_security_protocol: str = field(
        default_factory=lambda: os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    )
    kafka_sasl_password: str = field(
        default_factory=lambda: os.getenv("KAFKA_SASL_PASSWORD", "")
    )
    # Guardrails
    redact_pii: bool = field(default_factory=lambda: _bool("REDACT_PII", True))
    block_prompt_injection: bool = field(
        default_factory=lambda: _bool("BLOCK_PROMPT_INJECTION", True)
    )
    # Store prompts in audit log? Default off — store hashes only (GDPR minimisation).
    audit_store_content: bool = field(
        default_factory=lambda: _bool("AUDIT_STORE_CONTENT", False)
    )


def get_settings() -> Settings:
    return Settings()
