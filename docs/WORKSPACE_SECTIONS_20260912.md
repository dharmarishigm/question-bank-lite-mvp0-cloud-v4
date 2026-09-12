# Workspace sections and production schema repair

Deployed: `question-bank-cloud-v4-workspace-sections-20260912`, 100% production traffic; candidate and public health checks passed. Cloud Build `882731ec-c8b7-4940-9938-57e2931307bf` succeeded. Image digest: `sha256:f8cd0a5d30d77f731eca795129c95ab0eaa7772d7ebf6b81fe0b55cc555c7007`. Previous application revision `question-bank-cloud-v4-prompt-program-20260912c` remains available for rollback; retain the additive schema on rollback.

Production traces showed `UndefinedTable` for `prompt_definitions` in Prompt Registry and `program_enrollments` in My Exams. Available Exams requests My Exams as well, so this also blocked Admin exam participation. The previous application deployment omitted the feature schema expansion.

Database backup `1789193575203` succeeded before repair. Execution `qb-prod-exam-schema-fix3-20260912-k4857` succeeded, adding the prompt tables, seeded active prompts, program enrollments and runtime grants. The Alembic marker remains unchanged for compatibility with retained application revisions. The reproducible repair is in `scripts/repair_prompt_program_schema.py` and must use the privileged migration identity, never the runtime identity.

DigitalQBank catalog sections: Workspaces, Create workspace, PDF library, Operator access (where authorized). Workspace sections: Digitise, Review & save, Create exam / schedule (where available). Form nodes stay mounted, preserving unsaved edits. Review questions have a bounded scroll area. Programs exposes its existing dedicated sections, including Create exam and setup, directly; the catalog is hidden while a program is open and restored on close.

Server and connection errors now identify the affected feature and recovery action. Available Exams recognizes program-derived enrollment. Startup checks require all new feature tables before a candidate can pass health checks.

Validation: JavaScript syntax and Python compilation passed; prompt registry tests (2) and exam heartbeat test passed. Headless Chromium checked mobile width, keyboard operation and preservation of unsaved input. The broader existing UI suite failed on its upload-path assertion (`/uploads/../.env`); this change does not modify that helper. Authenticated production Admin/student end-to-end testing has not been performed.
