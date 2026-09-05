# MVP-0 v3 implementation notes

## Purpose

Keep the application lightweight and local while proving high-fidelity digitization. SQLite and local files are deliberate choices. GCP is used only for multimodal transcription, independent verification, and Math OCR evidence.

## Fidelity decisions

1. Original uploaded files are copied into `data/sources` and fingerprinted with SHA-256.
2. Every question keeps one or more high-resolution source segments.
3. Gemini can identify tables/graphs/diagrams/shapes/images using normalized page boxes. The app crops and stores those regions; if a box is uncertain it falls back to the whole question crop rather than fabricating a visual.
4. Mixed question text is stored both as editable `statement` text and as `content_blocks` separating text/math/chemistry spans.
5. Tables may have structured headers/rows, but the original table crop remains authoritative.
6. Graphs/diagrams/shapes/organic structures are never regenerated in MVP-0.
7. Mathematical/chemical notation with no Document AI Math OCR evidence is forced to `REVIEW` rather than silently auto-verifying.
8. Large PDFs are processed in overlapping Gemini page batches and <=15-page Document AI chunks.

## SQLite additions

The `questions` table now includes JSON columns:

- `content_blocks`
- `visual_assets`
- `math_evidence`

The migration is additive and existing v2 databases remain readable.

## Validation performed

- Python compile checks.
- Offline unit suite.
- JavaScript syntax check.
- Local FastAPI smoke test with a fresh temporary SQLite database and GCP disabled.

Live Vertex AI / Document AI calls require the user's own GCP project/ADC and are not executed by the offline test suite.
