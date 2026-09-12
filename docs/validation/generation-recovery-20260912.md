# Generation recovery release — 2026-09-12

Application commit: `efc39a8` (develop).
Cloud Build: `90691af6-bfa6-408c-8047-745a3db66bec`.
Image: `sha256:357eaf138e335298cabd4ad0fd6397c9224d9c69fc72f693c54ae10af6520ca2`.
Production revision: `question-bank-cloud-v4-generation-efc39a8`, 100% traffic.
Previous revision: `question-bank-cloud-v4-current-question-93854ad`.

Includes syllabus/LaTeX prompt rules, deferred teaching-explanation guidance,
schema-complexity JSON fallback, validation feedback in retries, cooperative
pause, incomplete-run continuation, interrupted-run recovery and soft deletion
of saved generation runs. Existing bank questions and papers are not deleted.
Continuation creates a new batch and preserves the original for review.

Validation: 192 local regression tests passed; JavaScript syntax and diff checks
passed. Cloud Build's isolated PostgreSQL release gate passed. Candidate health
and served recovery controls were verified before promotion. Candidate error
logs were empty. After promotion, public https://meritiqra.com/api/health returned
`status: ok` and the exact new revision.

No production generation was started or existing run changed for this release.
Authenticated live Gemini generation remains unverified; tests simulate provider
errors. Prior production rejection reasons cannot be recovered from the generic
error alone. Worker job and scheduler configuration were not changed.
