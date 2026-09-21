# Infraestructura como código del disparador del pipeline de Churn (clase 8 bonus).
#
# En vez de crear el topic y el job de Cloud Scheduler a mano en la consola (clickeando), los
# declaramos acá. `terraform apply` los crea; `terraform destroy` los borra. La infra queda
# versionada en git, igual que el código: revisable, reproducible y borrable de un comando.
#
# Uso:
#   terraform init
#   terraform validate
#   terraform apply  -var project=mlops-itba-2026
#   terraform destroy -var project=mlops-itba-2026

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

variable "project" {
  type        = string
  description = "Project ID de GCP."
}

variable "region" {
  type        = string
  description = "Región de los recursos."
  default     = "us-central1"
}

variable "schedule" {
  type        = string
  description = "Cron del reentrenamiento programado (default: lunes 03:00)."
  default     = "0 3 * * 1"
}

# El topic al que el disparador publica. Una Cloud Function suscripta a este topic llama a
# PipelineJob.submit() (ver pipeline/trigger/README.md). El disparo por drift publica al mismo
# topic desde pipeline/trigger/drift_gate.py.
resource "google_pubsub_topic" "retrain" {
  name = "churn-retrain"
}

# Disparo por tiempo: Cloud Scheduler publica al topic según el cron. Este es el "quién dispara
# el pipeline" cuando la respuesta es "el reloj".
resource "google_cloud_scheduler_job" "weekly_retrain" {
  name      = "churn-retrain-weekly"
  schedule  = var.schedule
  time_zone = "America/Argentina/Buenos_Aires"

  pubsub_target {
    topic_name = google_pubsub_topic.retrain.id
    data       = base64encode("scheduled-retrain")
  }
}

output "topic" {
  value       = google_pubsub_topic.retrain.id
  description = "Topic de Pub/Sub que dispara el reentrenamiento."
}

output "scheduler_job" {
  value       = google_cloud_scheduler_job.weekly_retrain.name
  description = "Job de Cloud Scheduler que publica según el cron."
}
