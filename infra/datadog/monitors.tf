locals {
  common_tags = [
    "team:${var.team_name}",
    "env:hackathon",
    "service:auth-service",
    "managed-by:terraform",
    "hackathon:jkt-2026"
  ]
}

resource "datadog_webhook" "sre_agent" {
  name      = "sre_agent"
  url       = var.sre_agent_webhook_url
  encode_as = "json"

  payload = jsonencode({
    event_type = "monitor"
    source     = "datadog"
    title      = "$EVENT_TITLE"
    body       = "$EVENT_MSG"
    url        = "$LINK"
    tags       = "$TAGS"
    alert_type = "$ALERT_STATUS"
    monitor = {
      id   = "$MONITOR_ID"
      name = "$MONITOR_NAME"
    }
  })
}

resource "datadog_monitor" "auth_service_database_timeout" {
  name = "[${var.team_name}] auth-service database timeout incident"
  type = "query alert"

  query = "sum(last_1m):sum:auth.errors.database_timeout{env:hackathon,service:auth-service}.as_count() > 0"

  message = <<-EOT
  Auth-service is returning DATABASE_TIMEOUT errors.

  Impact:
  - Users may fail auth token validation.
  - This should create APM/log evidence and trigger the SRE agent investigation flow.

  Runbook:
  1. Open service auth-service in APM and inspect recent 5xx traces.
  2. Check Kubernetes deployment: `kubectl -n hackathon get deploy,pods`.
  3. Confirm whether chaos mode is active.
  4. Let the SRE agent investigate and auto-remediate by calling `/api/v1/admin/chaos/deactivate`.
  5. Verify recovery with `/api/v1/auth/validate`.

  Webhook target:
  ${var.sre_agent_webhook_url}

  @webhook-sre_agent
  EOT

  monitor_thresholds {
    critical = 0
  }

  include_tags        = true
  notify_no_data      = false
  require_full_window = false
  renotify_interval   = 0
  priority            = 2
  tags                = local.common_tags

  depends_on = [datadog_webhook.sre_agent]
}

resource "datadog_monitor_notification_rule" "auth_service_to_sre_agent" {
  name       = "[${var.team_name}] route auth-service alerts to sre-agent"
  recipients = ["webhook-sre_agent"]

  filter {
    tags = [
      "env:hackathon",
      "service:auth-service",
      "team:${var.team_name}"
    ]
  }

  depends_on = [datadog_webhook.sre_agent]
}

resource "datadog_service_level_objective" "auth_service_availability" {
  name        = "[${var.team_name}] auth-service availability"
  type        = "monitor"
  description = "Hackathon SLO tied to the auth-service database timeout monitor. Used for Ops Ready Bonus demo."

  monitor_ids = [datadog_monitor.auth_service_database_timeout.id]

  thresholds {
    timeframe = "7d"
    target    = 99
    warning   = 99.5
  }

  tags = local.common_tags
}
