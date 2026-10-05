# Phase 0 implementation evidence

Date: 2 October 2026  
Status: Complete for the Phase 0 acceptance scope; later plan phases remain open.

## Delivered

- `create_app` owns application lifecycle and accepts injected settings, engines, and session dependencies. Importing or starting the API does not create tables, run migrations, publish fixtures, or reconcile workflow state.
- `/health/live` is process liveness. `/health/ready` performs bounded configuration, database, migration-head, schema, and pre-provisioned storage checks and returns safe failure codes without repairing state.
- `python -m app.cli development-init` is the explicit Alembic initialization command. `seed --include-sample-projects` is a development-only, versioned, idempotent fixture command. Existing profile versions and administrator drafts are not republished or overwritten.
- Read routes no longer seed data or rewrite workflow status. Legacy unversioned SQLite compatibility is explicit and does not claim an Alembic revision.
- Missing or sample live-provider credentials fail closed. Mock generation requires an explicit development/test demo flag and is rejected in staging/production. Provider bodies, document content, credentials, and exception values are excluded from ordinary operational logs.
- Render runtime storage is provisioned at process start, while migrations remain a separate deployment command. Vercel/Render setup and health paths are documented without claiming authenticated client isolation.
- Backend and frontend quality ratchets, dependency locks, local synthetic PostgreSQL fixtures, CI, unit tests, and fixed-shell/long-JSON browser regressions are checked in.

## Verification

| Check | Result |
|---|---|
| Backend regression suite | 99 passed, 2 PostgreSQL tests skipped when `TEST_POSTGRES_URL` is absent |
| PostgreSQL fresh migration | Passed in a disposable PostgreSQL 16.2 database |
| PostgreSQL legacy upgrade and explicit binding preservation | Passed in a disposable PostgreSQL 16.2 database |
| Backend quality ratchet | Passed; 478 Ruff and 37 mypy diagnostics remain in the recorded legacy ledger |
| Frontend typecheck/lint/unit/build | Passed; 3 unit tests passed and 9 inherited lint warnings remain in the ledger |
| Browser regression setup | CI and the checked-in local verification procedure run four Chromium cases with synthetic API fixtures; a direct rerun in this environment was blocked by local-port sandbox permissions |

The disposable PostgreSQL cluster was created only for these fixtures. No application database or customer data was used. The cluster could not be stopped after the sandbox escalation reviewer reached its usage limit; it is isolated to `/private/tmp/erpfusion-phase0-postgres-20261001` and port `55439`, and should be stopped with `pg_ctl` when escalation is available.

## Remaining qualification

Phase 0 does not provide authenticated users, client isolation, PostgreSQL row-level security, exact concurrent revision transitions, durable generation jobs, object storage, ERP connection credentials, package installation, sandbox execution, or release qualification. Those are explicit acceptance work in Phases 1–11. The current deployment configuration is therefore for controlled evaluation only.
