# ---------------------------------------------------------------------------
# Identity: one user-assigned managed identity per workload, federated with
# its Kubernetes ServiceAccount (AKS Workload Identity). Least privilege RBAC.
# ---------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "gateway" {
  name                = "id-ai-gateway-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "gateway" {
  name                = "fic-ai-gateway"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.gateway.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:ai-platform:ai-gateway"
}

# The gateway is the ONLY identity allowed to call Azure OpenAI.
resource "azurerm_role_assignment" "gateway_openai" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.gateway.principal_id
}

# ---------------------------------------------------------------------------
# Key Vault (RBAC mode, private)
# ---------------------------------------------------------------------------
resource "azurerm_key_vault" "this" {
  name                          = "kv-${var.prefix}-${var.environment}-${local.suffix}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = true # deployment runner needs access; restrict via network_acls in prod
  tags                          = local.tags

  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }
}

resource "azurerm_role_assignment" "deployer_kv_officer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "gateway_kv_reader" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.gateway.principal_id
}

resource "random_password" "tenant_keys" {
  for_each = toset(["trade-finance", "retail-chatbot"])
  length   = 40
  special  = false
}

resource "azurerm_key_vault_secret" "this" {
  for_each = {
    "azure-openai-endpoint"       = azurerm_cognitive_account.openai.endpoint
    "eventhubs-connection-string" = azurerm_eventhub_namespace_authorization_rule.apps.primary_connection_string
    "tenant-key-trade-finance"    = random_password.tenant_keys["trade-finance"].result
    "tenant-key-retail-chatbot"   = random_password.tenant_keys["retail-chatbot"].result
  }
  name         = each.key
  value        = each.value
  key_vault_id = azurerm_key_vault.this.id
  content_type = "text/plain"
  depends_on   = [azurerm_role_assignment.deployer_kv_officer]
}

resource "azurerm_private_endpoint" "keyvault" {
  name                = "pe-kv-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-keyvault"
    private_connection_resource_id = azurerm_key_vault.this.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "keyvault"
    private_dns_zone_ids = [azurerm_private_dns_zone.this["keyvault"].id]
  }
}
