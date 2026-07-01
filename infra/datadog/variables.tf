variable "datadog_api_key" {
  description = "Datadog API key."
  type        = string
  sensitive   = true
}

variable "datadog_app_key" {
  description = "Datadog application key."
  type        = string
  sensitive   = true
}

variable "datadog_site" {
  description = "Datadog site, for example datadoghq.com or ap1.datadoghq.com."
  type        = string
  default     = "datadoghq.com"
}

variable "team_name" {
  description = "Team name used in tags and monitor names."
  type        = string
  default     = "ADMO"
}

variable "sre_agent_webhook_url" {
  description = "Externally reachable SRE agent webhook URL."
  type        = string
  default     = "https://ttom2d8uod.execute-api.ap-southeast-3.amazonaws.com/webhook"
}
