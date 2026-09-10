#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-gen-lang-client-0491787004}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-question-bank-cloud-v4}"
RELEASE_TAG="${RELEASE_TAG:-epidemiology-$(date +%Y%m%d%H%M%S)}"
REVISION_SUFFIX="${REVISION_SUFFIX:-epi-${RELEASE_TAG#*-}}"

gcloud config set project "$PROJECT_ID" >/dev/null
STAGE="$(RELEASE_TAG="$RELEASE_TAG" .venv/bin/python scripts/stage_engagement_release.py | tail -1)"
IMAGE="$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"][0])' "$STAGE/cloudbuild.json")"

echo "Submitting Cloud Build for $IMAGE"
BUILD_ID="$(gcloud builds submit "$STAGE" --config="$STAGE/cloudbuild.json" --project="$PROJECT_ID" --async --format='value(id)')"
echo "Build: $BUILD_ID"

while true; do
  STATUS="$(gcloud builds describe "$BUILD_ID" --project="$PROJECT_ID" --format='value(status)')"
  echo "Build status: $STATUS"
  case "$STATUS" in
    SUCCESS) break ;;
    FAILURE|CANCELLED|EXPIRED|TIMEOUT) echo "Build failed with status $STATUS" >&2; exit 1 ;;
  esac
  sleep 15
done

DIGEST="$(gcloud builds describe "$BUILD_ID" --project="$PROJECT_ID" --format='value(results.images[0].digest)')"
IMAGE_REF="${IMAGE%@*}@${DIGEST}"
echo "Deploying $IMAGE_REF"

gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE_REF" \
  --no-traffic \
  --revision-suffix="$REVISION_SUFFIX" \
  --update-env-vars="VERTEX_MODEL_PRIMARY=${VERTEX_MODEL_PRIMARY:-gemini-2.5-flash},VERTEX_MODEL_VERIFY=${VERTEX_MODEL_VERIFY:-gemini-2.5-flash},VERTEX_MODEL_TUTOR=${VERTEX_MODEL_TUTOR:-gemini-2.5-flash},AI_MAX_RETRIES=${AI_MAX_RETRIES:-1},AI_GENERATION_MAX_OUTPUT_TOKENS=${AI_GENERATION_MAX_OUTPUT_TOKENS:-12000},AI_GUIDANCE_MAX_OUTPUT_TOKENS=${AI_GUIDANCE_MAX_OUTPUT_TOKENS:-4096},BLUEPRINT_MAX_OUTPUT_TOKENS=${BLUEPRINT_MAX_OUTPUT_TOKENS:-5000},BLUEPRINT_MAX_RETRIES=${BLUEPRINT_MAX_RETRIES:-1},TUTOR_MAX_OUTPUT_TOKENS=${TUTOR_MAX_OUTPUT_TOKENS:-900},QB_GEMINI_MAX_OUTPUT_TOKENS=${QB_GEMINI_MAX_OUTPUT_TOKENS:-12000}" \
  --no-cpu-throttling \
  --min-instances="${MIN_INSTANCES:-0}" \
  --quiet

READY="$(gcloud run revisions describe "$SERVICE-$REVISION_SUFFIX" --project="$PROJECT_ID" --region="$REGION" --format='value(status.conditions[0].status)')"
if [ "$READY" != True ]; then
  echo 'New revision is not ready; production traffic was not changed.' >&2
  exit 1
fi

gcloud run services update-traffic "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --to-revisions="$SERVICE-$REVISION_SUFFIX=100" \
  --quiet

SERVICE_URL="${PUBLIC_URL:-https://meritiqra.com}"
curl --fail --silent --show-error --retry 3 --max-time 30 "${SERVICE_URL%/}/healthz"
echo
echo "Deployment complete: $SERVICE-$REVISION_SUFFIX"
