# Grand Tests

A separate authenticated workspace for Admins and Operators. Operators work on their own papers; Admins can see all work and assign the Operator role to existing users under Grand Tests → Manage Operator access.

Choose an existing active Program, upload a PDF, and digitize the whole paper or collect regions across pages. Questions remain workspace records until reviewed and finalized. Extraction uses the existing PDF/crop services, and classification uses the Program and curriculum masters as context. Low-confidence or failed classification requires manual correction. Mark every question reviewed before finalization.

Admin-only Generate Exam copies finalized records into the existing bank and exam tables in one transaction. Questions lock after generation. Draft exam name, start/end times, duration, and self-enrollment remain editable. Use existing Exam Admin for individual assignments and registration links. Publish snapshots the reviewed paper, creates an existing-format shared proctor code, and makes the scheduled exam available. Save the code displayed once; existing Exam Admin can rotate codes later. Server-side eligibility enforces enrollment, start/end time and code validation. Grand Test session expiry is capped at the exam deadline.

Digitization runs in the background. Reloading the workspace shows its saved progress and result. Failed operations can be retried; a job interrupted by instance termination can be retried after 30 minutes. Revision checks prevent overwriting concurrent work. Repeated regions and highly similar same-source questions are consolidated; review the consolidated output against the paper before finalization.

Deployment adds Alembic migration `0018_grand_tests` and no destructive schema changes. Application rollback uses the prior Cloud Run revision; keep the workspace table.

Validation:

- `python -m pytest tests -q`
- `python -m tests.validate_grand_tests_ui`

The browser test uses deterministic extraction fixtures. Production validation additionally exercises the configured GCP extraction service on a small validation paper.
