#!/usr/bin/env bash
set -euo pipefail

# One-command deployment for MeritIQra Question Bank Cloud v4.
# Required tools: gcloud, terraform, and a logged-in Google account.

PROJECT_ID="${PROJECT_ID:-gen-lang-client-0491787004}"
REGION="${REGION:-asia-south1}"
SERVICE_NAME="${SERVICE_NAME:-question-bank-cloud-v4}"
REPOSITORY="${REPOSITORY:-question-bank}"
IMAGE_NAME="${IMAGE_NAME:-cloud-v4}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d%H%M%S)}"

command -v gcloud >/dev/null || { echo 'gcloud CLI is required.' >&2; exit 1; }
command -v terraform >/dev/null || { echo 'Terraform is required.' >&2; exit 1; }

if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  echo 'No active gcloud account found. Run: gcloud auth login' >&2
  exit 1
fi

read -r -p "Google OAuth client ID [${GOOGLE_CLIENT_ID:-optional}]: " INPUT_CLIENT_ID
GOOGLE_CLIENT_ID="${INPUT_CLIENT_ID:-${GOOGLE_CLIENT_ID:-}}"
read -r -p "Document AI processor ID [${DOCUMENTAI_PROCESSOR_ID:-optional}]: " INPUT_PROCESSOR_ID
DOCUMENTAI_PROCESSOR_ID="${INPUT_PROCESSOR_ID:-${DOCUMENTAI_PROCESSOR_ID:-}}"
read -r -p "Admin email [${ADMIN_EMAILS:-admin@example.com}]: " INPUT_ADMIN_EMAIL
ADMIN_EMAILS="${INPUT_ADMIN_EMAIL:-${ADMIN_EMAILS:-admin@example.com}}"
read -r -s -p "Local admin password [press Enter to disable local password login]: " INPUT_ADMIN_PASSWORD
echo
ADMIN_LOCAL_PASSWORD="${INPUT_ADMIN_PASSWORD:-${ADMIN_LOCAL_PASSWORD:-}}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"

gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com storage.googleapis.com aiplatform.googleapis.com documentai.googleapis.com

terraform -chdir=infra init
terraform -chdir=infra apply -auto-approve \
  -target=google_project_service.api \
  -target=google_artifact_registry_repository.app \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="service_name=${SERVICE_NAME}" \
  -var="image=${IMAGE}"

gcloud builds submit --tag "${IMAGE}"

# Terraform accepts a JSON object through TF_VAR_secret_env.
export TF_VAR_secret_env="$(printf '{\"ADMIN_LOCAL_EMAIL\":\"%s\",\"ADMIN_LOCAL_PASSWORD\":\"%s\"}' "${ADMIN_EMAILS}" "${ADMIN_LOCAL_PASSWORD}")"
terraform -chdir=infra apply -auto-approve \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="service_name=${SERVICE_NAME}" \
  -var="image=${IMAGE}" \
  -var="google_client_id=${GOOGLE_CLIENT_ID}" \
  -var="admin_emails=${ADMIN_EMAILS}" \
  -var="documentai_processor_id=${DOCUMENTAI_PROCESSOR_ID}" \
  -var='high_availability=true'

SERVICE_URL="$(terraform -chdir=infra output -raw service_url)"
echo "Cloud Run service: ${SERVICE_URL}"

# Set the canonical application origin after Terraform creates the service URL.
terraform -chdir=infra apply -auto-approve \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="service_name=${SERVICE_NAME}" \
  -var="image=${IMAGE}" \
  -var="app_base_url=${SERVICE_URL}" \
  -var="google_client_id=${GOOGLE_CLIENT_ID}" \
  -var="admin_emails=${ADMIN_EMAILS}" \
  -var="documentai_processor_id=${DOCUMENTAI_PROCESSOR_ID}" \
  -var='high_availability=true'

curl --fail --silent --show-error --retry 5 --max-time 30 "${SERVICE_URL%/}/healthz"
echo
echo "Deployment complete: ${SERVICE_URL}"
echo "Open ${SERVICE_URL}/app"
