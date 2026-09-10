locals {
  apis = toset(["artifactregistry.googleapis.com", "cloudbuild.googleapis.com", "run.googleapis.com", "sqladmin.googleapis.com", "secretmanager.googleapis.com", "storage.googleapis.com", "aiplatform.googleapis.com", "documentai.googleapis.com"])
  bucket = "${var.project_id}-qb-v4-data"
}
data "google_project" "current" {}
resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "question-bank"
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
}
resource "google_project_service" "api" {
  for_each = local.apis
  service = each.value
  disable_on_destroy = false
}
resource "google_service_account" "app" {
  account_id = "qb-cloud-v4"
  display_name = "Question Bank Cloud v4"
}
resource "google_storage_bucket" "data" {
  name = local.bucket
  location = var.region
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  force_destroy = false
  versioning {
    enabled = true
  }
  lifecycle_rule {
    condition {
      age = 90
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }
}
resource "google_storage_bucket_iam_member" "app" {
  bucket = google_storage_bucket.data.name
  role = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.app.email}"
}
resource "google_sql_database_instance" "postgres" {
  name = "qb-cloud-v4-postgres"
  region = var.region
  database_version = "POSTGRES_17"
  deletion_protection = true
  settings {
    edition = "ENTERPRISE"
    tier    = var.database_tier
    availability_type = var.high_availability ? "REGIONAL" : "ZONAL"
    disk_type = "PD_SSD"
    disk_size = 20
    disk_autoresize = true
    backup_configuration {
      enabled = true
      point_in_time_recovery_enabled = true
      start_time = "20:00"
      transaction_log_retention_days = 7
    }
    ip_configuration {
      ipv4_enabled = true
      ssl_mode = "ENCRYPTED_ONLY"
    }
  }
  depends_on = [google_project_service.api]
}
resource "google_sql_database" "app" {
  name = "question_bank"
  instance = google_sql_database_instance.postgres.name
}
resource "random_password" "database" {
  length = 32
  special = false
}
resource "google_sql_user" "app" {
  name = "question_bank_app"
  instance = google_sql_database_instance.postgres.name
  password = random_password.database.result
}
resource "google_secret_manager_secret" "database_url" {
  secret_id = "qb-cloud-v4-database-url"
  replication {
    auto {}
  }
}
resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = "postgresql+psycopg://${google_sql_user.app.name}:${random_password.database.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
}
resource "google_secret_manager_secret_iam_member" "database" {
  secret_id = google_secret_manager_secret.database_url.id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.app.email}"
}
resource "google_secret_manager_secret" "app" {
  for_each  = nonsensitive(toset(keys(var.secret_env)))
  secret_id = "qb-cloud-v4-${lower(replace(each.key, "_", "-"))}"
  replication {
    auto {}
  }
}
resource "google_secret_manager_secret_version" "app" {
  for_each    = nonsensitive(toset(keys(var.secret_env)))
  secret      = google_secret_manager_secret.app[each.key].id
  secret_data = var.secret_env[each.key]
}
resource "google_secret_manager_secret_iam_member" "app" {
  for_each  = nonsensitive(toset(keys(var.secret_env)))
  secret_id = google_secret_manager_secret.app[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}
resource "google_project_iam_member" "roles" {
  for_each = toset(["roles/cloudsql.client", "roles/aiplatform.user", "roles/documentai.apiUser"])
  project = var.project_id
  role = each.value
  member = "serviceAccount:${google_service_account.app.email}"
}
resource "google_project_iam_member" "cloud_build" {
  for_each = toset(["roles/artifactregistry.writer", "roles/run.admin"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}
resource "google_service_account_iam_member" "cloud_build_act_as_app" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}
resource "google_cloud_run_v2_service" "app" {
  name = var.service_name
  location = var.region
  deletion_protection = false
  ingress = "INGRESS_TRAFFIC_ALL"
  template {
    service_account = google_service_account.app.email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    scaling {
      # Guided paper generation continues after its HTTP response is returned.
      min_instance_count = 1
      max_instance_count = 10
    }
    containers {
      image = var.image
      resources {
        limits = { cpu = "2", memory = "2Gi" }
        cpu_idle = false
      }
      ports {
        container_port = 8080
      }
      dynamic "env" {
        for_each = {
          QB_DATA_DIR = "/mnt/qb-data"
          DATABASE_BACKEND = "postgresql"
          STORAGE_BACKEND = "gcs-volume"
          GCP_PROJECT_ID = var.project_id
          GCP_REGION = var.region
          GCS_DATA_BUCKET = google_storage_bucket.data.name
          GOOGLE_CLIENT_ID = var.google_client_id
          ADMIN_EMAILS = var.admin_emails
          DOCUMENTAI_PROCESSOR_ID = var.documentai_processor_id
          APP_BASE_URL = var.app_base_url
        }
        content {
          name = env.key
          value = env.value
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
            secret_key_ref {
              secret = google_secret_manager_secret.database_url.secret_id
              version = google_secret_manager_secret_version.database_url.version
          }
        }
      }
      dynamic "env" {
        for_each = nonsensitive(toset(keys(var.secret_env)))
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.key].secret_id
              version = google_secret_manager_secret_version.app[env.key].version
            }
          }
        }
      }
      volume_mounts {
        name = "cloudsql"
        mount_path = "/cloudsql"
      }
      volume_mounts {
        name = "qb-data"
        mount_path = "/mnt/qb-data"
      }
      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 10
        timeout_seconds = 5
        period_seconds = 10
        failure_threshold = 12
      }
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
    volumes {
      name = "qb-data"
      gcs {
        bucket = google_storage_bucket.data.name
        read_only = false
      }
    }
  }
  depends_on = [
    google_secret_manager_secret_iam_member.database,
    google_secret_manager_secret_iam_member.app,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_version.app,
    google_storage_bucket_iam_member.app,
  ]
}
resource "google_cloud_run_v2_service_iam_member" "public" {
  project = var.project_id
  location = var.region
  name = google_cloud_run_v2_service.app.name
  role = "roles/run.invoker"
  member = "allUsers"
}
