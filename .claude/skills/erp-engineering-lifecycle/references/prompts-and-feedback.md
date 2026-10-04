# Compiled intelligence, provenance and feedback

## Active generation versus legacy helpers

The live application path is
[api/generation.py](../../../../backend/app/api/generation.py) →
[PromptCompiler](../../../../backend/app/services/prompt_compiler.py) → stored
`GenerationRun` → [worker](../../../../backend/app/cli/generation_worker.py) →
`process_generation_run` → [configured strategy](../../../../backend/app/services/codegen/strategies.py)
→ [configured provider](../../../../backend/app/services/llm/factory.py) → validation
and human review.

[services/ai/](../../../../backend/app/services/ai/) contains older context/FDD/TDD/
SQL/PLSQL/deployment prompt-building helpers. Those helpers are exported but are
not the current generation route's dispatch. Trace callers before extending
them; changes there can leave actual product behavior unchanged.

## Compiler contract

The compiler resolves the request's exact ERP profile version. It combines
applicable published GLOBAL/ERP/STAGE prompts, current requirement/schema,
approved upstream artifacts, relevant approved reviewer guidance and relevant
published knowledge/package context with the configured task. Missing usable
ERP configuration blocks generation; Oracle prompts are not a fallback.

`validate_prompt_template` checks declared/supported placeholders. The compiler
currently chooses latest applicable published prompts per scope/stage/name.
Global prompts are independently versioned; new runs may resolve new global
versions without changing the ERP profile pin.

Retrieval currently uses bounded in-memory lexical relevance, bounded excerpts
and a shared asset selection limit. It is not semantic/vector search, guaranteed
baseline-package selection or a complete source-span index. Read the current
limits in the compiler before changing retrieval. Preserve selected source IDs,
versions and checksums rather than treating truncated context as the full asset.

## Recorded evidence

Compiler provenance records profile, prompt, selected asset and feedback versions,
requirement/context versions, upstream version IDs and generation settings.
The queued run stores compiled prompts/content. `RecordedProvider` records the
effective requests, including provider adjustments, and only allowlisted receipt
metadata. These are controlled engineering records, not ordinary log payloads.

Auditable prior inputs/artifacts are reproducible records; rerunning an LLM is
not guaranteed to reproduce identical bytes. A profile pin alone also does not
freeze future global prompts/guidance or mutable external vendor state.

## Feedback boundaries

[Review routes](../../../../backend/app/api/reviews.py) create approved PROJECT
guidance from authorized request-changes comments. The compiler restricts project
guidance to the exact project/client, ERP guidance to its profile without client
ownership, and GLOBAL guidance to global scope; stage/relevance limits also apply.

[Feedback promotion](../../../../backend/app/api/feedback.py) requires an authorized
human publisher and project/client authority, checks the pinned ERP association,
and audits promotion. Do not mix clients' source comments into reusable guidance
or automatically promote them. Review/sanitize content before broader reuse.

Sandbox failures do not currently trigger automatic LLM repair, retesting or
verified lesson synthesis. Future learning notes need failed attempts, verified
fix/evidence, scope and human promotion controls; do not describe ordinary
review comments as that implemented learning loop.
