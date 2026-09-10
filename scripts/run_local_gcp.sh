#!/usr/bin/env bash
set -euo pipefail

project="${GCP_PROJECT_ID:-gen-lang-client-0491787004}"
region="${GCP_REGION:-asia-south1}"
bucket="${GCS_DATA_BUCKET:-gen-lang-client-0491787004-qb-v4-data}"
data_dir="${QB_DATA_DIR:-$PWD/data}"

echo "Starting MeritIQra at http://127.0.0.1:8000"
echo "GCP project: ${project}; region: ${region}; private bucket: ${bucket}"
echo "Database: local SQLite at ${data_dir}/questions.db"

GCP_PROJECT_ID="$project" \
GCP_REGION="$region" \
GCS_DATA_BUCKET="$bucket" \
STORAGE_BACKEND=gcs \
QB_PDF_LLM=vertex \
VERTEX_MODEL_PRIMARY="${VERTEX_MODEL_PRIMARY:-gemini-2.5-flash}" \
VERTEX_MODEL_VERIFY="${VERTEX_MODEL_VERIFY:-gemini-2.5-flash}" \
VERTEX_MODEL_TUTOR="${VERTEX_MODEL_TUTOR:-gemini-2.5-flash}" \
AI_MAX_RETRIES="${AI_MAX_RETRIES:-1}" \
AI_GENERATION_MAX_OUTPUT_TOKENS="${AI_GENERATION_MAX_OUTPUT_TOKENS:-12000}" \
QB_GEMINI_MAX_OUTPUT_TOKENS="${QB_GEMINI_MAX_OUTPUT_TOKENS:-12000}" \
APP_ENV=development \
AUTH_MODE=mock \
ADMIN_EMAILS="${ADMIN_EMAILS:-admin@meritiqra.com}" \
ADMIN_LOCAL_EMAIL="${ADMIN_LOCAL_EMAIL:-admin@meritiqra.com}" \
ADMIN_LOCAL_PASSWORD="${ADMIN_LOCAL_PASSWORD:-meritiqra-local-admin}" \
APP_BASE_URL=http://127.0.0.1:8000 \
QB_DATA_DIR="$data_dir" \
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
