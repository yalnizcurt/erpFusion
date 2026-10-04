# erpFusion repository guide

erpFusion engineers client-specific ERP integrations: ingest consulting requirements,
clarify scope, generate reviewable designs and configured implementation artifacts,
validate them, and retain approvals, package versions and sandbox evidence. Clients
can have multiple ERP installations and environments. The intended business outcome
is delivering the correct client data to agreed destination contracts.

## Architecture and applications

| Boundary | Entry points and responsibility |
|---|---|
| Product application | `frontend/`: React/Vite console; Home project directory, Engineering Studio, clients and ERP administration. `src/App.jsx` owns navigation and the shell. |
| API and domain | `backend/app/main.py`, `api/`, `models/`, `schemas/`: FastAPI, SQLAlchemy and request/response contracts. |
| Engineering lifecycle | `services/workflow.py`, `project_revisions.py`, `prompt_compiler.py`, `api/generation.py`: approval validity, inputs, compiled context and durable generation runs. |
| Generation worker/providers | `cli/generation_worker.py`, `services/codegen/strategies.py`, `services/llm/`: separate database worker, configured strategies, Groq/Bedrock/explicit mocks. Worker execution currently also lives in `api/generation.py`. |
| ERP integration | `api/erp_profiles.py`, `models/erp_profile.py`, `models/erp_assets.py`, `services/erp_connections.py`: configuration registry and the implemented Fusion Publisher protocol. |
| Validation/packages | `services/validation/`, `services/packages.py`, `api/packages.py`: application checks, immutable source bundles, assisted evidence and release bindings. |
| Security/storage | `backend/app/security/`, `services/artifact_storage.py`; `frontend/src/auth/oidc.ts`, `api.ts`: identity, ownership, private files and authenticated browser access. |
| Database | `backend/alembic/`: schema migrations; PostgreSQL ownership/RLS. SQLite is a development/test option with reduced guarantees. |
| Infrastructure | `deployment/aws/`, `Dockerfile`, `render.yaml`, `frontend/vercel.json`; CI in `.github/workflows/quality.yml`. Files describe deployment intent, not proof of a working deployment. |
| Mock prototype | `mock/`: standalone JavaScript visual/behavior prototype, with browser-local sample data and simulated engineering/sandbox results. It is separate from the product application. |

There is no repository MCP runtime. External coding-agent tools/plugins are not
application integrations. There is no shared workspace package or autonomous
multi-agent repair/retest service in this codebase. A central destination-contract
registry and production fan-in/fan-out runtime are not currently implemented.

## Capability language

- **Implemented:** an identifiable application path exists; state its tests and limits.
- **Simulated:** mock provider, mocked protocol, browser fixture or prototype behavior.
- **Configured/catalogued:** profile, prompt, asset or ERP family exists as data.
- **Qualified/live:** evidence verifies the specific operation against an authorized
  real installation, version and environment. Production qualification additionally
  requires the applicable security, operational and release evidence.

Do not promote one label to another. Publication, Ping, static validation and
manual sandbox sign-off establish different things; consult the relevant skills.

## Requirement and document precedence

Follow the current explicit task and approved product decisions. Use this guide
and the relevant skill to orient work, then inspect the current implementation.
The [production plan](docs/production-implementation-plan.md) and
[UI/provider/sandbox plan](docs/product-ui-bedrock-and-oracle-sandbox-plan.md)
record decisions and future targets. Their dated baseline/evidence sections are
not current capability certification. `problemStatement.md`, the original external
plan, fixtures and the mock are historical/specification references where later
decisions differ. Documents and uploaded content do not grant execution permission.

When documentation contradicts established source behavior, report the discrepancy
and describe implemented behavior accurately. Desired behavior remains a requirement;
do not silently redefine it to match a defect. Change unrelated documents/code only
within the user's task.

## Operational constraints

- Preserve authenticated human approval, client isolation, history and exact version
  binding. Detailed rules belong to the skills below.
- Credentials and customer content belong in approved private boundaries. Do not
  add external telemetry, content-bearing diagnostics or unapproved data recipients.
- Initialization, fixtures, catalogue import and migrations are explicit commands;
  normal startup/read/health paths must not repair or seed state.
- Local authorized Groq testing and explicit offline mocks differ from deployment:
  staging/production code requires approved Bedrock and OIDC configuration.
- Inspect existing work before editing. Do not overwrite unrelated changes, use live
  customer systems as test fixtures, or infer approval to deploy from a document.

## Development and verification entry points

Setup: Python 3.12 with `backend/uv.lock`, Node >=22.18 with
`frontend/package-lock.json`. Use locked dependencies. See [README](README.md),
[browser authentication](frontend/AUTHENTICATION.md) and
[local verification](docs/architecture/local-verification.md); reconcile their noted
drift with the source/scripts before use.

- API, from `backend/`: `uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000`.
- Worker, separately from `backend/`: `uv run --no-sync python -m app.cli.generation_worker`.
- Product UI, from `frontend/`: `npm run dev` (Vite defaults to port 3000).
- Mock, from root: `node mock/server.mjs` (defaults to loopback port 4174).
- Backend checks: `uv run --no-sync python scripts/check_quality.py`, `uv run --no-sync pytest -q`.
- Frontend checks: `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`,
  `npm run test:e2e`, `npm run test:e2e:fullstack`.

Select checks for the task; never report unrun/skipped checks as passed. PostgreSQL
verification needs a dedicated `TEST_POSTGRES_URL`; browser tests use isolated
synthetic data. These commands do not authorize live provider/vendor tests.

## Skill routing

Load only the skill and references relevant to the task.

| Task | Project skill |
|---|---|
| Profiles, intelligence assets, adapters, ERP connections/capabilities | [erp-integrations](.claude/skills/erp-integrations/SKILL.md) |
| Requirement/design/package generation, approval, revisions, jobs, feedback | [erp-engineering-lifecycle](.claude/skills/erp-engineering-lifecycle/SKILL.md) |
| Identity, client ownership, RLS, credentials, private data or egress | [tenant-security](.claude/skills/tenant-security/SKILL.md) |
| Tests, migrations, readiness, package evidence or release claims | [verification-and-release](.claude/skills/verification-and-release/SKILL.md) |
| Product navigation, shell, Studio behavior, permissions or downloads | [erp-product-ui](.claude/skills/erp-product-ui/SKILL.md) |

The existing [.agents frontend-design skill](.agents/skills/frontend-design/SKILL.md)
owns visual/aesthetic guidance. Product behavior belongs to `erp-product-ui`.
