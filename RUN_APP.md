# Run the app with GCP-native extraction

This project can run in two modes:

- Local-only mode: no GCP configuration required
- GCP-native mode: uses Vertex AI Gemini + Document AI OCR/Math OCR

For production use, run the app in GCP-native mode with the values already configured in the `.env` file.

## 1) Prerequisites

- Python 3.11+
- Google Cloud SDK (`gcloud`)
- A Google Cloud project with billing enabled
- Vertex AI API enabled
- Document AI API enabled

## 2) Open the project folder

```bash
cd "/Users/dharmaofficial/Library/CloudStorage/OneDrive-Personal/Career &Interview/CODE-NINJA/question-bank-lite-mvp0-v3"
```

## 3) Authenticate with Google Cloud

Run the following commands:

```bash
gcloud auth application-default login
gcloud config set project gen-lang-client-0491787004
gcloud services enable aiplatform.googleapis.com documentai.googleapis.com
```

If needed, verify your login:

```bash
gcloud auth list
gcloud projects describe gen-lang-client-0491787004
```

## 4) Confirm the environment variables

Your `.env` should contain values like:

```dotenv
GCP_PROJECT_ID=gen-lang-client-0491787004
GCP_REGION=asia-south1
VERTEX_MODEL_PRIMARY=gemini-3.5-flash
VERTEX_MODEL_VERIFY=gemini-3.5-flash
DOCUMENTAI_LOCATION=us
DOCUMENTAI_PROCESSOR_ID=348a15206a259771
QB_PDF_LLM=vertex
QB_VERIFY=on
QB_OCR=auto
```

## 5) Create or activate the local Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 6) Start the application

Start normally:

```bash
./run_local.sh
```

If port 8000 is already in use, use a different port:

```bash
PORT=8001 ./run_local.sh
```

Then open:

```text
http://127.0.0.1:8000
```

or, if you used the free-port override:

```text
http://127.0.0.1:8001
```

## 7) Verify the app is running

Open the app in the browser and upload a PDF or image.

You can also run the built-in verification checks:

```bash
python3 -m pytest -q tests/test_verification.py
```

Expected result:

```text
3 passed
```

## 8) Troubleshooting

### Port already in use

```bash
PORT=8001 ./run_local.sh
```

### GCP extraction falls back to local evidence

This means the app tried the Vertex/Document AI path and it failed, then showed local evidence instead.
Common fixes:

```bash
gcloud auth application-default login
gcloud config set project gen-lang-client-0491787004
gcloud services enable aiplatform.googleapis.com documentai.googleapis.com
```

Then check that your processor exists in the same region:

```bash
gcloud document-ai processors list --location=us
```

### Missing permission errors

Make sure the active Google account has access to the project and processor.

## 9) Notes

- The app starts in GCP-native mode when `.env` contains valid project and processor settings.
- If any GCP values are missing or invalid, the app will fall back to local parsing.
- The Document AI processor must be created in the same location configured in `.env`.
