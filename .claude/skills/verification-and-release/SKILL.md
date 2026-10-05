---
name: verification-and-release
description: Select checks and assess evidence for HighStudio changes, database migrations, cloud readiness, immutable packages, sandbox sign-off and release qualification. Use when testing or reporting whether a capability or package is ready, passed, live or production-qualified.
---

# Verification and release

## Use and ownership

This skill owns evidence classification and release-readiness claims. It connects
existing checks to the specific implementation/target under review. It does not
grant approval to change a database, deploy, publish or invoke a live provider/ERP.

## Critical rules

- Report the check actually run, its environment, bindings, result and limits.
  Never promote mocks, fixture tests, static checks or manual attestations into
  successful remote ERP execution.
- Distinguish unit, mocked protocol, frontend fixture, full-stack mock-model,
  PostgreSQL, static validation, compilation, installation, execution, remote
  verification, human-attested evidence and production qualification.
- Package approval/evidence must bind exact current inputs, revisions, candidate
  bytes, environment, connection/secret versions and approved test plan.
- Preserve immutable historical packages and sign-off metadata. Do not describe
  a source bundle as a certified native installer.
- Missing/skipped checks are missing evidence. Quality ratchets preserve explicit
  inherited debt; passing them does not mean the entire codebase is clean.

## Do not assume

SQLite proves PostgreSQL isolation/concurrency. A test name or CI file proves a
test was executed. Readiness 200 proves ERP installation. A manual PASS proves
remote bytes. A new ERP onboarding test qualifies every package stage.

## Pattern architecture reference

Read the [HighStudio pattern architecture](../../../docs/architecture/highstudio-integration-patterns.md)
when a task changes pattern selection, approved baseline pins, target runtime or qualification
claims. Reuse existing intelligence, ownership, revision and evidence services; installation
is required only when the selected pattern contract requires it.

## Source entry points

- [CI](../../../.github/workflows/quality.yml),
  [backend checks](../../../backend/scripts/check_quality.py),
  [frontend scripts](../../../frontend/package.json).
- [Migrations](../../../backend/alembic/), [readiness](../../../backend/app/core/readiness.py).
- [Package service](../../../backend/app/services/packages.py),
  [package routes](../../../backend/app/api/packages.py),
  [sandbox UI](../../../frontend/src/components/SandboxWorkspace.jsx).

## Read as needed

- [Test evidence](references/test-evidence.md): selecting checks and describing results.
- [Migrations/cloud readiness](references/migrations-and-cloud-readiness.md): schema and deployment qualification.
- [Package release evidence](references/package-release-evidence.md): candidate, sandbox and release assurances.
