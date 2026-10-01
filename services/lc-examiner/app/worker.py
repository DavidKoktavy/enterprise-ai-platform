"""Kafka worker: trade.lc.presentations -> trade.lc.examinations

Delivery semantics: at-least-once. Offsets are committed only after the result
(or the DLQ record) is acknowledged by the broker; results are keyed by
presentation_id so downstream consumers can de-duplicate idempotently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.helpers import create_ssl_context

from .llm import GatewayClient
from .service import examine, parse_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("lc.worker")

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
IN_TOPIC = os.getenv("KAFKA_IN_TOPIC", "trade.lc.presentations")
OUT_TOPIC = os.getenv("KAFKA_OUT_TOPIC", "trade.lc.examinations")
DLQ_TOPIC = os.getenv("KAFKA_DLQ_TOPIC", "trade.lc.presentations.dlq")
GROUP = os.getenv("KAFKA_GROUP", "lc-examiner")


def _security() -> dict:
    if os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT") == "SASL_SSL":
        return dict(
            security_protocol="SASL_SSL",
            sasl_mechanism="PLAIN",
            sasl_plain_username="$ConnectionString",
            sasl_plain_password=os.environ["KAFKA_SASL_PASSWORD"],
            ssl_context=create_ssl_context(),
        )
    return {}


async def run() -> None:
    consumer = AIOKafkaConsumer(
        IN_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id=GROUP,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        **_security(),
    )
    producer = AIOKafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        acks="all",
        enable_idempotence=True,
        **_security(),
    )
    gateway = GatewayClient()
    await consumer.start()
    await producer.start()
    log.info("consuming %s -> %s (group=%s)", IN_TOPIC, OUT_TOPIC, GROUP)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)  # graceful shutdown on pod termination

    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=20)
            for _tp, records in batch.items():
                for rec in records:
                    try:
                        req = parse_request(rec.value)
                        result = await examine(req, gateway)
                        await producer.send_and_wait(
                            OUT_TOPIC,
                            result.model_dump_json().encode(),
                            key=result.presentation_id.encode(),
                        )
                        log.info("%s -> %s (%d findings)", result.presentation_id,
                                 result.status, len(result.findings))
                    except Exception as exc:  # poison message -> DLQ, never block the partition
                        log.exception("failed offset %s; routing to DLQ", rec.offset)
                        await producer.send_and_wait(
                            DLQ_TOPIC,
                            json.dumps({"error": str(exc), "offset": rec.offset,
                                        "payload": rec.value.decode(errors="replace")}).encode(),
                            key=rec.key,
                        )
            if batch:
                await consumer.commit()
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(run())
