locals {
  name   = "${var.prefix}-${var.environment}"
  suffix = random_string.suffix.result
  tags   = merge(var.tags, { environment = var.environment })
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------
# Network: AKS subnet + dedicated private-endpoint subnet. All PaaS services
# (Azure OpenAI, Event Hubs, Key Vault, ACR) are reachable only privately.
# ---------------------------------------------------------------------------
resource "azurerm_virtual_network" "this" {
  name                = "vnet-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 4, 0)] # 10.20.0.0/20
}

resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 8, 16)] # 10.20.16.0/24
}

locals {
  private_dns_zones = {
    openai    = "privatelink.openai.azure.com"
    eventhubs = "privatelink.servicebus.windows.net"
    keyvault  = "privatelink.vaultcore.azure.net"
    acr       = "privatelink.azurecr.io"
  }
}

resource "azurerm_private_dns_zone" "this" {
  for_each            = local.private_dns_zones
  name                = each.value
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  for_each              = local.private_dns_zones
  name                  = "link-${each.key}"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.this[each.key].name
  virtual_network_id    = azurerm_virtual_network.this.id
}

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 90
  tags                = local.tags
}

# ---------------------------------------------------------------------------
# Container registry (Premium = private endpoint support)
# ---------------------------------------------------------------------------
resource "azurerm_container_registry" "this" {
  name                          = "acr${var.prefix}${var.environment}${local.suffix}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = true # CI pushes from GitHub-hosted runners; lock down with self-hosted runners
  tags                          = local.tags
}

resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-acr"
    private_connection_resource_id = azurerm_container_registry.this.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "acr"
    private_dns_zone_ids = [azurerm_private_dns_zone.this["acr"].id]
  }
}
