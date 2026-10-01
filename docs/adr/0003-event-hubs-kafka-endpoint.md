# ADR-0003: Azure Event Hubs (Kafka protocol) instead of self-managed Kafka in Azure

**Status:** Accepted · **Date:** 2026-09

## Context
We need Kafka semantics in Azure. Options: Strimzi on AKS, Confluent Cloud, or
Azure Event Hubs with its Kafka-compatible endpoint.

## Decision
Use **Event Hubs Standard** with the Kafka endpoint (`<ns>.servicebus.windows.net:9093`).
Applications use the plain Kafka client (`aiokafka`); only bootstrap server and
SASL settings differ between local Apache Kafka and Azure — configured via env.

## Rationale
* No broker, ZooKeeper/KRaft or storage operations for the platform team.
* Private endpoint + Azure RBAC + diagnostic logs integrate with existing bank controls.
* Auto-inflate throughput units; Premium/Dedicated tiers available if needed.

## Trade-offs
* Not full Kafka: no compacted topics on Standard, no Kafka Streams state stores,
  partition count fixed at creation on Standard. None needed by current workloads.
* SAS connection string used for SASL/PLAIN today → move to OAUTHBEARER with
  workload identity (no shared secret).
* If future workloads need Kafka Streams / ksqlDB / Connect at scale, revisit
  (Confluent Cloud on Azure or Strimzi).
