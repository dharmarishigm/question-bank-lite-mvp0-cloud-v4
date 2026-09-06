# Question Bank Cloud MVP-0 v4

A cloud-ready examination and question-digitization application. Production uses Cloud SQL for PostgreSQL, a private Cloud Storage bucket mounted into Cloud Run, Secret Manager, Vertex AI, and Document AI. SQLite and local files remain available for development.

See [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md) for provisioning, deployment, migration, validation, rollback, and operations.

The application also includes an authenticated examination layer. Administrators manage the Question Bank and create exams from existing questions. Students discover published exams, enroll, take independent timed attempts, autosave answers, and see only their own results.

## Google authentication

Create a Web OAuth client in Google Cloud Console and configure its authorized JavaScript origin as `http://127.0.0.1:8000` (and `http://localhost:8000` if you use that host). This app uses Google Identity Services ID tokens, verified by the FastAPI server; it does not request Gmail or mailbox permissions.

Add these values to `.env`:

```dotenv
GOOGLE_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
APP_BASE_URL=http://127.0.0.1:8000
ADMIN_EMAILS=admin@example.com
```

`GOOGLE_CLIENT_SECRET` is reserved for a future authorization-code flow and is not sent to the browser. Sessions are opaque random tokens stored in SQLite with HTTP-only, SameSite cookies. HTTPS deployments automatically use Secure cookies. Accounts matching `ADMIN_EMAILS` become administrators; all other newly authenticated accounts are students. Users cannot select or change their own role.

For automated tests or explicit local development, mock identity is enabled only when both settings are present:

```dotenv
APP_ENV=development
AUTH_MODE=mock
```

Do not use mock mode in a deployed environment.

## Examination flow

## Prompt-driven AI question generation

Administrators can open **Generate Questions by AI**, provide arbitrary examination metadata and syllabus context, and enter a required detailed generation prompt. The application sends that context to the configured Vertex AI Gemini model with a structured response schema, validates the result, rejects exact duplicates, and saves accepted questions into the canonical Question Bank with `REVIEW_REQUIRED` status.

Interactive requests support 1–50 questions. Generation requires Google Cloud credentials plus `GCP_PROJECT_ID`, `GCP_REGION`, and `VERTEX_MODEL_PRIMARY`. **Preview Effective Prompt** displays the public metadata, syllabus, administrator prompt, and output requirement without exposing credentials or the internal system instruction.

An administrator opens **Manage Exams**, creates an exam, supplies Question Bank IDs, and publishes it. A student signs in, opens **Available Exams**, enrolls, then starts or resumes the exam under **My Exams**. Answers save to the server on selection. The server owns the expiry time, submission locks the attempt, and **My Results** is always scoped to the signed-in student.

## What this MVP proves

Upload PDF, scanned PDF, PNG, JPG or WebP containing Math / Physics / Chemistry questions. The app attempts to extract every question and preserve:

- prose and answer options;
- mathematical equations as LaTeX;
- chemical formulae/reactions with mhchem-compatible LaTeX;
- tables as structured rows **plus the original table crop**;
- graphs, circuits, diagrams, geometry, shapes, organic structures and other visuals as **original source crops**, never redrawn;
- source page/region, model/run metadata, Math OCR evidence, verification issues and review status.

The safety rule is simple: **AI text is editable digital content; original source crops are ground truth.** If independent evidence is missing or systems disagree, the question is marked `REVIEW`/`FAILED` instead of silently trusted.

## Architecture

```text
Browser UI
   |
FastAPI (one local process)
   |
   +-- SQLite: questions + provenance + verification
   +-- ./data: original files + question/visual crops
   |
   +-- Vertex AI Gemini 3.5 Flash
   |      - transcription
   |      - question/source regions
   |      - table/graph/diagram detection
   |      - independent verification
   |
   +-- Document AI Enterprise OCR + Math OCR
          - OCR/layout evidence
          - LaTeX formula evidence + bounding boxes
```

Large PDFs are still processed in this one local process, but Gemini receives small overlapping page batches and Document AI receives <=15-page PDF chunks. This avoids one huge model response and protects questions that cross a batch boundary.

## Digital question representation

SQLite keeps the familiar `statement/options/answer/solution` fields for easy editing and also stores ordered `content_blocks` JSON. Example:

```json
[
  {"type":"text","content":"For the circuit shown..."},
  {"type":"math","content":"$R_1=4\\Omega$"},
  {"type":"diagram","asset":"/uploads/q12-diagram-....png","source_truth":true}
]
```

Visuals are stored in `visual_assets`; Document AI formula evidence is stored in `math_evidence`.

## Easiest run — macOS/Linux

Prerequisite: Python 3.11+.

```bash
./run_local.sh
```

The first run creates `.venv`, installs dependencies, copies `.env.example` to `.env`, creates the local data folders, and starts the server.

Open:

```text
http://127.0.0.1:8000
```

Without GCP configuration the UI and local PDF parser still run. AI-extracted questions remain unavailable/unverified until GCP is enabled.

## Easiest run — Windows

Double-click or run:

```bat
run_local.bat
```

Then open `http://127.0.0.1:8000`.

## Enable the GCP-native intelligence path

1. Create/select a GCP project with billing.
2. Enable Vertex AI and Document AI APIs.
3. Create an **Enterprise Document OCR** processor and note its processor ID and location.
4. Authenticate locally with Application Default Credentials:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

5. Edit `.env`:

```dotenv
GCP_PROJECT_ID=your-project-id
GCP_REGION=asia-south1
DOCUMENTAI_LOCATION=us
DOCUMENTAI_PROCESSOR_ID=your-processor-id
QB_PDF_LLM=vertex
QB_VERIFY=on
QB_OCR=auto
```

Check configuration:

```bash
.venv/bin/python check_setup.py
```

or open:

```text
http://127.0.0.1:8000/api/system/status
```

## Use

1. Click **Import source**.
2. Upload a PDF/scanned PDF/image.
3. The GCP path detects/transcribes the questions and creates source/visual crops.
4. Review the side-by-side source and digital content.
5. `VERIFIED` = no material mismatch detected; `REVIEW` = uncertainty or missing independent evidence; `FAILED` = critical mismatch/low confidence.
6. Edit where needed and click **Import selected**.
7. Questions are stored in `data/questions.db`; local images are stored below `data/uploads`; immutable originals are below `data/sources`.

## Why graphs/diagrams are images in MVP-0

The application intentionally does **not** regenerate a graph, circuit, geometry figure, organic structure or other shape. Recreating it can change scientific meaning. Gemini can classify/describe the visual and a table can also get structured cells, but the original crop remains part of the digital question.

## Tests

```bash
python -m unittest discover -s tests -v
node --check static/app.js
```

The automated suite is offline and makes no paid GCP calls. A live GCP golden-corpus benchmark is still required before claiming a particular accuracy level.

## MVP scope / non-goals

Not included: microservices, Cloud Run, Pub/Sub, Postgres, vector search, RAG, agents, authentication, graph-to-SVG conversion or online exam functionality. Those are intentionally excluded so engineering effort remains focused on **question digitization fidelity**.
