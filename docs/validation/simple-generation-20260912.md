# Simplified generation contract — 2026-09-12

Ordinary text generation now requests eight authored fields rather than the
persisted question model with nested visual primitives and application metadata.
Diagram fields remain available when the selected subject/topic/type or authoring
prompt explicitly calls for visual/non-verbal questions. A reference syllabus
mention alone does not force every batch into diagram mode. The application model,
stored question format, curriculum inputs, difficulty, review/save pipeline and
scheduled teaching explanations are unchanged.

Text options remain non-empty and distinct. Visual A-D choices are validated by
rendered primitives instead of captions; repeated/empty captions are permitted
only with complete distinct panels. Missing captions can name existing A-D
panels, never invent missing diagram content. Duplicate rendered panels and
unsupported primitives are rejected. Numeric option value zero is preserved.

Real Vertex Gemini 2.5 Flash probes in asia-south1 used synthetic scope, disposable
local prompt registry and no production application reads/writes:

- Three mental-ability/EVS text questions: 10.24 seconds, one provider response,
  four options and answer/solution for each; 1060 prompt / 746 output tokens.
- One non-verbal visual question: 10.13 seconds, one provider response, complete
  visual specification and four choices; 1524 prompt / 1222 output tokens.
- Both checks confirmed teaching explanation fields were deferred.

These are structural smoke checks, not official-syllabus certification, an
academic correctness audit, or a guarantee of production latency. They do not
identify the exact contents of the previously failed production question.
No deployment was performed for these changes.
