#!/usr/bin/env bash
# This script intentionally has no production traffic promotion operation.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:-gen-lang-client-0491787004}"
REGION="${REGION:-asia-south1}"
SERVICE="${SECURITY_PREVIEW_SERVICE:?Set SECURITY_PREVIEW_SERVICE to a separately provisioned staging service with isolated database and storage}"
if [ "$SERVICE" = question-bank-cloud-v4 ]; then
  echo 'Refusing security preview deployment to the production service.' >&2; exit 1
fi
RELEASE_TAG="security-$(date +%Y%m%d%H%M%S)"
REVISION_SUFFIX="$RELEASE_TAG"
export PROJECT_ID REGION RELEASE_TAG
BEFORE="$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format=json)"
export PREVIEW_CONFIG="$BEFORE"
PRODUCTION_CONFIG="$(gcloud run services describe question-bank-cloud-v4 --project="$PROJECT_ID" --region="$REGION" --format=json)"
export PRODUCTION_CONFIG
.venv/bin/python - <<'PY'
import json,os
def config(name):
    spec=json.loads(os.environ[name])['spec']['template']['spec']
    return spec, {e['name']:e for e in spec['containers'][0]['env']}
stage,se=config('PREVIEW_CONFIG');prod,pe=config('PRODUCTION_CONFIG')
assert stage['serviceAccountName']!=prod['serviceAccountName'], 'Preview requires a separate runtime identity'
assert se['DATABASE_URL'].get('valueFrom') and pe['DATABASE_URL'].get('valueFrom'), 'Use reviewed, separate Secret Manager database references'
assert se['DATABASE_URL']['valueFrom']!=pe['DATABASE_URL']['valueFrom'], 'Preview cannot share the production database secret'
assert se['GCS_DATA_BUCKET'].get('value') and se['GCS_DATA_BUCKET']['value']!=pe['GCS_DATA_BUCKET']['value'], 'Preview cannot share the production data bucket'
assert os.environ.get('ISOLATED_DATABASE_VERIFIED')=='yes', 'Verify the staging secret targets a separate database; set ISOLATED_DATABASE_VERIFIED=yes only after checking'
PY
unset PREVIEW_CONFIG PRODUCTION_CONFIG
TRAFFIC_BEFORE="$(printf '%s' "$BEFORE" | .venv/bin/python -c 'import json,sys;print(json.dumps(sorted((t["revisionName"],t["percent"]) for t in json.load(sys.stdin)["status"]["traffic"] if t.get("percent",0))))')"
SERVING="$(printf '%s' "$BEFORE" | .venv/bin/python -c 'import json,sys;print(max(json.load(sys.stdin)["status"]["traffic"],key=lambda t:t.get("percent",0))["revisionName"])')"
BASE_IMAGE="$(gcloud run revisions describe "$SERVING" --project="$PROJECT_ID" --region="$REGION" --format='value(status.imageDigest)')"
export BASE_IMAGE
if [[ "$BASE_IMAGE" != *@sha256:* ]]; then echo 'Immutable production base image not found' >&2; exit 1; fi
STAGE="$(.venv/bin/python scripts/stage_engagement_release.py | tail -1)"
IMAGE="$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["images"][0])' "$STAGE/cloudbuild.json")"
BUILD="$(gcloud builds submit "$STAGE" --config="$STAGE/cloudbuild.json" --project="$PROJECT_ID" --async --format='value(id)')"
echo "Build: $BUILD"
while true; do
  STATUS="$(gcloud builds describe "$BUILD" --project="$PROJECT_ID" --format='value(status)')"
  echo "Build status: $STATUS"
  case "$STATUS" in
    SUCCESS) break ;;
    FAILURE|CANCELLED|EXPIRED|TIMEOUT) exit 1 ;;
  esac
  sleep 15
done
DIGEST="$(gcloud builds describe "$BUILD" --project="$PROJECT_ID" --format='value(results.images[0].digest)')"
gcloud run deploy "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --image="${IMAGE%:*}@${DIGEST}" --revision-suffix="$REVISION_SUFFIX" \
  --no-traffic --tag=security-preview --concurrency=40 \
  --update-env-vars=SECURITY_HARDENING=1 --quiet
AFTER="$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format=json)"
TRAFFIC_AFTER="$(printf '%s' "$AFTER" | .venv/bin/python -c 'import json,sys;print(json.dumps(sorted((t["revisionName"],t["percent"]) for t in json.load(sys.stdin)["status"]["traffic"] if t.get("percent",0))))')"
if [ "$TRAFFIC_BEFORE" != "$TRAFFIC_AFTER" ]; then
  echo 'Unexpected traffic allocation change: inspect the service immediately.' >&2; exit 1
fi
URL="$(printf '%s' "$AFTER" | .venv/bin/python -c 'import json,sys;print(next(t["url"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")=="security-preview"))')"
curl --fail --silent --show-error --max-time 30 "$URL/api/health"
for ROUTE in /api/questions /api/grand-tests /api/admin/users; do
  CODE="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 30 "$URL$ROUTE")"
  if [ "$CODE" != 401 ]; then echo "Unexpected anonymous response for $ROUTE: $CODE" >&2; exit 1; fi
done
echo
echo "Security preview: $URL/app"
echo "Revision: $SERVICE-$REVISION_SUFFIX"
echo "Production allocation unchanged: $TRAFFIC_AFTER"
