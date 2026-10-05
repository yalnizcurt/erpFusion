# ADR 0001: Repeatable verification and explicit legacy debt

Date: 1 October 2026  
Status: Accepted for Phase 0  
Owner: Platform engineering

## Context

The prototype lacked frontend/browser test runners and repeatable CI. Existing backend tests used
SQLite. Initial measurements found 593 Ruff findings (490 line-length findings) and 77 mypy
findings with untyped function bodies checked. Frontend lint has nine warnings and the production
build has a bundle-size warning. These counts are inherited work, not security release exceptions.

## Decision

- Preserve the FastAPI/React stack and introduce checks incrementally.
- Pin Python production/development dependencies in `backend/uv.lock`; CI runs
  `uv sync --locked --extra dev`. Frontend CI runs `npm ci` from its lock.
- Ruff checks the entire backend; mypy checks `app`, tools and the PostgreSQL smoke suite.
  Settings, database, startup, new core/CLI modules and providers use explicit strict options.
- `backend/scripts/check_quality.py` matches exact tool/file/rule/message/source-line fingerprints
  and occurrence counts. New diagnostics fail. The prune command only removes resolved entries.
  CI never regenerates the ledger; changes accepting debt require review.
- Frontend `scripts/check-lint.ts` enforces the same policy for its nine inherited warnings.
- TypeScript checks all introduced typed sources/configuration/fixtures/tools. The API URL helper
  is the first converted production module. Existing JSX remains explicit conversion debt.
- Vitest runs deterministic helper/component tests. Playwright runs the actual Vite application
  at 1440×900 and 1024×768, with synthetic API responses and external browser requests blocked.
- PostgreSQL tests create disposable databases for clean installation and upgrade from a populated
  `20260929_01` fixture. They check migration head, required columns, preserved requirements,
  prompts and explicit profile bindings. No test invokes `create_all` to certify a migration.
- CI has read-only repository permissions and verified immutable action commits. It requires no
  customer/provider credentials. Controlled failure evidence retention is seven days.

## Limits

The diagnostic ratchet does not certify bug-free or production-secure code. Fix audit defects in
their owning phases and prune the ledger. Migration smoke is narrower than qualification: later
phases add constraint/type equivalence, runtime-role/RLS tests, representative legacy copies and
restore exercises. Browser fixtures do not replace authenticated UI-only Demo ERP onboarding,
live model tests or vendor installation qualification.

Security scans, signed provenance, penetration tests, runtime egress/privacy inspection and load/
recovery exercises remain release requirements. Browser archives follow locked Playwright;
tool/image/action/dependency updates require reviewed test evidence.

See [local verification](local-verification.md), [defect register](../defect-test-register.md)
and [security register](../security/verification-register.md).
