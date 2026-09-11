# Separate Terraform root and state. Never apply the production infra state here.
terraform {
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
}
variable "project_id" { type = string }
variable "region" { type = string }
variable "staging_domain" { type = string }
provider "google" {
  project = var.project_id
  region  = var.region
}
resource "google_compute_region_network_endpoint_group" "staging" {
  name                  = "qb-security-staging-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  cloud_run { service = "qb-security-staging" }
}
resource "google_compute_security_policy" "staging" {
  name = "qb-security-staging-waf"
  rule {
    priority = 1000
    action   = "deny(403)"
    preview  = true
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable') || evaluatePreconfiguredWaf('xss-v33-stable')"
      }
    }
  }
  rule {
    priority = 2147483647
    action   = "allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
  }
}
resource "google_compute_backend_service" "staging" {
  name                  = "qb-security-staging-backend"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.staging.id
  backend { group = google_compute_region_network_endpoint_group.staging.id }
  log_config {
    enable      = true
    sample_rate = 1.0
  }
}
resource "google_compute_url_map" "staging" {
  name            = "qb-security-staging-map"
  default_service = google_compute_backend_service.staging.id
}
resource "google_compute_managed_ssl_certificate" "staging" {
  name = "qb-security-staging-tls"
  managed { domains = [var.staging_domain] }
}
resource "google_compute_target_https_proxy" "staging" {
  name             = "qb-security-staging-https"
  url_map          = google_compute_url_map.staging.id
  ssl_certificates = [google_compute_managed_ssl_certificate.staging.id]
}
resource "google_compute_global_forwarding_rule" "staging" {
  name                  = "qb-security-staging-443"
  target                = google_compute_target_https_proxy.staging.id
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
output "staging_ip" { value = google_compute_global_forwarding_rule.staging.ip_address }
