# ---------------------------------------------------------------------------
# Azure Event Hubs with the Kafka protocol endpoint (port 9093).
# Applications use the standard Kafka client — only bootstrap + SASL change
# between local Kafka and Azure (see ADR-0003).
# ---------------------------------------------------------------------------
resource "azurerm_eventhub_namespace" "this" {
  name                          = "evhns-${local.name}-${local.suffix}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  sku                           = "Standard" # Kafka endpoint requires Standard or higher
  capacity                      = 2
  auto_inflate_enabled          = true
  maximum_throughput_units      = 10
  public_network_access_enabled = false
  minimum_tls_version           = "1.2"
  tags                          = local.tags
}

resource "azurerm_eventhub" "topics" {
  for_each          = var.kafka_topics
  name              = each.key
  namespace_id      = azurerm_eventhub_namespace.this.id
  partition_count   = each.value
  message_retention = 7
}

resource "azurerm_eventhub_consumer_group" "lc_examiner" {
  name                = "lc-examiner"
  namespace_name      = azurerm_eventhub_namespace.this.name
  eventhub_name       = azurerm_eventhub.topics["trade.lc.presentations"].name
  resource_group_name = azurerm_resource_group.this.name
}

# Namespace-level SAS for the Kafka SASL/PLAIN handshake (stored in Key Vault).
# Hardening path: OAUTHBEARER with workload identity tokens instead of SAS.
resource "azurerm_eventhub_namespace_authorization_rule" "apps" {
  name                = "apps-send-listen"
  namespace_name      = azurerm_eventhub_namespace.this.name
  resource_group_name = azurerm_resource_group.this.name
  listen              = true
  send                = true
  manage              = false
}

resource "azurerm_private_endpoint" "eventhubs" {
  name                = "pe-evh-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-eventhubs"
    private_connection_resource_id = azurerm_eventhub_namespace.this.id
    subresource_names              = ["namespace"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "eventhubs"
    private_dns_zone_ids = [azurerm_private_dns_zone.this["eventhubs"].id]
  }
}
