"""Publish the sample LC presentations to Kafka (local docker-compose stack)."""

import asyncio
import json
import os
from pathlib import Path

from aiokafka import AIOKafkaProducer

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


async def main() -> None:
    producer = AIOKafkaProducer(bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"))
    await producer.start()
    try:
        for f in sorted(SAMPLES.glob("presentation_*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            key = data["presentation"]["presentation_id"].encode()
            await producer.send_and_wait(
                "trade.lc.presentations", json.dumps(data).encode(), key=key
            )
            print(f"sent {f.name} key={key.decode()}")
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
