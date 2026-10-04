# Test evidence: scope and limits

## Evidence classes

| Evidence | Demonstrates | Does not establish |
|---|---|---|
| Unit/component test | Behavior exercised under its fixture | Deployed system or vendor operation |
| Mocked provider/protocol test | Contract/error handling for simulated replies | Real model/vendor authentication or output |
| Frontend fixture browser test | UI behavior with intercepted synthetic API | Backend behavior or real authorization |
| Full-stack test | UI + real local API/DB/compiler/worker paths exercised | Live model/ERP behavior when model/target is mocked |
| PostgreSQL verification | Tested migrations, constraints, RLS/locking on that database setup | Production deployment or untested concurrency cases |
| Static package validation | Configured source/structure/rule checks | Compilation, installation or business correctness |
| Compilation | Compiler accepts the exact source on the stated target | Installed job produces correct business output |
| ERP installation | Exact artifact imported/installed in the authorized target | Successful execution or reconciliation |
| ERP execution | Job ran with recorded target/artifact/parameters | Correct data without output assertions |
| Remote verification | Independent target/output observations bound to artifact/version | Broader untested production operations |
| Human-attested sandbox evidence | Authorized tester attests stated cases/results | Independently verified remote bytes/execution |
| Production qualification | Applicable tested security/operational/release criteria | Zero bugs or universal ERP support |

## Existing check entry points

Use locked setup from [README](../../../../README.md) and current scripts.
Do not load customer `.env`/documents into test fixtures or contact providers
merely because a test command is documented here.

- Backend, from `backend/`: `uv run --no-sync python scripts/check_quality.py`
  and `uv run --no-sync pytest -q`. [pyproject.toml](../../../../backend/pyproject.toml)
  defines tooling, markers and typing scope.
- PostgreSQL suites require a dedicated `TEST_POSTGRES_URL` whose database name
  ends `_test`. [compose.test.yaml](../../../../compose.test.yaml) provisions a
  disposable fixture; tests create/drop random fixture databases. Missing service
  means skipped evidence, not a successful PostgreSQL check.
- Frontend, from `frontend/`: `npm run typecheck`, `npm run lint`, `npm test`,
  `npm run build`, `npm run test:e2e`, `npm run test:e2e:fullstack`.
  [package.json](../../../../frontend/package.json) is the command source.
- [Fixture browser config](../../../../frontend/playwright.config.ts) runs isolated
  desktop/compact tests on port 4173 with synthetic API fixtures.
- [Full-stack config](../../../../frontend/playwright.fullstack.config.ts) uses
  separate ports and a disposable database/API/worker. Its
  [supervisor](../../../../frontend/e2e-fullstack/server.mjs) avoids the user's
  `.env` and database; [Demo ERP acceptance](../../../../frontend/e2e-fullstack/onboarding.spec.ts)
  tests configuration/provenance/version pins with a mock LLM. It does not cover
  a real vendor installation or certify a complete tested package release.

## Quality and reporting

Backend/frontend diagnostic ledgers reject new debt; pruning only removes
resolved entries. Do not enlarge baselines or add broad suppressions to make a
check pass. Type checking covers configured TypeScript inputs; legacy JSX is not
fully type-checked. Inspect [tsconfig](../../../../frontend/tsconfig.json) before
claiming coverage, including new test directories.

[CI](../../../../.github/workflows/quality.yml) defines checks and synthetic
evidence uploads. A workflow definition is not evidence a run succeeded. Distinguish
local results, CI results and live qualification; state skips/failures explicitly.
Do not copy historical pass counts from documentation as today's results.

Select checks for the authorized task. Documentation-only guidance work normally
needs frontmatter/link/content checks, not running application suites or starting
customer services. Consult [local verification](../../../../docs/architecture/local-verification.md)
for fixture procedures, while reconciling stale recorded counts with actual runs.
