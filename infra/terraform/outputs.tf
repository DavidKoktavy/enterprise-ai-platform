# Consumed by .github/workflows/deploy.yml to fill the <PLACEHOLDERS> in deploy/k8s/overlays/azure
output "resource_group" { value = azurerm_resource_group.this.name }
output "aks_name" { value = azurerm_kubernetes_cluster.this.name }
output "acr_name" { value = azurerm_container_registry.this.name }
output "key_vault_name" { value = azurerm_key_vault.this.name }
output "eventhubs_namespace" { value = azurerm_eventhub_namespace.this.name }
output "openai_endpoint" { value = azurerm_cognitive_account.openai.endpoint }
output "gateway_identity_client_id" { value = azurerm_user_assigned_identity.gateway.client_id }
output "tenant_id" { value = data.azurerm_client_config.current.tenant_id }
