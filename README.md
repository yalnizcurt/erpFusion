# HighStudio

ERP integration engineering with configurable profiles, versioned artifacts, validation checks, and human review.

Implementation follows [the production implementation plan](docs/production-implementation-plan.md). Phase 0 establishes repeatable setup and quality checks. Phase 1 adds verified identity, client ownership, onboarding, permissions, and PostgreSQL isolation. Exact revision workflow, package adaptation, connections, sandbox testing, and release qualification remain tracked in the plan.

## Current capabilities

- ERP profile administration manages workflow stages, prompts, package and knowledge assets, and validation configuration. New requests select a published profile version.
- Oracle generation runs through its implementation adapter. Generic structured generation is available for data-created profiles; special deterministic behavior requires an installed adapter.
- Artifacts have versions, validation results, review actions, and generation context metadata. Current lineage and concurrency limitations are documented in the defect register.
- Validation checks are application checks. A passing result does not prove that code compiles, installs, or runs correctly in an ERP sandbox.
- Clients have multiple ERP installations and named environments. Each new integration request selects an explicit client, installation, environment, and published profile version.
- Server-owned platform roles separate ERP configuration from publication; client roles govern onboarding, generation, and review. Reviewer identity comes from authentication. Requests are archived rather than deleted.
- PostgreSQL enforces client row security and parent ownership constraints. Unmapped legacy records are quarantined. See [Phase 1 evidence and deployment prerequisites](docs/architecture/0003-phase-1-identity-client-ownership-foundation.md).
- Real SSO login integration, ERP connections, package installation, and sandbox testing have not been demonstrated against external systems.

## Local setup

Use Python 3.12, `uv`, and Node.js 22.18 or newer. Backend dependencies are locked in `backend/uv.lock`; frontend dependencies are locked in `frontend/package-lock.json`.

### Backend

```bash
cd backend
uv sync --locked --extra dev --extra aws
cp .env.example .env
```

Set `DATABASE_URL` and `GROQ_API_KEY` in `backend/.env`. SQLite is an option for local development:

```ini
DATABASE_URL=sqlite+aiosqlite:///./erpfusion.db
LLM_PROVIDER=groq
GROQ_API_KEY=
DEMO_MODE=false
APP_ENV=development
ARTIFACT_STORAGE_PATH=./artifacts
AUTH_MODE=development
DEV_IDENTITY_USER_ID=development-fixture
DEV_IDENTITY_ROLES=["platform_admin"]
```

Fill in the Groq key before using the authorized local live provider. Missing or sample credentials fail clearly and never select a mock provider automatically. For explicit offline exploration, use `LLM_PROVIDER=mock` and `DEMO_MODE=true`; mock mode is restricted to development/test. Bedrock Converse is implemented for direct regional Nova Pro using workload IAM. Staging/production require Bedrock, an approved private endpoint and data policy; see `backend/.env.example`. Account/model access must be enabled before live Bedrock generation.

Initialize a new development database, provision local storage, and optionally load fixtures:

```bash
uv run --no-sync python -m app.cli development-init
mkdir -p artifacts
uv run --no-sync python -m app.cli seed
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Run the durable generation worker in a second backend terminal with the same configuration:

```bash
uv run --no-sync python -m app.cli.generation_worker
```

The API commits version-bound jobs before responding. The worker claims each job once; navigation does not stop it and changed inputs make old completions stale. This local worker polls the database; the cloud queue/outbox deployment phase remains pending. Production workers require explicitly provisioned client scope.

Import the 22 ERP family drafts through the explicit audited catalogue command:

```bash
uv run --no-sync python -m app.cli.erp_catalogue --actor <operator-identity> --dry-run
uv run --no-sync python -m app.cli.erp_catalogue --actor <operator-identity>
```

Draft catalogue entries are configuration work queues, not certified live ERP adapters. Publish only after approved prompts, knowledge, package assets, output contracts and validation are configured. Existing governed profiles and versions are preserved.

The seed command is development-only. It loads versioned fixtures without overwriting existing ERP configuration or publishing an administrator's drafts. Startup and normal reads do not run migrations, load fixtures, or reconcile stored gates. Optional legacy sample projects remain unowned and hidden by default; create a client-owned request through the UI for the normal flow.

For an existing unversioned SQLite prototype, take a backup before using the explicit compatibility command:

```bash
uv run --no-sync python -m app.cli development-init --legacy-sqlite
```

This additive compatibility operation preserves records and does not stamp the database as Alembic-certified. An unstamped database remains unready. Review and migrate legacy records through the reconciliation procedure before deployment; do not stamp it blindly or infer client ownership from names.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

The Vite server uses port 3000 and proxies `/api` to the backend. For a different port, add that exact origin to backend `CORS_ORIGINS`.

Open **ERP Profiles** to configure stages, publish their prompts/assets, and publish the profile version. Open **Clients** to add a client, installation, sandbox environment, and client memberships. Create an integration request with those explicit selections. The local identity is an explicit development fixture; deployed environments reject development identity headers and shared administrator keys.

For deployed identity, configure `AUTH_MODE=oidc`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_JWKS_URL`. The verified SSO integration must supply access tokens through the frontend's in-memory `configureAccessTokenProvider` hook. No hosted login flow or real organization identity provider has been configured by this implementation. Optional introspection settings provide a per-request revocation check; otherwise token validity lasts until expiry and portal roles/memberships are checked on every request.

