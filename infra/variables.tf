variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "service_name" {
  type    = string
  default = "question-bank-cloud-v4"
}
variable "app_base_url" {
  type        = string
  default     = ""
  description = "Public HTTPS origin used for secure authentication cookies"
}
variable "image" {
  type        = string
  description = "Artifact Registry image URL deployed to Cloud Run"
}
variable "google_client_id" {
  type      = string
  default   = ""
  sensitive = true
}
variable "admin_emails" {
  type    = string
  default = ""
}
variable "documentai_processor_id" {
  type      = string
  default   = ""
  sensitive = true
}
variable "database_tier" {
  type    = string
  default = "db-custom-1-3840"
}
variable "high_availability" {
  type        = bool
  default     = false
  description = "Enable regional HA for production exams"
}
variable "secret_env" {
  type        = map(string)
  default     = {}
  sensitive   = true
  description = "Additional Cloud Run environment variables stored in Secret Manager"
}
