# Role UI and generation-save repair

The production generation flow called `init_prompt_registry` after the model returned, causing table-creation permission errors before results were saved. Removed this request-time call. Managed runtime prompt reads now fail clearly without attempting schema initialization. Added regression tests for read-only resolution, missing managed schema and generation saving without initialization. Local bootstrap creates program enrollments only after the Programs schema exists.

## Page coverage

This is a source/layout review and shared presentation pass, not an assertion that every production account workflow has been exercised.

| Pages | Applicable improvements |
| --- | --- |
| Admin and Student dashboards | Shared heading spacing, keyboard focus and page finder |
| Question Bank, AI generation, Upload & Digitise, review pages | Content navigation color, consistent actions, bounded tables; existing review/save behavior retained |
| Programs and exam creation | Colored dedicated tabs, primary-action hierarchy; existing generation steps retained |
| DigitalQBank (Admin/Operator) | Colored workspace tabs, mobile targets, existing retained-form tab behavior |
| Prompt Registry | Dedicated Active prompt, Edit draft, Version history, Usage sections; bounded readable content |
| Exam Admin and registrations | Clear primary/destructive action colors, sticky table headers |
| Available Exams and My Exams (Admin/Student) | Green start/resume actions, blue navigation grouping |
| My Results, Admin Results, Performance Lab | Purple result actions/navigation, bounded tables |
| Student profile | Shared field spacing, visible focus and mobile font sizing |
| FLAG learning/resources/access, enquiries | Shared actions and table presentation; entitlement logic unchanged |
| Active exam | New shared overrides and page finder disabled during exam focus; timer and conduct controls unchanged |

The finder derives its options from existing role-visible navigation, deduplicates links, rechecks visibility when selected, and handles keyboard input. Labels and active borders communicate meaning in addition to color. It does not change API permissions.

## Validation

- 26 targeted tests passed: prompt registry, AI batch review, program exam generation/review/reuse.
- JavaScript syntax, Python compilation and diff whitespace checks passed.
- Real shell/styles with role fixtures tested in Chromium at 1440px and 390px for Admin, Student and Operator. Checked hidden role links, keyboard search, no-match feedback and exam-focus exclusion.
- Reviewed desktop and mobile screenshots. These use fixtures, not authenticated production student data.
- Prior broad UI test suite has an unrelated upload-path assertion failure; no blanket claim of a clean full suite.

No production database migration is required by this release. The previous revision is `question-bank-cloud-v4-workspace-sections-20260912`; retain it and the existing additive schema for rollback.
