#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-gen-lang-client-0491787004}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-question-bank-cloud-v4}"
RELEASE_TAG="${RELEASE_TAG:-digitalqbank-$(date +%Y%m%d%H%M%S)}"
REVISION_SUFFIX="${REVISION_SUFFIX:-dqb-$(date +%Y%m%d%H%M%S)}"

gcloud config set project "$PROJECT_ID" >/dev/null
STAGE="$(RELEASE_TAG="$RELEASE_TAG" .venv/bin/python scripts/stage_engagement_release.py | tail -1)"
if ! grep -q 'translate_ddl(statement)' "$STAGE/migrations/versions/0019_digitalqbank_page_tracking.py"; then
  echo 'Staged migration 0019 is stale; refusing to deploy an incompatible PostgreSQL migration.' >&2
  exit 1
fi
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
IMAGE_REF="${IMAGE%:*}@${DIGEST}"
echo "Deploying $IMAGE_REF"

# A previous failed deployment can leave spec.traffic pointing at an unready
# revision even while status.traffic still serves the healthy one. Preserve
# the actual serving allocation before asking Cloud Run for another candidate.
SERVING_TRAFFIC="$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format='json(status.traffic)' | .venv/bin/python -c 'import json,sys; print(",".join(str(t["revisionName"])+"="+str(t["percent"]) for t in json.load(sys.stdin)["status"]["traffic"] if t.get("percent",0)>0))')"
if [ -z "$SERVING_TRAFFIC" ]; then
  echo 'No healthy serving allocation found; inspect the service before deploying.' >&2
  exit 1
fi
gcloud run services update-traffic "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --to-revisions="$SERVING_TRAFFIC" --quiet

gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE_REF" \
  --no-traffic \
  --revision-suffix="$REVISION_SUFFIX" \
  --tag=release-check \
  --quiet

READY="$(gcloud run revisions describe "$SERVICE-$REVISION_SUFFIX" --project="$PROJECT_ID" --region="$REGION" --format='value(status.conditions[0].status)')"
if [ "$READY" != True ]; then
  echo 'New revision is not ready; production traffic was not changed.' >&2
  exit 1
fi

CANDIDATE_URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format=json | .venv/bin/python -c 'import json,sys; print(next(t["url"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")=="release-check"))')"
curl --fail --silent --show-error --retry 3 --max-time 30 "${CANDIDATE_URL}/api/health"

gcloud run services update-traffic "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --to-revisions="$SERVICE-$REVISION_SUFFIX=100" \
  --quiet

SERVICE_URL="${PUBLIC_URL:-https://meritiqra.com}"
curl --fail --silent --show-error --retry 3 --max-time 30 "${SERVICE_URL%/}/api/health"
echo
echo "Deployment complete: $SERVICE-$REVISION_SUFFIX"
