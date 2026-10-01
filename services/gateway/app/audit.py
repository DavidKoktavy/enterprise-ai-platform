"""Audit trail: every LLM call produces one immutable event on Kafka.

Consumers of `ai.gateway.audit`: SIEM (Sentinel), FinOps cost dashboards,
model-risk monitoring (EU AI Act / DORA evidence), usage analytics.

Content is NOT stored by default — only SHA-256 hashes plus metadata
(GDPR data minimisation). Set AUDIT_STORE_CONTENT=true for non-prod debugging.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Protocol

log = logging.getLogger("gateway.audit")


class AuditSink(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def emit(self, event: dict) -> None: ...


class MemoryAuditSink:
    """Used in tests and when Kafka is not configured."""

    def __init__(self, maxlen: int = 1000):
        self.events: deque[dict] = deque(maxlen=maxlen)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def emit(self, event: dict) -> None:
        self.events.append(event)
        log.info("audit %s", json.dumps(event, default=str))


class KafkaAuditSink:
    """aiokafka producer; works with Apache Kafka and Azure Event Hubs (Kafka API).

    Event Hubs: bootstrap `<ns>.servicebus.windows.net:9093`, SASL_SSL/PLAIN,
    username `$ConnectionString`, password = connection string (from Key Vault).
    """

    def __init__(self, bootstrap: str, topic: str, security_protocol: str, sasl_password: str):
        self.bootstrap, self.topic = bootstrap, topic
        self.security_protocol, self.sasl_password = security_protocol, sasl_password
        self._producer = None
        self._fallback = MemoryAuditSink()

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer
        from aiokafka.helpers import create_ssl_context

        kwargs: dict = {
            "bootstrap_servers": self.bootstrap,
            "acks": "all",
            "enable_idempotence": True,
            "value_serializer": lambda v: json.dumps(v, default=str).encode(),
            "key_serializer": lambda k: k.encode() if k else None,
        }
        if self.security_protocol == "SASL_SSL":
            kwargs.update(
                security_protocol="SASL_SSL",
                sasl_mechanism="PLAIN",
                sasl_plain_username="$ConnectionString",
                sasl_plain_password=self.sasl_password,
                ssl_context=create_ssl_context(),
            )
        self._producer = AIOKafkaProducer(**kwargs)
        await self._producer.start()
        log.info("kafka audit sink connected to %s topic=%s", self.bootstrap, self.topic)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def emit(self, event: dict) -> None:
        try:
            assert self._producer is not None
            # key by tenant -> per-tenant ordering within a partition
            await self._producer.send_and_wait(self.topic, event, key=event.get("tenant"))
        except Exception:  # never fail the user request because audit is down…
            log.exception("audit emit failed; buffering locally")
            await self._fallback.emit(event)  # …but never lose the event silently either
