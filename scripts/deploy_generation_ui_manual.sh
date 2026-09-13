#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root after reviewing `git diff`.
# This script deploys the current working tree; it does not commit changes.
# It intentionally delegates to deploy_gcp.sh instead of building the raw
# development Dockerfile: production uses a schema-managed startup image and
# must never run Alembic migrations during a Cloud Run startup probe.
PROJECT_ID="${PROJECT_ID:-gen-lang-client-0491787004}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-question-bank-cloud-v4}"
REPOSITORY="${REPOSITORY:-question-bank}"
TAG="${TAG:-generation-ui-$(date +%Y%m%d%H%M%S)}"
REVISION_SUFFIX="${REVISION_SUFFIX:-gen-ui-$(date +%Y%m%d%H%M%S)}"
PROMOTE="${PROMOTE:-1}"

command -v gcloud >/dev/null || { echo 'gcloud CLI is required.' >&2; exit 1; }
command -v curl >/dev/null || { echo 'curl is required.' >&2; exit 1; }
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo "Service: ${SERVICE}"
echo
echo 'Reviewing working-tree changes:'
git diff --check
git status --short
echo

export PROJECT_ID REGION SERVICE
export RELEASE_TAG="${TAG}"
export REVISION_SUFFIX
export PROMOTE_TRAFFIC="${PROMOTE}"
exec bash scripts/deploy_gcp.sh
