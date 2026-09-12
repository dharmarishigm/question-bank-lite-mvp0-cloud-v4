# AI runtime audit — 12 September 2026

## Scope and evidence

The reported production failure was confirmed in Cloud Run logs at
`2026-09-12T09:33:58Z`, revision
`question-bank-cloud-v4-correction-latex-45f9145`: generation raised an
unterminated-JSON-string error at character 984. Those logs do not contain the
provider finish reason or token counts, so they do not establish whether the
original response was token-limited, otherwise truncated, or malformed.

Production HTTP admin tests were blocked by `MFA_REQUIRED`. MFA was not disabled
or bypassed. Provider checks below used the production Vertex project, region,
and model settings with synthetic inputs and isolated local databases. They are
not authenticated end-to-end production tests.

## Changes

- Decode SDK-parsed responses or complete non-thought candidate JSON. Never
  concatenate alternative candidates or manufacture missing JSON content.
- Log finish reasons, token counts, error types, and validation field locations,
  without logging prompts, answers, credentials, or model thoughts.
- Bound provider retries, thinking, output budgets, and generation wall time.
  Split malformed multi-question batches immediately; retry only missing work.
- Require worked solutions and English/Telugu explanations in the active runtime
  generation contract, including databases with older administrator prompts.
- Preserve validated partial work as reviewable drafts. Aggregate parallel batch
  usage and limit interactive authoring to one wave of four workers.
- Checkpoint guided papers after three questions by default. Additional
  administrator conditions now participate in the question-bank reuse hash.
- Apply the LaTeX requirement to the effective correction, authoring, independent
  solving, and explanation system prompts without overwriting admin versions.
- Keep correction input strict. Normalize only known provider response shapes,
  preserve labelled option order, and reject ambiguous answer mappings.
- Cache legacy explanation misses automatically; reject stale results if a
  question changes during generation. Invalidate old bilingual explanations in
  corrected drafts, metadata, and saved generation previews.
- Enforce released-result and active-exam controls for student explanations.
  Tutor receives actual option text and validates its structured response.
- Enforce assumption validation for epidemiology suggestions without supplied
  evidence; AI output cannot claim that those inputs are reference-validated.

## Validation coverage

| Use case | Regression coverage | Real provider check |
|---|---|---|
| Question generation and prompt guidance | JSON recovery, retry limits, deadlines, partial batches, bilingual schema | Passed: generation 8.49s; guidance 8.63s |
| Guided full/subject papers | Checkpoints/resume, review, publication, reuse, additional conditions | Shared generation provider tested; live admin workflow pending MFA |
| Correction and regeneration | Input validation, safe normalization, review-before-save, lineage | Passed: 4.66s and 4.56s |
| English/Telugu explanations | Generation cache, legacy cache miss, correction invalidation, access gates | Telugu structured explanation 10.85s; repeat used cache |
| Tutor | Context, schema, access controls, safe fallback | Passed: 3.33s |
| Image digitization/verification | SDK response variants, strict schema, retries, deadlines | Synthetic image extraction passed: 14.96s |
| Program setup | Proposal validation and lifecycle | Passed: 9.64s, first attempt |
| Official exam source lookup | Grounded evidence filtering and application rules | Not validated: probe ended without a persisted result |
| Blueprint refinement, authoring, independent solving | Structured calls, patch policy, workflow integration | Shared provider wrapper tested; purpose-specific live checks not completed |
| Grand-test classification | Classification and lifecycle tests | Not individually live-tested |
| FLAG explanations | Cache, quota, access and workflow tests | Not individually live-tested |
| Epidemiology suggestions | Permissions, mandatory assumptions, provider failure | Not individually live-tested |

Browser acceptance uses mocked AI with real local API/storage: desktop/mobile
correction and regeneration, rendered LaTeX, proposal-not-saved controls, student
controls absent; guided full/subject generation, five difficulties, review and
publish, mobile layout, archive/restore. Both scripts passed without page errors.
The guided browser fixture was updated to close the detail panel before using
list controls. Several existing API fixtures were updated for the existing
scheduled-start and consent requirements; those product requirements were not
relaxed.

## Runtime controls

| Setting | Effective default/limit |
|---|---|
| `AI_MAX_RETRIES` | 1 retry; at most 2 configurable retries |
| `AI_GENERATION_BATCH_SIZE` | 3, maximum 5 per provider batch |
| `AI_GENERATION_COMPLEX_BATCH_SIZE` | 1 for hard/very-hard questions, configurable up to 3 |
| `AI_GENERATION_MAX_OUTPUT_TOKENS` | 12,000 configuration default; enforced floor 6,000 and cap 24,000 |
| `AI_GENERATION_TOTAL_TIMEOUT_SECONDS` | 150; bounded to 30–180 seconds per worker |
| `AI_GENERATION_TIMEOUT_SECONDS` | 90; each call is additionally limited by remaining total time |
| `PROGRAM_EXAM_BATCH_SIZE` | 3, configurable up to 20 |
| `BLUEPRINT_MAX_RETRIES` | 1 retry, maximum 2 attempts; correction owns its route-level recovery instead |
| `BLUEPRINT_QUESTION_CORRECTION_MAX_OUTPUT_TOKENS` | Purpose default 6,000 |
| `BLUEPRINT_QUESTION_EXPLANATION_MAX_OUTPUT_TOKENS` | Purpose default 8,000 |
| `BLUEPRINT_PROGRAM_SETUP_MAX_OUTPUT_TOKENS` | Purpose default 12,000 |

The model may still be unavailable or return invalid content. These changes
bound recovery, retain validated work, and provide diagnostic evidence; they do
not promise zero provider errors or a fixed latency for every question.

## Reproduction and release

- `scripts/validate_generation_provider.py`: isolated real generation/guidance;
  `--scenario jee-chemistry` exercises a three-question very-hard chemistry batch.
- `scripts/validate_aux_ai_live.py`: opt-in extraction/setup/official checks.
- `scripts/validate_ai_production.py`: authenticated production or candidate HTTP
  checks; records MFA blocks as blocked rather than passing.
- `tests/validate_question_correction_ui.py` and
  `tests/validate_program_exam_ui.py`: isolated browser acceptance.
- `scripts/deploy_gcp.sh` supports `PROMOTE_TRAFFIC=0` to build a candidate without
  shifting production traffic. The image build checks actual installed SDK
  support for retry, thinking, and per-call timeout settings, plus migrations on
  disposable PostgreSQL.

No exam was published and no production question content was changed by these
validation probes. Existing failed paper checkpoints are not automatically
regenerated or published during deployment.
