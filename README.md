# erpFusion

**AI ERP Integration Engineering Agent** — Converts business requirements and ERP context into reviewable, versioned integration artifacts. ERP behavior is supplied by published profiles; Oracle Fusion is the initial configured profile and strategy adapter.

> **Guiding Principle**: AI accelerates engineering work; deterministic engines validate; humans retain engineering authority.

---

## 🌟 Key Capabilities

1. **Profile-Defined Workflow**:
   - **Gate 1: Context Analysis**: Identifies ERP tables, columns, join conditions, extraction modes, assumptions, and ambiguities.
   - **Gate 2: Functional Design (FDD)**: Generates complete business attribute mappings, sanitization rules, and output specifications.
   - Existing Oracle stages use the preserved Oracle generation adapter. Other profiles can define different stages and use generic structured generation or an installed implementation adapter.

2. **Deterministic Validation Engine**:
   - **Schema Conformity**: Verifies all referenced tables, columns, and joins against ERP schema context — flags LLM hallucinations immediately.
   - **SQL Structure & Bind Safety**: Checks for read-only query compliance, bind variable compliance, and text sanitization.
   - **PL/SQL Compile Readiness**: Validates spec-to-body alignment, public procedure implementations, and exception handling blocks.
   - **Traceability Validator**: Checks end-to-end lineage from requirement attributes to final extraction queries.

3. **Human-in-the-Loop Review Governance**:
   - One-click Approve, Request Changes (with feedback loops), or Reject.
   - Automatic cascade invalidation of downstream artifacts when upstream designs change.
   - Version history and visual diff comparison across revisions.

4. **Configured LLM Support**:
   - Groq API configured with `openai/gpt-oss-120b`.
   - Built-in High-Fidelity Demo Provider for immediate out-of-the-box exploration.

5. **Governed ERP Configuration**:
   - Admins create ERP profiles and configure workflow stages, prompts, validation rules, standard packages, and knowledge assets in the ERP Profiles console.
   - Published profile versions are immutable. New requests pin an exact published version; a request may be upgraded before generation starts.
   - The prompt compiler retrieves relevant profile assets and approved feedback, and each generation records the resolved context and provenance.

---

## 🚀 Quick Start

### 1. Configure Environment

The backend `.env` is created at `backend/.env`. Add your Groq key and a separate administrator key for ERP configuration:
```ini
DATABASE_URL=sqlite+aiosqlite:///./erpfusion.db
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
ERP_ADMIN_API_KEY=replace_with_a_long_random_secret
```

### 2. Start Backend Server (FastAPI)

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- Interactive Swagger API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

### 3. Start Frontend UI (Vite + React)

```bash
cd frontend
npm run dev
```
- Access UI on: [http://localhost:3000](http://localhost:3000)

### 4. Run Unit Tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```
The suite covers workflow, validation, and data-created Demo ERP generation.

### ERP administration

Open **ERP Profiles** from the app navigation and connect with `ERP_ADMIN_API_KEY`. Create an ERP profile, configure workflow stages and validation rules, add and publish a prompt for every configured stage, add/publish package and knowledge assets, then publish the profile version. Only published profiles appear when creating new integration requests. Profiles may use `generic_json`; ERPs that require specialized deterministic code need an installed strategy adapter.

---

## 🏗️ Architecture

```

## Database changes

Apply Alembic migrations to PostgreSQL before deploying. Development startup creates missing SQLite tables and applies an additive compatibility upgrade to older local prototype databases; it preserves existing records. Production schema changes are not run automatically by the app.

## Deploy: Vercel frontend + Render backend

The repository includes a Render Blueprint at `render.yaml`. It provisions a FastAPI service, managed PostgreSQL, a persistent disk for uploaded ERP packages/knowledge files, and runs Alembic migrations before each deploy. The database and disk use paid Render plans because uploaded files must survive service restarts and deployments.

1. Push this repository to GitHub. In Render, create a Blueprint from the repository and review the resources and pricing before applying it. Enter `GROQ_API_KEY`, a long random `ERP_ADMIN_API_KEY`, and `CORS_ORIGINS` when prompted. For CORS, enter a JSON array containing the exact Vercel production origin, for example `["https://your-project.vercel.app"]`; add your custom domain too if you use one. Do not use `*`.
2. Wait for Render to finish. Check `https://<your-render-service>.onrender.com/health` and confirm it returns `healthy`.
3. In Vercel, import the same repository and set the **Root Directory** to `frontend`. Use `npm run build` as the build command and `dist` as the output directory.
4. Set the Vercel environment variable `VITE_API_BASE_URL` to the Render service origin only, such as `https://erpfusion-api.onrender.com` (no trailing slash and no `/api`). Apply it to Production and redeploy. Local development keeps using the Vite `/api` proxy.
5. Open the Vercel URL, add the initial ERP profile through **ERP Profiles**, and create a request. Production startup intentionally does not run development seed data.

The API origin is public; only `ERP_ADMIN_API_KEY` and the LLM key belong in Render secrets. This prototype does not yet provide end-user authentication for project or artifact APIs, so deploy it for controlled evaluation only and do not put confidential or customer requirements in it until access control is added.

Render references: [Blueprint configuration](https://render.com/docs/blueprint-spec), [PostgreSQL connection variables](https://render.com/docs/blueprint-spec#referencing-service-properties). Vercel references: [Vite deployment](https://vercel.com/docs/frameworks/frontend/vite).
erpFusion/
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI routes (projects, artifacts, reviews, generation)
│   │   ├── models/          # SQLAlchemy async models & enums
│   │   ├── schemas/         # Pydantic request/response schemas
│   │   ├── services/
│   │   │   ├── ai/          # Oracle generation implementation, called only through its adapter
│   │   │   ├── llm/         # LLM abstraction (Groq openai/gpt-oss-120b + Mock fallback)
│   │   │   ├── validation/  # Generic/configured validation and Oracle validators
│   │   │   ├── codegen/     # Configured implementation strategy adapters
│   │   │   ├── prompt_compiler.py # ERP context, retrieval, and generation provenance
│   │   │   └── workflow.py  # Profile-driven workflow and human gates
│   │   ├── config.py        # Pydantic settings
│   │   └── main.py          # FastAPI application factory
│   └── tests/               # Pytest suite (workflow & validation)
├── frontend/                # Vite + React interactive UI
│   ├── src/
│   │   ├── components/      # Header, WorkflowPipeline, ArtifactViewer, DiffViewer, TraceabilityMatrix
│   │   ├── App.jsx          # Interactive dashboard
│   │   └── index.css        # Enterprise glassmorphism dark theme
│   └── vite.config.js       # Dev server proxying /api to port 8000
└── problemStatement.md      # System requirements specification
```
