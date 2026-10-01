"""Print examination results from Kafka as they arrive (Ctrl+C to stop)."""

import asyncio
import json
import os

from aiokafka import AIOKafkaConsumer


async def main() -> None:
    consumer = AIOKafkaConsumer(
        "trade.lc.examinations",
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
        auto_offset_reset="earliest",
        group_id=None,
    )
    await consumer.start()
    try:
        async for msg in consumer:
            r = json.loads(msg.value)
            print(f"\n=== {r['presentation_id']}  {r['status']}  "
                  f"(deadline {r['examination_deadline']}, llm={r['llm_model']})")
            for f in r["findings"]:
                print(f"  [{f['severity']:11}] Art. {f['ucp_article']:12} {f['message']}")
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
