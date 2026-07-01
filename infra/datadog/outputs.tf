output "sre_agent_webhook_url" {
  description = "Webhook URL used by Datadog to call the SRE agent."
  value       = var.sre_agent_webhook_url
}

output "auth_service_monitor_id" {
  description = "Datadog monitor ID for auth-service database timeout incidents."
  value       = datadog_monitor.auth_service_database_timeout.id
}

output "auth_service_slo_id" {
  description = "Datadog SLO ID for auth-service availability."
  value       = datadog_service_level_objective.auth_service_availability.id
}
