# Local verification

Use synthetic fixtures. Keep customer credentials/documents outside test databases and browser
fixtures. Commands below explicitly distinguish local deterministic checks from real PostgreSQL.

## Backend

```sh
cd backend
uv sync --locked --extra dev --extra aws
uv run --no-sync python scripts/check_quality.py
APP_ENV=test LLM_PROVIDER=mock DEMO_MODE=true GROQ_API_KEY= ERP_ADMIN_API_KEY= uv run --no-sync pytest -q -m 'not postgres'
```

The quality command reports inherited findings and fails on new ones. After fixing debt, run
`uv run --no-sync python scripts/check_quality.py --prune-baseline` and review the ledger diff.
It cannot add accepted debt.

Startup/read endpoints do not initialize a schema or load fixtures. PostgreSQL uses Alembic.
The explicit development fixture command is `python -m app.cli seed`; it requires an initialized
database and `APP_ENV=development`. Sample requests need `--include-sample-projects`.
See the main README for the explicit development initialization route.

## PostgreSQL migration tests

```sh
docker compose -f compose.test.yaml up -d --wait
cd backend
TEST_POSTGRES_URL=postgresql+asyncpg://erpfusion_test:local-fixture-only@127.0.0.1:55432/erpfusion_test uv run --no-sync pytest -q -m postgres
cd ..
docker compose -f compose.test.yaml down
```

This password belongs only to the disposable, loopback-only fixture. The fixture role requires
CREATEDB. Alternatively use an existing dedicated local PostgreSQL instance through
`TEST_POSTGRES_URL`; its database name must end in `_test`. Each test creates/removes only an
internally generated `erpfusion_migration_<uuid>` database.

Without the variable, the PostgreSQL tests report SKIPPED. This is unavailable evidence, not a
passing migration check. CI supplies its real PostgreSQL fixture.

## Frontend

Use Node 22.18 or newer; the lint tool uses Node's built-in TypeScript stripping.

```sh
cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests start their own isolated server on port 4173. They use synthetic API fixtures,
block external browser requests, and never reuse the user's open portal/backend. Tests verify
long JSON cannot expand the viewport/hide navigation, header/sidebar/footer stay fixed while
content scrolls, and downstream gates display locked behind a pending first stage.

`npm run lint:report` shows raw warnings. Prune resolved entries with
`node scripts/check-lint.ts --prune-baseline` and review the diff. Type checking covers typed
files; legacy JSX is covered by tests/build until feature owners convert it.

## CI

`.github/workflows/quality.yml` runs locked backend quality/tests with real PostgreSQL and
frontend type/lint/unit/build/browser checks. It uses no customer/provider secrets and does not
deploy, publish ERP profiles, install customer packages or contact an AI provider.

## Recorded local evidence — 2 October 2026

- Backend: 265 passed, 10 skipped. The skipped PostgreSQL checks require a dedicated fixture;
  no real PostgreSQL isolation/concurrency certification or CI execution is claimed.
- Frontend: 53 unit tests and 14 desktop/compact browser regressions passed. Type checking,
  lint and the production build passed. The inherited 802 kB main bundle warning remains.
- Quality ratchet passed: 280 inherited Ruff and 13 mypy diagnostics remain; no new diagnostic
  debt was accepted. Frontend lint has no remaining warnings.
- An isolated SQLite database upgraded to head, downgraded to `20261002_02`, and upgraded to
  head again. The actual development database was backed up before its explicit migration.
- The actual local portal created a client-owned synthetic project and uploaded a TXT
  requirement. Real Groq `openai/gpt-oss-120b` assessed it; missing schema and unresolved
  assumptions were identified, corrections produced four preserved assessment revisions,
  and project-scoped review guidance was recorded. The fourth assessment correctly described
  four CSV output columns. Its test-only approval was submitted through the local API after
  review; only FDD unlocked. Real FDD generation completed with schema/cross-artifact checks
  passing and a content-free provider receipt, and remains pending review. TDD and package
  gates remain locked. The approval dialog is now an explicit in-app revision confirmation.
- Groq is the user's authorized local synthetic-test provider. No customer data was used.
  Bedrock is configured and enforced for staging/production; live invocation is deferred.
- No real ERP endpoint, credential, native Publisher baseline, compilation or sandbox output
  was supplied or tested. Candidate/release download and manual evidence tests use synthetic
  fixtures; they do not certify native import, execution, or vendor installation support.
