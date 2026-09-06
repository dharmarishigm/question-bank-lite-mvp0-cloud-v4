# Cloud MVP-0 v4 deployment

## Architecture

- Cloud Run runs FastAPI as a generation 2 service.
- Cloud SQL for PostgreSQL stores questions, versions, exams, registrations, attempts, answers, results, sessions, and audit records.
- One private, versioned Cloud Storage bucket stores uploaded sources and derived images. Cloud Run mounts it at `/mnt/qb-data`; existing file paths continue to work while the bucket remains private. Requests to `/uploads/*` require an application session when authentication is configured.
- Secret Manager supplies `DATABASE_URL` to Cloud Run.
- A dedicated service account has Cloud SQL Client, Storage Object User, Secret Manager Secret Accessor, Vertex AI User, and Document AI API User roles.
- Alembic owns the PostgreSQL schema. SQLite initialization remains available for local development.

## Prerequisites

Install `gcloud` and Terraform 1.7+, authenticate with Application Default Credentials, and select a billing-enabled project. Never commit `.env`, Terraform state, database exports, PDFs, or credentials.

```bash
gcloud auth application-default login
gcloud config set project gen-lang-client-0491787004
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

Edit `infra/terraform.tfvars`. Put sensitive application values in `secret_env`; Terraform creates a Secret Manager secret for each entry and exposes it only to the Cloud Run service account. For production, set `high_availability=true`. Protect Terraform state because it contains secret values.

## Provision and deploy

Artifact Registry must exist before the first application image is built. Terraform creates it, so bootstrap that resource first:

```bash
terraform -chdir=infra init
terraform -chdir=infra apply -target=google_project_service.api -target=google_artifact_registry_repository.app
gcloud builds submit --tag asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4:initial
terraform -chdir=infra apply \
  -var='project_id=gen-lang-client-0491787004' \
  -var='image=asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4:initial'
```

The container runs `alembic upgrade head` before starting FastAPI. Later revisions can be built and deployed with `gcloud builds submit --config cloudbuild.yaml`.

Set the production OAuth origin to the `service_url` Terraform output. Verify `/api/system/status`, administrator login, student login, and a complete exam flow before directing users to the service.

## Migrate SQLite and local files

Put the old application in maintenance mode and copy `data/questions.db` and the full `data` directory. Connect with the Cloud SQL Auth Proxy, run the schema migration, then use the restartable importer:

```bash
export DATABASE_URL='postgresql+psycopg://question_bank_app:PASSWORD@127.0.0.1:5432/question_bank'
export GCS_DATA_BUCKET='gen-lang-client-0491787004-qb-v4-data'
alembic upgrade head
python scripts/migrate_sqlite_to_cloud.py --sqlite /path/to/data/questions.db --data-dir /path/to/data
```

The importer preserves IDs, uses conflict-safe inserts, advances PostgreSQL sequences, and uploads objects under the same relative keys used by the Cloud Storage mount. Re-running it skips existing rows and objects.

Validate table counts, foreign keys, exam snapshots, registrations, attempt answers, scores, and representative PDF and crop images. Keep the source SQLite database and files read-only until acceptance is complete.

## Local development

Without `DATABASE_URL`, the application uses SQLite and `QB_DATA_DIR` as v3 did. To exercise PostgreSQL locally, set `DATABASE_URL`, run `alembic upgrade head`, and start the application:

```bash
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -r requirements.txt
DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost/question_bank' .venv/bin/alembic upgrade head
.venv/bin/uvicorn app:app --reload
```

## Operations and recovery

Cloud SQL automated backups and seven days of point-in-time recovery are enabled. The instance has deletion protection. The bucket has public access prevention, uniform access control, object versioning, and cleanup of older noncurrent versions. Configure alerts for Cloud Run 5xx responses, latency, Cloud SQL CPU/storage/connections, and failed backups.

For rollback, route traffic to the previous healthy Cloud Run revision. Restore Cloud SQL to a new instance for data recovery, validate it, update the database secret, and deploy a new revision.
