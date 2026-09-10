# Competitive program presets

Added on 10 September 2026 through the existing admin program and saved-setup APIs.
The reviewed, editable presets live in `program_presets/`. The AI authoring
suggestions were generated with the application's existing Vertex model, reviewed,
and saved as Markdown. Adding a preset creates no questions or published exams.

| Program | Full practice questions | Raw marks | Minutes | Scope |
| --- | ---: | ---: | ---: | --- |
| SSC CGL Tier I | 100 | 200 | 60 | Four subjects, 2026 reference |
| SSC CGL Tier II Paper I | 150 | 450 | 135 | Five objective subjects, 2026 reference |
| GATE CS & IT | 65 | 100 | 180 | Aptitude, Mathematics and nine CS areas, 2027 reference |
| CAT | 68 | 204 | 120 | VARC, DILR, QA; editable practice allocation |
| IELTS Academic | 100 | 100 | 165 | Four skills, MCQ practice adaptation |
| IELTS General Training | 100 | 100 | 165 | Four skills, MCQ practice adaptation |

Open **Programs → Create exam**. The full setup loads automatically. Choose
**Subject-wise**, select a subject, and adjust counts, duration, marks, curriculum
and difficulty. The final Markdown prompt incorporates those inputs. All five
difficulties and the existing approved-question reuse / missing-question generation
workflow remain available. Switching back to Full Exam restores the full duration,
including an admin's edited duration.

## Reference limitations shown in the app

- SSC Tier II includes Computer Knowledge's 60 qualifying marks in the 450 raw
  practice total. Official merit-bearing sections total 390. DEST typing and
  post-specific Papers II/III are excluded.
- SSC/CAT section timings are authoring guidance; delivery uses an overall timer.
- GATE is the **CS paper**, not all branches. It preserves the 15/13/72 marks split
  with editable chapter allocations and mark bands. MSQ and numerical answers
  are adapted to single-correct MCQs. Chapter weights are not official predictions.
- CAT's readable official 2025 release establishes three sections and timing.
  The preset does not claim verified 2026 counts. Its 24/22/22 counts and MCQ-only
  scoring are practice settings. No scaled score or percentile is inferred.
- IELTS uses written listening transcripts and writing/speaking skills MCQs.
  It does not administer audio listening, essays or oral responses, and produces
  no IELTS band. The 10 writing and 10 speaking questions are practice allocations.
- Source URLs, reference cycle and verification date are included in each program
  description and pattern. Refresh sources before adopting a later cycle.

## Repeatable installation

From the repository root, use the existing virtual environment:

```sh
.venv/bin/python scripts/seed_competitive_programs.py
.venv/bin/python scripts/seed_competitive_programs.py --apply
```

The first command validates the local catalog. The second uses the established
GCP service's administrator configuration in memory to create missing programs
and setups. It refuses to overwrite edited setups or restore archived programs.
An interrupted run can be repeated: exact existing setups are verified and reused.
It verifies saved settings and full/subject prompt totals, then writes a receipt
under `docs/validation/competitive-programs-deployment.json`. It never invokes
question generation or exam publication.

Preset JSON is the durable source for initial installation. Subsequent edits in
the Programs UI remain authoritative for that live program; do not rerun the seed
as a way to overwrite an administrator's changes.
