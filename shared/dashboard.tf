terraform {
  required_providers {
    datadog = { source = "DataDog/datadog" }
  }
}
 
provider "datadog" {
  api_key = var.datadog_api_key
  app_key = var.datadog_app_key
}

resource "datadog_dashboard" "llm_starter" {
  title       = "Jakarta Hackathon — LLM Observability Starter"
  layout_type = "ordered"
  description = "Delete and rebuild this to earn your Dashboard Live checkpoint"
 
  # Widget 1: Request rate by model
  widget {
    timeseries_definition {
      title = "LLM Request Rate by Model"
      request {
        q            = "sum:ml_obs.trace{*} by {model_name}.as_rate()"
        display_type = "line"
      }
    }
  }
 
  # Widget 2: P95 latency
  widget {
    timeseries_definition {
      title = "P95 Duration"
      request {
        q            = "p95:ml_obs.trace.duration{*}"
        display_type = "line"
      }
    }
  }
 
  # Widget 3: Total token cost (last hour)
  widget {
    query_value_definition {
      title     = "Total Tokens (last 1h)"
      autoscale = true
      request {
        q          = "sum:ml_obs.span.llm.total.cost{*}.as_count()"
        aggregator = "sum"
      }
    }
  }
 
  # Widget 4: Error rate
  widget {
    timeseries_definition {
      title = "LLM Error Rate"
      request {
        q            = "sum:ml_obs.trace.error{*}.as_count()"
        display_type = "bars"
      }
    }
  }
}

