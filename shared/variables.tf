# variables.tf
variable "datadog_api_key" {
  description = "Datadog API key"
  sensitive   = true
}

variable "datadog_app_key" {
  description = "Datadog Application key"
  sensitive   = true
}

variable "team_name" {
  description = "Your team name (used in resource names and tags)"
}
