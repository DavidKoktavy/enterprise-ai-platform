# ---------------------------------------------------------------------------
# Azure OpenAI — private only, Entra ID only (local_auth_enabled = false):
# no API keys exist that could leak. Access is granted per workload identity.
# ---------------------------------------------------------------------------
resource "azurerm_cognitive_account" "openai" {
  name                          = "oai-${local.name}-${local.suffix}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "oai-${local.name}-${local.suffix}"
  public_network_access_enabled = false
  local_auth_enabled            = false
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }

  network_acls {
    default_action = "Deny"
  }
}

resource "azurerm_cognitive_deployment" "this" {
  for_each               = var.openai_deployments
  name                   = each.key # == "deployment" in services/gateway/config/models.yaml
  cognitive_account_id   = azurerm_cognitive_account.openai.id
  version_upgrade_option = "NoAutoUpgrade" # model versions change only via PR + eval gate

  model {
    format  = "OpenAI"
    name    = each.value.model_name
    version = each.value.model_version
  }

  sku {
    name     = each.value.sku
    capacity = each.value.capacity
  }
}

resource "azurerm_private_endpoint" "openai" {
  name                = "pe-oai-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-openai"
    private_connection_resource_id = azurerm_cognitive_account.openai.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "openai"
    private_dns_zone_ids = [azurerm_private_dns_zone.this["openai"].id]
  }
}

# Every prompt/response metadata event to Log Analytics -> Sentinel
resource "azurerm_monitor_diagnostic_setting" "openai" {
  name                       = "diag-openai"
  target_resource_id         = azurerm_cognitive_account.openai.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  enabled_log {
    category_group = "allLogs"
  }
  metric {
    category = "AllMetrics"
  }
}
