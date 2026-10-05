# Defect-to-test register

Updated: 2 October 2026  
Owners: Platform, workflow, frontend and adapter engineering  
Source: [application audit](application-audit-2026-10-01.md)

Tests close defects only after their implementation and relevant checks pass. PostgreSQL/vendor
qualification needs the real runtime. Fixture browser tests do not certify client ERP installation.

| ID | Failure/invariant | Phase | Evidence/required regression | Status |
|---|---|---|---|---|
| D01 | Unauthenticated data/reviews and shared admin identity | 1 | Identity/client role/isolation matrix | Local API/browser coverage; PostgreSQL certification pending |
| D02 | Duplicate generation; changed upstream dependencies | 2 | Two-session revision and late-completion tests | Local regressions pass; PostgreSQL concurrency pending |
| D03 | Concurrent stale review overwrites approval | 2 | Atomic review conflict test | Local regressions pass; PostgreSQL concurrency pending |
| D04 | Unsafe SQL/PLSQL receives misleading PASS | 7 | All modes, signatures/helpers, prohibited operations, compilation | Open |
| D05 | Startup/read operations create/re-publish fixtures | 0 | Startup/readiness and seed/pure-read suites | Fixed; local regressions pass |
| D06 | Published profile lacks usable prompts/adapters | 3 | Publication readiness/capability checks | Open |
| D07 | PKB viewer shows spec; stale frontend review target | 2/6 | Exact target switching/file viewer browser tests | Open |
| D08 | Sample Oracle supplier relationship incorrect | 4/7 | Source fidelity and verified schema fixture | Open |
| D09 | Compiler snapshot differs from actual provider request | 5 | Effective request/provenance equality | Recorded requests/filtered receipts covered; live Groq FDD verified |
| D10 | Provider failures lack durable generation evidence | 5 | Failure persistence and retry suite | Durable job/failure/recovery regressions pass |
| D11 | Cloned asset version lookup ambiguous | 3 | Exact resource identity resolution | Open |
| D12 | Retrieval mixes revisions/excludes packages | 4/5 | Scoped relevant exact-version sources | Exact-version/scoped relevance covered; lexical retrieval and UI-only qualification remain |
| D13 | Documents stored without extraction/indexing | 4 | Format/OCR/source ingestion tests | Bounded text/PDF/DOCX extraction covered; OCR not implemented |
| D14 | Prompt uniqueness/lifecycle inconsistencies | 3 | Stage/scope/version/publication tests | Open |
| D15 | Downloads omit required files | 8 | Server manifest/checksum completeness | Complete bundle/exact-file/historical download regressions pass; native ERP qualification pending |
| D16 | Historical approval appears active after invalidation | 2 | Active/historical read regression | Local regressions pass; history stays read only |
| D17 | Google Docs templates absent; exports omit content | 6 | Template-copy and complete document exports | Open |
| D18 | ERP publication requires reload to select | 3 | Same-session onboarding browser test | Open |
| D19 | Failed review clears comments; errors/duplicates unclear | 2 | Draft preservation and stale-submission test | Draft preservation/duplicate guards covered; in-app confirmation added |
| D20 | Admin editing needs internal JSON | 3 | Typed editor/readiness browser tests | Open |
| D21 | Missing keys silently mock; health ignores dependencies | 0 | Production configuration/startup/readiness suites | Production/configuration/startup regressions pass; deployed dependency qualification pending |
| D22 | Demo ERP lacks UI-only tested-download acceptance | 3–8 | Full authenticated browser acceptance | Open |
| D23 | Inputs/configuration cannot be explicitly revised | 2/4 | Revision/backtracking and historical preservation | Requirement/context revision/invalidation/history covered; explicit profile upgrade qualification pending |
| D24 | Legacy/fresh prompt-stage bindings differ | 3 | PostgreSQL configuration equivalence | Open |
| D25 | Long JSON hides navigation | 0 | Vitest + desktop/compact Playwright shell tests | Fixed; desktop/compact browser checks pass |
| D26 | No repeatable test pipeline/dependency lock | 0 | Locked CI, unit/browser/migration commands | Implemented; CI execution pending |
| D27 | Type/lint debt and legacy JSX typing | All | Explicit diagnostic ledgers and feature conversion | Open, ratcheted |
| D28 | Runtime telemetry/destination policy unverified | 0/11 | Redaction now; egress/provider inventory later | Partially covered |
| D29 | Unresolved legacy assessment fields still permit approval | 2 | Shared blockers, API response and UI disabled-approval checks | Fixed; local regressions pass |
| D30 | Interrupted old worker can release a replacement gate | 2 | Exact revision/binding checks in recovery | Fixed; worker recovery regressions pass |

Initial debt: 593 Ruff findings and 77 mypy findings with untyped bodies checked; frontend nine
warnings plus legacy JSX typing and a bundle-size warning. New core/provider boundaries accept
no legacy debt. A passing ratchet means no new exact diagnostic debt; it does not mean all code
is clean. Prune resolved ledger entries after fixes. Adding accepted debt requires a reviewed
defect, owner and rationale. Module-wide lint/type suppression cannot replace planned corrections.

Current local evidence: 265 backend tests, 53 frontend tests and 14 browser regressions pass;
10 PostgreSQL tests are skipped without their dedicated service. Type/lint/build and an isolated
SQLite migration round trip pass. Fixture and Groq development checks do not close D04/D22 or
certify native Fusion installation, live Bedrock, cloud isolation, or a tested client release.
