# UI and competitive-exam participation review

The Programs list and overview render Markdown descriptions with readable headings, lists and tables. Shared admin/student styles standardize focus indicators, headings, mobile controls, wrapping, table scrolling and empty states. Navigation identifies the active page, supports keyboard focus and closes the mobile sidebar with Escape. AI workspace tabs support arrow-key navigation. Loading failures expose a retry action. Student profile loading and saving are connected to the profile API.

Available Exams now reflects enrollment and attempt state. Enrollment opens the start/proctor dialog on that page when eligible. Existing students can start, resume, view results or retake there. Server eligibility, attempt limits and proctor validation remain authoritative.

## Real competitive-exam participation

`static/program-participation.json` contains reviewed 2024–2026 external examination figures and per-year source links. The corresponding browser module displays approximate counts in Programs, linked exam cards, the start dialog and public Explore Exams. Program association comes from persisted program-paper records, never title matching.

JEE Main counts unique appeared candidates across sessions; JEE Advanced counts candidates appearing in both papers; NEET and TG EAPCET count appeared candidates. Navodaya counts registrations. Source notes distinguish official publications, news coverage, mirrored NVS plans and the 2026 draft plan. SOF Class 8/9 subject-specific annual figures remain unavailable because verified counts were not found; aggregate Olympiad totals are not substituted. Other programs show unavailable figures until sourced data is added. These figures are not platform enrollments. Data needs periodic editorial refresh; pages do not make LLM calls.

## Validation

Backend tests cover program associations in public, available, enrolled and detail APIs and ensure similarly named unrelated exams do not inherit statistics. The navigation browser audit checks nine admin and six student views at desktop, tablet and mobile widths, plus eleven program sections at desktop and mobile widths (67 combinations). It also exercises Markdown structure, keyboard tabs, profile persistence, error recovery and mobile navigation. A separate synthetic browser test exercises enrollment, incorrect proctor rejection and successful start directly from Available Exams at desktop and mobile widths. This is targeted UI validation, not a complete accessibility certification.
