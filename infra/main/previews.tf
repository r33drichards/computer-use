# PR workloads have their own image repository. Production images and tags
# cannot be overwritten by the preview publisher.
resource "google_artifact_registry_repository" "previews" {
  count         = var.enable_previews ? 1 : 0
  repository_id = "${var.name}-previews"
  location      = var.region
  format        = "DOCKER"
  description   = "Temporary pull-request environment images"

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "expire-previews"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "1209600s" # Active preview tags keep their versions alive.
    }
  }
}

resource "google_service_account" "preview_publisher" {
  count        = var.enable_previews ? 1 : 0
  account_id   = "preview-publisher"
  display_name = "PR preview image publishing (trusted main workflows only)"
}

resource "google_artifact_registry_repository_iam_member" "preview_publish" {
  count      = var.enable_previews ? 1 : 0
  project    = var.project_id
  location   = google_artifact_registry_repository.previews[0].location
  repository = google_artifact_registry_repository.previews[0].name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.preview_publisher[0].member
}

resource "google_artifact_registry_repository_iam_member" "preview_pull" {
  count      = var.enable_previews ? 1 : 0
  project    = var.project_id
  location   = google_artifact_registry_repository.previews[0].location
  repository = google_artifact_registry_repository.previews[0].name
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.nodes.member
}

resource "google_service_account" "preview_deployer" {
  count        = var.enable_previews ? 1 : 0
  account_id   = "preview-deployer"
  display_name = "PR namespace lifecycle and edge routing (trusted main workflows only)"
}

# Namespace creation, namespaced Roles and RoleBindings, and Pomerium's
# routing ConfigMap require administrator privileges, as in iam.tf. This
# identity is NEVER available to PR build jobs or preview pods. Trusted
# main code validates every namespace, image digest and route before apply.
resource "google_project_iam_member" "preview_cluster" {
  count   = var.enable_previews ? 1 : 0
  project = var.project_id
  role    = "roles/container.admin"
  member  = google_service_account.preview_deployer[0].member
}

resource "google_service_account_iam_member" "preview_github" {
  for_each = var.enable_previews ? {
    publisher = google_service_account.preview_publisher[0].name
    deployer  = google_service_account.preview_deployer[0].name
  } : {}
  service_account_id = each.value
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${local.project_number}/locations/global/workloadIdentityPools/${var.github_wif_pool_id}/attribute.repository_id_ref/${var.github_repository_id}@refs/heads/main"
}

# Writer cannot delete tags. Give lifecycle cleanup only tag inspection and
# deletion, not image-version deletion, publication or repository IAM.
resource "google_project_iam_custom_role" "preview_tag_cleanup" {
  count       = var.enable_previews ? 1 : 0
  role_id     = "previewTagCleanup"
  title       = "PR preview tag cleanup"
  description = "Inspect and delete obsolete preview image tags"
  permissions = ["artifactregistry.tags.get", "artifactregistry.tags.list", "artifactregistry.tags.delete"]
}

resource "google_artifact_registry_repository_iam_member" "preview_cleanup" {
  count      = var.enable_previews ? 1 : 0
  project    = var.project_id
  location   = google_artifact_registry_repository.previews[0].location
  repository = google_artifact_registry_repository.previews[0].name
  role       = google_project_iam_custom_role.preview_tag_cleanup[0].name
  member     = google_service_account.preview_deployer[0].member
}
