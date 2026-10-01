variable "prefix" {
  description = "Short name prefix for all resources"
  type        = string
  default     = "aiplat"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "location" {
  description = "Azure region. Sweden Central has the broadest Azure OpenAI model availability in the EU."
  type        = string
  default     = "swedencentral"
}

variable "vnet_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "aks_node_vm_size" {
  type    = string
  default = "Standard_D4s_v5"
}

variable "aks_node_count" {
  type    = number
  default = 3
}

variable "openai_deployments" {
  description = "Azure OpenAI model deployments. DataZoneStandard keeps processing inside the EU data zone."
  type = map(object({
    model_name    = string
    model_version = string
    sku           = string
    capacity      = number # thousands of tokens per minute
  }))
  default = {
    "gpt-4o" = {
      model_name    = "gpt-4o"
      model_version = "2024-11-20"
      sku           = "DataZoneStandard"
      capacity      = 50
    }
    "gpt-4o-mini" = {
      model_name    = "gpt-4o-mini"
      model_version = "2024-07-18"
      sku           = "DataZoneStandard"
      capacity      = 100
    }
  }
}

variable "kafka_topics" {
  description = "Event Hubs (Kafka topics) and partition counts"
  type        = map(number)
  default = {
    "ai.gateway.audit"           = 6
    "trade.lc.presentations"     = 3
    "trade.lc.examinations"      = 3
    "trade.lc.presentations.dlq" = 1
  }
}

variable "tags" {
  type = map(string)
  default = {
    workload    = "enterprise-ai-platform"
    owner       = "ai-platform-team"
    cost-center = "ai-cc-001"
    data-class  = "confidential"
  }
}
