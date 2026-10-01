resource "azurerm_kubernetes_cluster" "this" {
  name                      = "aks-${local.name}"
  location                  = azurerm_resource_group.this.location
  resource_group_name       = azurerm_resource_group.this.name
  dns_prefix                = local.name
  sku_tier                  = "Standard" # uptime SLA
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"
  local_account_disabled    = true # Entra ID only
  oidc_issuer_enabled       = true # \  pods get Entra ID tokens
  workload_identity_enabled = true # /  without stored secrets
  azure_policy_enabled      = true
  tags                      = local.tags

  default_node_pool {
    name                        = "system"
    vm_size                     = var.aks_node_vm_size
    node_count                  = var.aks_node_count
    vnet_subnet_id              = azurerm_subnet.aks.id
    zones                       = ["1", "2", "3"]
    temporary_name_for_rotation = "systemtmp"
    upgrade_settings {
      max_surge = "33%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium" # enforces deploy/k8s/base/networkpolicies.yaml
    outbound_type       = "loadBalancer"
  }

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  workload_autoscaler_profile {
    keda_enabled = true
  }

  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.this.id
    msi_auth_for_monitoring_enabled = true
  }
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.this.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}