## Health and schema management

- `/health` and `/health/live`: process liveness, independent of database availability.
- `/health/ready`: configuration, bounded database connectivity, exact Alembic heads, required tables/columns, and existing storage access. Returns HTTP 503 if a check fails; it never repairs state or exposes credentials.
- `/docs`: local API documentation.

Apply production migrations with a separate privileged migration connection. The application `DATABASE_URL` must use a non-owner, non-superuser role without `BYPASSRLS` or inherited table ownership. Readiness and production authentication reject privileged runtime roles. Readiness detects missing tables/columns and migration mismatch; it does not certify every database constraint or column type. SQLite tests do not replace PostgreSQL migration evidence.

## Verification

Backend:

```bash
cd backend
uv run --no-sync python scripts/check_quality.py
uv run --no-sync pytest -q
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

The quality checks reject new diagnostic fingerprints while recording existing debt. New backend foundation modules have strict typing; frontend TypeScript conversion starts with the API helper and test infrastructure.

`compose.test.yaml` provides an isolated PostgreSQL test service with synthetic credentials and temporary storage. Its dedicated database name ends in `_test`. Set `TEST_POSTGRES_URL` to that service before running backend tests; without it, PostgreSQL tests are explicitly skipped. Tests create/drop only randomly named fixture databases.

CI runs backend quality checks, regressions, PostgreSQL fresh/legacy migration tests, frontend type/lint/unit/build checks, and Chromium fixed-shell/JSON viewport regressions. CI browser traces contain only synthetic fixtures.

## Vercel frontend and Render backend

`render.yaml` is a deployment template requiring organization identity and a restricted runtime database role. The remaining production plan gates still apply before onboarding customer requirements.

1. Import the repository as a Render Blueprint. Configure the approved Bedrock workload identity/private endpoint, OIDC issuer/audience/JWKS settings, and `CORS_ORIGINS` as a JSON array of exact HTTPS frontend origins. The template requires adapting network/identity provisioning to that host; it is not a completed production deployment. Provision a restricted PostgreSQL runtime role and set its connection as `DATABASE_URL`; keep the privileged connection in `MIGRATION_DATABASE_URL` for migrations and administration tooling.
2. The pre-deploy step applies Alembic migrations through `MIGRATION_DATABASE_URL`. Explicitly bootstrap the first administrator using the configured identity provider's stable subject: `python -m app.cli.bootstrap_identity --issuer <configured-issuer> --subject <stable-subject>`. Subsequent role grants use authenticated platform administration. The start command provisions the mounted artifact directory before launching the API. The current disk setup supports a single instance; durable object storage is planned for worker execution.
3. Confirm `/health/ready` returns HTTP 200 with `status: ready`. Startup does not create sample profiles or requests.
4. Import the repository into Vercel with root directory `frontend`, build command `npm run build`, and output directory `dist`. Set `VITE_API_BASE_URL` to the Render origin without `/api`, then redeploy.

LLM, database, and introspection credentials belong only in backend secrets. `VITE_API_BASE_URL` is a public origin. Production/staging reject mock/demo mode, development authentication, insecure identity/CORS endpoints, and non-PostgreSQL database settings. Never place credentials in environment URLs or installation metadata; connection-secret management belongs to the connection phase.

No external telemetry SDK or exporter is configured. Operational logs minimize content and redact credentials and exception values. Controlled engineering evidence and audit records have a separate retention policy in `docs/security/`.

## Requirement intake and sandbox packages

Home is the project directory; each project resumes in Studio. PDF/DOCX/TXT/Markdown uploads are privately stored, bounded, scanned and parsed. Production downloads and generation require a clean scan; without a configured local scanner uploads remain blocked. Development-only unscanned fixtures are explicitly labeled. Requirement/context revisions invalidate active descendants and preserve previous inputs, decisions, runs and downloads.

Clients → Environment provides scoped connection configuration, write-only Secrets Manager onboarding and Ping. The installed Fusion Publisher protocol checks reachability/authentication separately from tenant identity, native import and execution qualification. No URL/password pair establishes deployment permission.

Package preparation creates an immutable complete source ZIP from exact approved, validated revisions. Individual configured sources, including `.pks` and `.pkb`, can be downloaded from those bytes. Assisted sandbox attestations and sign-off create a historical release with evidence; they do not establish automatic native installation or independently verified remote bytes. **Fusion SaaS cannot receive arbitrary PL/SQL**: use a qualified native Publisher report/data model, or select a separate authorized Oracle database target for PL/SQL.

The live Fusion demo still needs a real non-production tenant, dedicated credentials, approved native baseline and independent expected outputs. See [the phase plan](docs/product-ui-bedrock-and-oracle-sandbox-plan.md) for qualification and cloud delivery gates.
