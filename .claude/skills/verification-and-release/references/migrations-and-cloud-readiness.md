# Schema verification and cloud readiness

## Database responsibilities

Read [Alembic environment](../../../../backend/alembic/env.py),
[migration chain](../../../../backend/alembic/versions/),
[database construction](../../../../backend/app/database.py),
[readiness](../../../../backend/app/core/readiness.py) and
[development CLI](../../../../backend/app/cli/__main__.py).

Schema changes belong in reviewed migrations. Startup, health and ordinary reads
do not create tables, migrate, load fixtures, publish profiles or repair gates.
Apply production migrations with the separate privileged connection; runtime
uses a restricted role and transaction-local client scope.

The explicit `development-init` command applies initialization for development;
`--legacy-sqlite` is additive compatibility for unversioned prototypes, not
Alembic certification. Preserve legacy records and explicit bindings, back up
authorized databases before migration, and do not stamp an unverified database
or guess client ownership from names. Catalogue/fixture loading are separate
audited commands and must not overwrite governed configuration.

[Migration smoke tests](../../../../backend/tests/test_migration_smoke.py) and
[PostgreSQL isolation tests](../../../../backend/tests/test_postgres_isolation.py)
exercise disposable PostgreSQL. SQLite migration round trips cannot establish
PostgreSQL policies, role behavior or concurrency. A new migration needs evidence
appropriate to its dialect, preserved data, constraints and ownership effects.

## Readiness limits

Liveness is independent of database availability. Readiness checks configuration,
bounded connectivity, required migration heads/tables/columns and existing storage;
it fails without repairing state. It does not certify all types/constraints,
external ERP permissions, native compilation, Bedrock account access, recovery
or production throughput. Interpret safe readiness codes without logging secrets.

## Infrastructure source and known gaps

- [Dockerfile](../../../../Dockerfile) packages a restricted API process.
- [AWS foundation](../../../../deployment/aws/foundation.json) and
  [buildspec](../../../../deployment/aws/buildspec.yml) describe infrastructure/build
  intent; [migrate.py](../../../../deployment/aws/migrate.py) handles explicit runtime
  role/bootstrap provisioning through privileged tooling.
- [Source packaging](../../../../deployment/aws/package_source.py) uses an allowlist
  to exclude local secrets, databases and customer artifacts. Do not widen it
  indiscriminately to fix a missing build file.
- [Vercel config](../../../../frontend/vercel.json) serves the frontend and browser
  routes. Public `VITE_` values must never contain backend/ERP secrets.
- [Render template](../../../../render.yaml) currently sets Groq although deployed
  [provider/config guards](../../../../backend/app/services/llm/factory.py) require
  Bedrock. Treat that as unresolved template drift; do not weaken the guard.
- The foundation includes earlier Groq-era resources and does not by itself
  establish the required Bedrock private endpoint or production worker/queue
  architecture. The local database-polling worker is not a deployed queue/outbox.

Qualify the actual deployment's OIDC, non-owner PostgreSQL role, storage, approved
provider/network policy, clean upload scanning, client-scoped workers and release
requirements. Do not claim it is ready based on manifests or old cloud logs.
Use the [production plan](../../../../docs/production-implementation-plan.md) as
the target backlog; deployment/migration actions still require task authorization.
