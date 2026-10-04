# Deployment failures are structured logs from the GitOps release workflow
# and the Argo CD application observer. Email delivery is managed by Google.
variable "deployment_alert_email" {
  description = "Recipient of production deployment failure emails."
  type        = string
  default     = "rwendt1337@gmail.com"
}

resource "google_monitoring_notification_channel" "deployment_failures" {
  project      = var.project_id
  display_name = "Computer Use deployment failures"
  type         = "email"
  enabled      = true
  labels = {
    email_address = var.deployment_alert_email
  }
  depends_on = [google_project_service.this["monitoring.googleapis.com"]]
}

resource "google_monitoring_alert_policy" "deployment_failures" {
  project               = var.project_id
  display_name          = "Computer Use production deployment failed"
  combiner              = "OR"
  enabled               = true
  notification_channels = [google_monitoring_notification_channel.deployment_failures.name]
  documentation {
    mime_type = "text/markdown"
    content   = "A Computer Use production release failed. Check [production release workflows](https://github.com/r33drichards/computer-use/actions/workflows/gitops-release.yml) for the release and rollback result. Argo CD application: `computer-use-production`."
  }
  conditions {
    display_name = "Deployment failure"
    condition_matched_log {
      filter = "jsonPayload.event=\"deployment_failed\" AND jsonPayload.application=\"computer-use-production\""
      label_extractors = {
        revision = "EXTRACT(jsonPayload.revision)"
      }
    }
  }
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
}

resource "google_project_iam_member" "deployer_deployment_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.deployer.member
}
