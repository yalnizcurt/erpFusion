# HighStudio production implementation plan

Date: 1 October 2026  
Status: Proposed implementation specification; application changes are not implemented by this document.  
Scope: Upgrade the existing HighStudio repository into a governed engineering platform for approximately 4,500 clients and the 22 ERP families supplied by the product owner.

## Product navigation update — 2 October 2026

The user specified a project-table Home page and a persistent project Engineering Studio.
Home columns are client name, project name, ERP, Standard/Custom type, status, due date,
Last updated, and authorized package download, with Create New above the table.
Workflow, requirement document upload, generation, reviews, revisions/history and sandbox
work belong in Studio. Users must be able to leave and resume and revise earlier stages
without losing history. These navigation requirements supersede the prototype's Home pipeline.

See [the Home and Engineering Studio delivery plan](home-and-engineering-studio-plan.md)
for concrete routes, persistence/date semantics, acceptance scenarios and end-to-end slices.
Its durable execution and exact-revision requirements remain prerequisites for truthful
resume/backtracking behavior; a visual navigation change alone is insufficient.

## Product design, provider and sandbox update — 2 October 2026

The user approved the JavaScript mock's visual design and requested Bedrock, no
unauthorized external data recipients, all 22 ERP profiles, a connection Ping button
and a real Oracle Fusion sandbox demonstration. See [the product UI, Bedrock and
Oracle sandbox plan](product-ui-bedrock-and-oracle-sandbox-plan.md) for the current
delivery order, capability qualification, secure connection setup and live test gates.
It supersedes earlier Google Docs/external-provider assumptions. The Fusion demo
uses a qualified Publisher report/API target; PL/SQL requires a separately configured
compatible database target. URL/password access alone does not establish installation.

## 1. Outcome and requirement precedence

The intended flow is:

```text
Client and ERP installation selected
  → Requirement documents uploaded and parsed
  → Questions resolved and requirement assessment approved
  → FDD generated, revised as needed, and approved
  → TDD generated, revised as needed, and approved
  → Approved AS-IS package adapted to the TDD
  → Package built, validated, revised as needed, and approved
  → Approved candidate downloaded or installed in the designated sandbox
  → Sandbox tests recorded and tester sign-off completed
  → Final tested release available for download
```

At every change, preserve history and invalidate affected active downstream work. AI proposes; authenticated humans approve exact revisions. ERP-specific behavior comes from published configuration and installed capability adapters.

The original `plan (1).md` is requirements evidence. Subsequent explicit product requirements take precedence where they differ:

- Identity and client isolation are foundational, rather than deferred extensions.
- Requirement document ingestion is part of the normal intake flow.
- Implementation adapts an approved AS-IS package, with its exact version recorded.
- A client can have multiple ERP installations and environments.
- Sandbox testing and current test evidence are required for final completion.
- SQL and individual package files are configured implementation artifacts; the platform does not require every ERP to use the Oracle stage layout. Profiles may require a separate SQL review.
- Keep the existing HighRadius header, sidebar, and bottom bar fixed; scroll the content regions.
- Disable third-party telemetry and tracking. Governed audit records and internal operational records have an explicit, documented policy.
- Use internal versioned document templates/editing and Word/PDF exports. The latest data-boundary requirement supersedes the original Google Docs template-copy requirement.
- Use only the approved Bedrock provider/model/Region in the intended AWS deployment; block unauthorized providers and qualify retention/residency before enabling generation.

Do not claim zero defects, universal automatic rollback, identical future LLM outputs, or automatic installation support based solely on an ERP name. Define and demonstrate measurable release criteria.

## 2. Repository baseline and immediate problems

Use [the application audit](application-audit-2026-10-01.md) as the initial defect register. Inspection for this plan reconfirmed the following implementation boundaries:

| Existing code | Required change |
|---|---|
| `backend/app/main.py` | Remove startup schema/seed writes; add application factory, explicit dependencies, liveness and readiness. |
| `backend/app/api/projects.py` | Remove seed writes from reads; add authenticated client ownership, input revisions, request queries, archival. |
| `backend/app/api/admin_auth.py` | Replace the shared administrator identity with authenticated, authorized users. |
| `backend/app/services/workflow.py` | Enforce exact dependency revisions, atomic transitions, in-flight invalidation, pure query operations. |
| `backend/app/api/generation.py` | Create durable runs before execution; enqueue work; move orchestration and validation out of routes. |
| `backend/app/models/project.py` | Add client/installation/environment ownership; normalize immutable requirement/context/configuration revisions. |
| `backend/app/models/version.py` | Separate immutable artifact content, approval decisions, and current validity. |
| `backend/app/models/erp_assets.py` | Normalize stable resource identities, version bindings, scope constraints, audit and job metadata. |
| `backend/app/api/erp_profiles.py` | Split typed profile, prompt, package, knowledge, publication, and configuration APIs. |
| `backend/app/services/prompt_compiler.py` | Resolve exact configuration; retrieve scoped sections; produce the actual provider request and source provenance. |
| `backend/app/services/codegen/strategies.py`, `services/ai/` | Preserve Oracle behavior inside its adapter; remove hidden prompt rewrites and apply effective settings. |
| `backend/app/services/validation/engine.py` | Replace misleading heuristic PASS results with typed checks, language-aware validation, and separate compilation evidence. |
| `backend/app/services/llm/base.py`, `factory.py` | Remove content-bearing error logs and silent production mock fallback; record provider receipts. |
| `frontend/src/App.jsx`, `components/BottomCards.jsx` | Correct stale requests/review targets, PKB display, lost comments, errors, and duplicated submissions. |
| `frontend/src/components/ERPAdmin.jsx` | Add typed administrative editors, publication readiness, resource versioning, and registry refresh. |
| `frontend/src/components/DeploymentPackageView.jsx` | Replace browser-derived readiness and bundle assembly with authoritative release APIs. |
| `render.yaml`, `frontend/vercel.json` | Add production execution/storage/readiness configuration and validate actual provider controls. |

The repository currently contains a Git checkout. Preserve existing local changes, including `backend/alembic/env.py` and `frontend/.gitignore`, and preserve the audit document. Use small reviewed changes on `codex/` branches during implementation.

The earlier audit reports 27 passing backend tests and a passing frontend build with lint/bundle warnings. Those results are historical evidence, not proof that the new acceptance criteria are met. Re-establish the baseline before implementation; this planning task did not rerun tests.

## 3. Architecture decisions

### 3.1 Preserve and strengthen the existing stack

- Retain FastAPI, SQLAlchemy, Alembic, React, and Vite. Introduce strict Python typing and incrementally convert the frontend to TypeScript.
- Start with a modular backend and separately deployed execution workers. Extract additional services only when isolation or measured scaling needs justify them.
- PostgreSQL is the production system of record and integration-test database. SQLite remains a clearly identified local development option; it does not certify PostgreSQL behavior.
- Use private object storage for durable artifacts. A single application server's local disk is a development option, not the multi-worker storage contract.
- Use a durable queue with database-backed job state and a transactional outbox. Adopt one supported worker runtime through an architecture decision record; evaluate a durable workflow runtime if external-operation recovery requires it. Business workflow truth remains in the application database.
- Use a secret-store interface and provider implementations. Persist secret references in application records.
- Generate a typed frontend client from a versioned OpenAPI contract. Keep UI state, server state, and workflow state distinct.

### 3.2 Module boundaries

```text
backend/app/
  core/             settings, errors, redacted logging, readiness
  security/         identity, permissions, tenant context, secret access
  models/           relational entities and constraints
  schemas/          typed transport and configuration contracts
  api/              thin authenticated HTTP routes
  repositories/     tenant-scoped persistence and atomic commands
  services/
    clients/        client, installation, environment administration
    workflow/       transitions, dependency lineage, review, invalidation
    registry/       profiles, prompts, assets, publication, manifests
    ingestion/      scanning, extraction, OCR, chunking, clarification
    retrieval/      scoped source selection and provenance
    generation/     context resolution, compilation, effective requests
    documents/      internal templates, rendered revisions, exports
    packages/       baseline selection, adaptation, diffs, output contracts
    validation/     shared checks and adapter validation
    releases/       candidate eligibility, manifests, bundles
    connections/    verified environment capabilities and discovery
    deployment/     plans, jobs, reconciliation, recovery
    testing/        sandbox tests, manual evidence, sign-off
    audit/          append-only events and retention
  adapters/         versioned capability implementations
  workers/          durable job handlers
  cli/              migrations support and explicit fixture loading

frontend/src/
  app/              fixed shell, authenticated routing, providers
  features/         clients, requests, registry, review, releases, sandbox
  api/              generated client and query/mutation services
  components/       shared design-system components
  contracts/        configuration and artifact types
```

Move existing services incrementally behind compatible interfaces. Avoid a simultaneous full rewrite.

### 3.3 Core domain

```text
Authenticated user → client membership and permissions
Client → ERP installation → environment → connection and secret reference
Client → optional business project → integration request
Integration request → requirement revision / context snapshot / configuration revision
Integration request → artifact → immutable artifact revision
Artifact revision → exact dependencies / validation evidence / review decisions
ERP profile → immutable published profile manifest
Manifest → exact prompts / packages / knowledge / template and adapter versions
Generation run → effective model request / retrieval selections / output / outcome
Release candidate → immutable files and checksums
Release candidate → deployment job → test runs → tester sign-off
Every governed action → audit event
```

Initially retain the existing `Project` table/API as the integration-request identity. Add client ownership and explicit request semantics before considering a rename or a separate business-project entity.

## 4. Coding and review standards

These are enforceable delivery requirements, not descriptive labels:

1. Use typed request/response/configuration models and validated domain values. Raw configuration dictionaries remain inside well-defined versioned payloads, rather than spreading through service interfaces.
2. Keep HTTP routes thin. Services own business rules; repositories own scoped persistence. Define explicit transaction boundaries.
3. Use constructor/dependency injection for providers, storage, clocks, secrets, and adapters. Avoid hidden production dependencies at module import time.
4. Handle expected failures with stable error codes and safe messages. Return conflicts for stale writes. Preserve diagnostic details within authorized internal records.
5. Use timezone-aware UTC persistence and local timezone display. Define stable resource IDs and deterministic serialization/hashing.
6. Allocate versions atomically and enforce uniqueness in PostgreSQL. Published content and approved release bytes cannot be edited in place.
7. Document adapter contracts, compatibility, supported actions, and recovery semantics. Registry keys identify capabilities; ERP names remain data.
8. Use parameterized SQL/commands, bounded inputs, safe parsers, explicit network destinations, and a limited validation-rule language. Avoid `eval`, administrator-supplied executable validators, and uncontrolled shell templates.
9. Lock dependencies, review licenses, scan dependencies/secrets, and build release artifacts from a known source revision.
10. Add regression tests for each corrected defect. Avoid arbitrary coverage percentages as the sole release decision; require coverage of critical invariants and failure paths.
11. Keep lint/type/build/test failures blocking in changed modules. Ratchet existing warnings down with an owned baseline; do not hide them through broad exclusions.
12. Write architecture decisions and operational instructions when behavior changes. README capabilities must match demonstrated functionality.

Security verification targets: OWASP ASVS 5.0 Level 2 with additional controls selected for privileged execution; NIST SSDF development practices; signed artifact provenance informed by SLSA. Maintain a control-to-test evidence register. These are targets until verified, not claims of certification.

References: [OWASP ASVS](https://owasp.org/projects/asvs?tab=main), [NIST SSDF](https://www.nist.gov/publications/secure-software-development-framework-ssdf-version-11-recommendations-mitigating-risk), [SLSA provenance](https://slsa.dev/spec/v1.2/build-provenance).

## 5. Implementation phases

Every phase includes its required API, domain changes, UI, migrations, tests, documentation, and operating behavior. Run the applicable regression suite, type checks, frontend build, PostgreSQL migration checks, and workflow checks before starting dependent work. Record results, external prerequisites, and any remaining capability limitations.

### Phase 0 — Establish a safe, repeatable development baseline

**Change:**

- Create `docs/architecture/`, `docs/security/`, and a defect-to-test register tied to the existing audit.
- Establish repeatable local services and isolated PostgreSQL test fixtures; keep secrets and real customer data outside fixtures.
- Add CI configuration for backend lint/type/unit/integration checks and frontend lint/type/build/browser checks. Add a frontend test runner and browser automation; lock dependency versions.
- Refactor `main.py` startup into an application factory/lifecycle without schema creation, fixture publication, or sample projects. Move seeds into an explicit idempotent command with versioned manifests.
- Remove mutations from read endpoints, including seed loading and workflow reconciliation. Reconciliation becomes an explicit audited command/job.
- Add liveness/readiness checks and production settings validation. Disable automatic mock fallback in production.
- Remove model-content logging in JSON parse errors; redact secrets, headers, tokens, and document content from operational logs.
- Correct README assertions about validation, startup, and deployment.

**Acceptance:** Application startup and repeated reads change no configuration/data; wrong schema version and missing required production settings prevent readiness; production cannot silently produce mock artifacts; fixtures load only through the explicit mechanism; CI baseline results are recorded.

### Phase 1 — Authenticated client and environment ownership

**Change:**

- Add identity, client, membership, installation, and environment models, typed APIs, and onboarding screens.
- Integrate the HighRadius identity mechanism through an OIDC-compatible identity interface. Validate issuer, audience, signature, expiry, and session revocation requirements. Keep development identity fixtures explicit.
- Derive reviewer and audit identities from authentication. Replace shared-key administrative access with configurator/publisher permissions.
- Add client-scoped functional reviewer, technical reviewer, tester, consultant, and client administrator roles. Keep platform configuration permissions separately governed.
- Scope every request/artifact/version/file/job/audit lookup by authorized ownership. Introduce composite ownership constraints and PostgreSQL RLS as defense in depth using a non-owner application role.
- Set transaction-scoped tenant context for HTTP requests and workers; verify pool reuse does not retain a previous client's context.
- Add searchable, paginated client/request queues with ERP, owner, status, and next-action filters.
- Replace normal hard deletion with archival and an authorized retention/purge process.

**Migration:** Add nullable ownership fields first. Use an explicit reviewed mapping for legacy records. Unmapped records remain quarantined from normal access. Enforce required ownership and constraints only after reconciliation. Never infer client identity from a project name.

**Acceptance:** Client A cannot access Client B through APIs, direct database access, object links, cache keys, or jobs. Consultants cannot publish profiles. Reviewers cannot spoof another identity. Existing history remains preserved. Client onboarding supports multiple installations/environments.

### Phase 2 — Exact-version workflow, review, and backtracking

**Change:**

- Split the current workflow service into transition commands, dependency queries, review commands, and invalidation services.
- Add immutable requirement/context/configuration revisions, an exact artifact-dependency table, review-decision events, and a current-revision pointer with a concurrency version.
- Use atomic conditional writes or locked transitions for generation claims, revision allocation, and reviews. Return a conflict when a submitted revision or dependency changed.
- Capture all exact required upstream revisions when generation starts; recheck them when generation completes and when a reviewer approves.
- Invalidate queued/running descendants through generation ownership tokens and stale markers. A late result is retained as stale evidence and cannot replace current work.
- Preserve historical APPROVED decisions. Record current validity separately rather than rewriting historical approval facts as invalidated.
- Add explicit input-revision and configuration-upgrade commands. Show impact before applying the change. Viewing history does not invalidate anything.
- Separate historical approved lookup from current eligible approved lookup. Release and traceability use the latter.
- Update the review UI to bind content, validation, comments, and actions to one exact revision ID. Cancel/ignore outdated requests; preserve comments after failed submission; disable duplicate writes.

**Acceptance:** Two conflicting reviews produce one successful decision and one conflict. Upstream changes during generation prevent stale approval. Later gates cannot remain actively approved against changed prerequisites. Historical releases and approval events remain intact. The PKB viewer displays the configured body file.

### Phase 3 — Governed ERP registry and frozen configuration manifests

**Change:**

- Normalize logical prompt/package/knowledge identities and immutable versions. Profile manifests bind exact resource-version IDs rather than duplicating ambiguous asset rows.
- Complete DRAFT → REVIEW → PUBLISHED → RETIRED lifecycle controls with authorization, audit events, and version-aware draft operations.
- Implement typed workflow, prompt-variable, output-file, validation-rule, retrieval, template, generation, and capability schemas.
- Implement publication readiness: graph validity and ordering, required stages/prompts, supported variables, installed adapter versions, mandatory packages, asset ingestion, rule validity, and output contracts.
- Preserve independent profile/prompt version numbers. A profile version's published manifest is immutable; an updated prompt requires a new manifest/configuration revision before an existing request uses it.
- Pin organization/client settings and global prompts through an effective request configuration revision. Retiring resources blocks new selection while retaining historical references.
- Move Oracle prompt text and initial assets into explicit profile fixture manifests. Keep deterministic Oracle implementation behavior in the adapter.
- Remove Oracle-shaped defaults and adapter-name branches from generic orchestration. Route validation and traceability through capability interfaces.
- Add native admin pages: ERP Profiles, Prompt Studio, Package Library, Knowledge Hub, Feedback/Guidance, and audit. Use typed forms and an optional advanced configuration view.
- Refresh shared ERP selectors after publication. Import the supplied ERP catalogue as governed records with truthful readiness/capability states; incomplete records remain DRAFT.

**Migration:** Fix prompt identity/global uniqueness, resource bindings, and cloned-asset addressing. Preserve applied migrations and historical IDs through additive corrective migrations. Reconcile fresh-seed and upgraded prompt-stage bindings explicitly.

**Acceptance:** A published profile cannot be modified. Unknown adapters and missing prompts prevent publication with actionable blockers. Same prompt names in different stages work. Cloned-profile lifecycle actions address one exact resource version. An upgraded request uses the new manifest; old runs retain the previous one.

### Phase 4 — Private file storage, ingestion, and requirement clarification

**Change:**

- Implement storage-object metadata independently from package/knowledge/request metadata: client/scope, checksum, size, MIME type, object key, retention, and ingestion state.
- Support multi-file uploads, scanning/quarantine, type verification, bounded archives, and authorized downloads. Use opaque keys and short-lived scoped download access.
- Add immutable document revisions and background extraction for DOCX, PDF, XLSX, text/source assets, and supported archive members. Add OCR for scanned PDFs and explicit review of low-confidence extraction.
- Preserve source pages, sections, tables, and diagram references. Unsupported or failed extraction must be visible and cannot silently become published searchable knowledge.
- Add structured requirements, assumptions, contradictions, acceptance criteria, and clarification questions/answers. Users can answer in the portal or upload replacements.
- Resolve both into a new requirement revision with source evidence. Evaluate business readiness for FDD separately from technical readiness for TDD/package work.
- Add upload, extraction preview, clarification, and requirement-assessment approval screens using Phase 2 review rules.

**Acceptance:** A requirement document can be uploaded, parsed, clarified, versioned, and approved through the UI. Extracted requirements cite their source. Failed OCR cannot masquerade as complete content. Client files never appear in another client's retrieval or downloads.

### Phase 5 — Durable generation, grounded context, and feedback

**Change:**

- Add durable Job, GenerationRun, JobAttempt, OutboxEvent, and effective-provider-request records. Commit the run and outbox event before provider execution.
- Change generation submission to return a job/run identifier. Add progress, cancellation, retry, and reconnect-safe UI state. Use bounded retries, leases, and ownership tokens.
- Introduce ERP context resolver, knowledge/package/feedback retrievers, and one prompt compiler. Compile published global rules, ERP/stage prompts, approved requirements/context/upstream artifacts, relevant guidance, package context, and current task.
- Select one pinned effective revision per resource. Use separate budgets for knowledge, standard packages, and feedback. Mandatory package contracts cannot be displaced by knowledge ranking.
- Apply scope/permission filters before retrieval. Record selected sections, locations, checksums, relevance reasons, exclusions, truncation, and effective configuration.
- Preserve request-change instructions as authorized request-scoped feedback. Reusable client/ERP/global guidance has an explicit approval lifecycle and promotion lineage; no automatic promotion.
- Make all generation adapters consume compiled context. If an adapter transforms the request, the final effective provider payload is the recorded request.
- Capture provider/model identity, model settings, request/response IDs, usage, timestamps, adapter version, parse/validation outcome, failures, cancellations, and stale completions.
- Store sensitive prompt/input snapshots in authorized encrypted provenance storage, not ordinary logs. Mark legacy runs with incomplete actual-provider provenance honestly.
- Keep historical reconstruction separate from fresh regeneration. Provider changes and prompt upgrades are explicit configuration actions.

**Acceptance:** Provider timeout, invalid JSON, cancellation, and stale completion each have a durable run record. Oracle adapters use supplied context and actual settings. Missing configuration blocks generation. Relevant package/knowledge text influences outputs and is visible in provenance. Feedback from unrelated clients/stages is excluded.

### Phase 6 — Complete FDD/TDD templates and technical readiness

**Change:**

- Define ERP-configurable structured FDD/TDD schemas and generic document/mapping consistency contracts.
- Add versioned organization/ERP/client templates and an explicit effective template selection.
- Render internal template copies while preserving supported structure and formatting. Keep source templates and rendered files in authorized private storage.
- Record template version, rendered revision, storage references and exported file checksums. Offer Word/PDF exports containing all configured sections.
- Treat approved structured content plus its rendered revision as the engineering evidence. Import edited documents as a new reviewed revision before they can influence implementation.
- Add schema/interface/dependency evidence and AS-IS package selection to TDD review. Surface unresolved field types, helper signatures, execution targets, and runtime contracts.

**Acceptance:** Requirement approval unlocks FDD; FDD approval unlocks TDD. Changes generate new versions. FDD/TDD are internal template copies with complete exports and no Google Workspace data transfer. Imported edits cannot silently change approved implementation inputs. TDD cannot approve unresolved package-critical contracts.

### Phase 7 — AS-IS package adaptation and trustworthy validation

**Change:**

- Model shared ERP baseline → optional approved client adaptation → request package candidate. Record the selected base version and compatibility requirements.
- Define multi-file package manifests with logical file IDs, relative paths, required outputs, schemas/serializers, language, build toolchain, protected sections, dependencies, and execution target.
- Have the agent adapt a copy of the approved base from the approved TDD. Preserve baseline bytes; produce base-to-result diffs and requirement-to-change mappings.
- Preserve the Oracle SQL/PLSQL adapter behind this interface. Preserve full/delta/selective requirements where configured. Correct the sample supplier relationship as a new documented fixture revision; do not rewrite customer schemas.
- Validate every configured SQL mode and code file. Parse references, signatures, parameters/modes, aliases, relationships, forbidden operations, and placeholders. Avoid keyword presence as proof of implementation.
- Run compilation/build checks in isolated workers with resource limits, narrowly permitted dependencies/network access, and no deployment credentials.
- Record distinct static, compilation, cross-artifact, human-review, and runtime evidence. Required checks that are unavailable report NOT_RUN/BLOCKED, rather than PASS.
- Support configured warning/blocker policies with audited exceptions where permitted. A generic JSON result is not equivalent to a certified native implementation package.

**Acceptance:** The audit's invalid PL/SQL and unsafe delta/selective SQL examples fail applicable checks. Baseline protected sections remain intact. The configured spec/body and all required files are generated, reviewable, and downloadable. Compilation evidence is actual tool output and identifies the exact source checksum.

### Phase 8 — Immutable release candidates and manual sandbox completion

**Change:**

- Add server-side candidate/release eligibility services, artifact-file records, manifest creation, checksum verification, and complete ZIP assembly.
- Candidate eligibility checks current dependency coherence, approvals, required validation, configuration bindings, file contracts, and unresolved blockers.
- Make approved candidates downloadable before sandbox testing. Include all configured SQL/code/configuration/install/recovery/runbook files and FDD/TDD references or exports.
- Add sandbox test plans, manual test evidence uploads, authorized tester sign-off, and exact package/environment linkage.
- A final tested release requires current successful evidence and sign-off. Represent candidate readiness, installation, testing, and completion separately.
- Preserve previously tested release manifests after backtracking. Invalidate their applicability to the new active candidate rather than destroying records.
- Replace frontend approval-count readiness and client-side bundle generation with release APIs.

**Acceptance:** UI users can complete the full requirement-to-tested-download flow through the manual sandbox path. ZIP checksums match the approved files and manifest. Missing required files/validation block candidate creation. Changing package bytes or relevant inputs prevents reuse of an earlier test sign-off.

### Phase 9 — ERP connection onboarding and verified context discovery

**Change:**

- Add Connection and SecretReference models, capability grants, verification jobs, and ConnectionAdapter interfaces.
- Build client onboarding/connection wizard fields from typed adapter configuration: product, edition/version, tenant/company, environment, endpoints, authentication, execution target, and allowed operations.
- Implement supported OAuth authorization/token refresh, certificate, and integration-account mechanisms through secret-store adapters. Scope consent/callback state to the authenticated client and environment.
- Verify actual tenant identity, connection permissions, metadata access, and deployment permissions separately. Display per-environment capability status and missing prerequisites.
- Restrict network destinations and validate redirects/endpoints. The private-runner network policy handles permitted internal endpoints; the public worker must not expose arbitrary internal-network access.
- Discover and freeze supported schemas/API contracts. Conflict with uploaded context creates an explicit resolution task and, if accepted, a new context revision.
- Distinguish source ERP access from database, application, and middleware execution targets. Credentials alone do not make an installation route available.

**Acceptance:** The UI can connect a supported test environment and retrieve versioned context; expired/revoked credentials produce actionable failures. Cross-client credential references are rejected. Data access alone does not enable Install. Requests can use approved uploaded context when discovery is unavailable.

### Phase 10 — Controlled automated deployment and sandbox tests

**Change:**

- Implement independent BuildAdapter, DeploymentAdapter, and TestAdapter interfaces with versioned capability manifests. Metadata identifies supported edition/version/artifact/target combinations and recovery support.
- Add DeploymentPlan, DeploymentJob, DeploymentAttempt, EnvironmentLock, RunnerRegistration, TestRun, and recovery records.
- Produce a concrete installation plan for the approved candidate/environment: changed objects, prerequisites, permissions, expected effects, and available recovery procedure. The authorized user explicitly starts the job.
- Build an outbound authenticated private runner with client/environment identity, expiring signed job authorization, package-hash verification, credential scoping, revocation, and permitted operations.
- Execute vendor-supported APIs/tools or customer pipeline handoffs through deterministic adapters. Reconcile remote status after lost responses before retrying; never assume exactly-once installation.
- Implement explicit partial-failure/unknown-remote-status handling. Rollback and forward recovery are separate declared capabilities.
- Run supported tests against the deployed checksum and environment. Collect vendor/compiler/runtime logs as controlled evidence, with redaction and retention.
- Failures become request-scoped revision feedback. A correction produces a new candidate requiring the relevant approvals and new test evidence.
- Retain the manual route for environments where automated deployment/testing is not certified or authorized.

**Acceptance:** A user deploys an exact approved candidate to a supported sandbox, observes durable status, runs tests, and signs off. Retry/lost-response tests cannot cause unrecognized duplicate installation. Runner revocation blocks new jobs. Unauthorized or checksum-mismatched packages cannot execute.

### Phase 11 — Certify ERP coverage and enterprise operations

**Change:**

- Qualify each required capability against an explicit product edition/version, artifact contract, target type, and authentication mode. Obtain authorized vendor/customer sandbox access and approved standard packages as external prerequisites.
- Add live contract/smoke suites, compatibility records, regression fixtures, and recertification triggers for vendor/adapter changes.
- Scale workers from measured workloads; add per-client quotas, fair scheduling, admission control, storage/retention policies, and capacity budgets.
- Configure backup recovery, availability/failover requirements, restore exercises, operational runbooks, and incident response.
- Update deployment manifests for API/workers, managed PostgreSQL, queue, object storage, secret management, and approved network routes. Restrict deployment/runtime DB roles separately.
- Verify provider and hosting data controls, runtime outbound destinations, dependency phone-home behavior, and production UI network traffic.
- Complete independent security review/penetration testing and the standards evidence register. Resolve release-blocking findings.

**Acceptance:** Advertised capabilities have recorded sandbox evidence. Capacity tests meet approved workload/SLO targets. Restore and recovery objectives are demonstrated. External destinations and privacy controls match the declared policy. Production approval is based on evidence, not a passing mock suite or UI availability.

## 6. ERP adapter qualification backlog

ERP names in this table are product catalogue records and planning coverage, not workflow branches or proof of current implementation. Start qualification with the existing Oracle engineering strategy plus representative native-SaaS and private-network routes; continue until the agreed capability matrix for all 22 families is verified.

| ERP family | Deployment route to qualify | Required distinction |
|---|---|---|
| SAP S/4HANA | Edition-supported extensions/transports or external integration | Public Cloud versus private/on-premises; released interfaces and tooling |
| SAP ECC | Customer ABAP transport pipeline/private runner | Version, development/transport landscape, authorized interfaces |
| SAP Business One | Extension/add-on tooling or external integration | Service Layer access versus extension installation permissions |
| Oracle Fusion Cloud ERP | Supported reports/integrations; explicitly named external DB/middleware target where applicable | Fusion data access versus PL/SQL execution environment |
| Oracle EBS | Customer-supported application/database deployment and services | Release-specific customization/patching standards |
| Oracle NetSuite | SuiteCloud project validation/deployment | Account, role, sandbox identity, object compatibility |
| Dynamics 365 Finance & Operations | Compatible compiled package through customer Microsoft pipeline | Unified versus legacy deployment topology |
| Dynamics AX | Version-specific model/customer tooling | Legacy environment and supported service/runtime contracts |
| Dynamics GP | Customer-side customization/integration tooling | Artifact type and installed runtime |
| Microsoft Business Central | AL app build and supported app-management route | SaaS versus on-premises; tenant/environment permissions |
| Workday Financial Management | Supported tenant integration/app tooling or approved manual handoff | Actual tenant capability/licensing and supported deployment route |
| Sage Intacct | External integration or native customization package | Data API access versus customization management |
| Sage X3 | X3 native development/update tooling or external integration | Version-specific patch/package contracts |
| Sage 300 | SDK/web customization tooling/customer runner | Installed services and artifact/runtime requirements |
| Infor CloudSuite | Underlying product's supported route | Identify actual product, edition, and version |
| Infor M3 | Supported integration/XtendM3 tooling | Governance, activation, and environment restrictions |
| Infor LN | Native extension management or external integration | Extension/interface compatibility |
| Infor SyteLine | Mongoose/IDO-supported tooling | SaaS versus on-premises deployment restrictions |
| Epicor Kinetic | Compatible native solution/tooling or external integration | Version and hosting-dependent installation support |
| Epicor Prophet 21 | Native customization/integration route or manual handoff | Customer-accessible APIs/tooling and supported artifacts |
| Acumatica ERP | Customization import/publish/status | Deployment authentication separately from business-data authentication |
| QuickBooks Online | External integration runtime plus company authorization | Application activation and API testing versus native package installation |

For each row, independently record engineering configuration, connectivity, discovery, build, deployment, tests, and recovery as CONFIGURATION_ONLY, IN_DEVELOPMENT, MANUAL, VERIFIED, or UNSUPPORTED where applicable. Actual environment permissions further restrict an otherwise verified adapter. UI actions follow effective capabilities.

A new ERP can be onboarded without source changes when installed adapters support its required mechanisms. New deterministic execution protocols require a reviewed adapter, isolated from the generic workflow. No fixed `SUPPORTED_ERPS` list is introduced.

## 7. Data migration and compatibility plan

Use additive Alembic migrations and an expand → reviewed backfill → verify → constrain → retire sequence. Allocate revision identifiers from the actual migration head during implementation; do not modify already-applied migrations to rewrite history.

| Migration group | Data changes and verification |
|---|---|
| Ownership | Identities, clients, memberships, installations, environments; explicit mapping of legacy requests; quarantine unmapped records |
| Isolation | Composite ownership constraints, scoped indexes, RLS policies; test non-owner runtime role and pooled transactions |
| Workflow | Input/configuration revisions, exact dependency references, decision events, concurrency tokens; legacy approval evidence labelled accurately |
| Registry | Stable resource identities, stage-aware/global uniqueness, immutable manifests and bindings; cloned assets addressed exactly |
| Storage/intake | Object metadata, document revisions, ingestion jobs, source chunks, clarification answers, template versions |
| Execution | Durable jobs/attempts/outbox, effective provider receipts, connections and secret references |
| Release/sandbox | File manifests, candidates/releases, deployment/test evidence, locks/runners/sign-off |
| Audit/retention | Named actors, append-only event storage, restricted historical deletion, authorized purge behavior |

Checks for every migration: clean PostgreSQL installation; upgrade from a representative copied legacy database; row-count/key/checksum reconciliation; ownership/conflict reports; application compatibility; backup/restore rehearsal. Use one migration actor and a DDL-limited runtime role.

Historical facts that were never recorded cannot be fabricated. Legacy reviewer strings are unverified identities; compiler snapshots are not guaranteed actual provider requests; ambiguous old dependencies remain explicitly incomplete. Preserve those records and require a current review/regeneration before treating them as qualified evidence.

## 8. API and adapter contracts

Contracts below are conceptual and should be expressed as typed Python protocols/models and generated client types:

- `ConnectionAdapter`: verify identity/permissions, list capabilities, discover allowed context, refresh/revoke access where supported.
- `GenerationStrategy`: create an effective request from compiled context, parse output, declare output schema/files.
- `BuildAdapter`: assemble/compile a candidate from approved sources and fixed toolchain inputs.
- `ValidationAdapter`: return check type, outcome, severity, evidence, source checksum, and validator version.
- `DeploymentAdapter`: preflight, plan, deploy, get status, reconcile uncertain outcomes, supported recovery.
- `TestAdapter`: run a versioned test plan, obtain status/results, collect evidence.
- `StorageAdapter`: authorized store/read/export/retention without leaking provider paths.
- `SecretStore`: resolve/rotate/revoke within a permitted operation; never serialize secret values into domain responses.

Long operations return durable identifiers and expose status/cancellation through authorized endpoints. Use stable error envelopes with an error code, safe message, field/configuration blockers, and correlation ID. Mutation requests carry expected revision/state and duplicate-request protection.

## 9. HighRadius UI delivery requirements

Deliver these progressively with their backend phases:

- Fixed shell with bounded content scrolling. Long JSON, SQL, filenames, diffs, and tables cannot expand the application viewport or hide navigation.
- Client/installation/environment search and work queues; avoid one unbounded selector containing 4,500 clients.
- New Integration Request wizard: client/environment → document set → extraction/clarification → context/templates → configuration summary.
- Compact sequential gates reflecting backend eligibility and exact current revisions.
- Complete artifact viewer: document link/export, structured view, configured files, diff, source provenance, validations, authenticated review actions.
- Admin registry with typed forms, lifecycle controls, version comparison, ingestion state, and publication blockers.
- Connection wizard with effective capabilities and missing access/setup instructions.
- Candidate/release view with complete downloads, deployment plans/status, manual/automated test evidence, and tester sign-off.
- Clear failed/loading/stale/permission states. Preserve unsaved comments and drafts after errors.
- Accessible keyboard/focus behavior and screen-reader labels. Browser tests cover the fixed-shell/JSON overflow regressions at representative viewport sizes.

## 10. Privacy, telemetry, and evidence policy

Proposed default: no product analytics, session replay, advertising trackers, third-party crash SDKs, automatic diagnostic uploads, or optional runtime phone-home calls. Host fonts/assets locally where feasible and audit runtime dependencies.

Maintain separately governed records inside the approved hosting boundary:

1. **Engineering evidence:** requirements, artifacts, configuration versions, provider request snapshots, reviews, deployments, and test reports. Encrypted, access-controlled, versioned, and retained under policy.
2. **Audit records:** actor/resource/action/version/time with redacted details, append-only permissions, retention/export controls, and protected archival.
3. **Operational records:** health, queue failures, availability and security events with minimal metadata; no document bodies, credentials, or model response fragments in normal logs.

For the requested deployment, permitted processing destinations are approved AWS services, the approved Bedrock model/API/Region, and explicitly authorized client ERP targets. Disable other AI providers and external document/analytics services. Restrict egress and keep model invocation content logging off. Qualify actual model/API retention controls; do not assume every Bedrock model has identical zero-retention behavior. See [the Bedrock and sandbox plan](product-ui-bedrock-and-oracle-sandbox-plan.md#4-data-boundary-and-bedrock-configuration).

Bedrock processes submitted context within AWS, and approved ERP operations send information to the client ERP vendor. This policy prohibits unauthorized recipients; it does not mean no data leaves an application process. If the contract instead prohibits AWS model processing or all vendor transfer, that conflicts with the requested Bedrock/live-ERP flow and must be resolved before enabling those operations. Do not promise control over an ERP vendor's own operational records.

Acceptance requires a reviewed destination inventory, production browser/network inspection, controlled-worker egress tests, redaction tests, and verified provider settings. Audit stores are not advertised as disabled while retaining them invisibly.

## 11. Verification and acceptance scenarios

### 11.1 Critical invariant suite

- No unauthenticated access to client requirements, artifacts, jobs, files, or review operations.
- No cross-client relationship, retrieval, cache, storage, or credential access.
- No review-author identity supplied by the caller.
- No downstream active approval against a changed upstream revision.
- No late generation replacing current work after invalidation.
- No in-place change to published configuration or approved release bytes.
- No model output or uploaded content grants deployment permission.
- No missing mandatory validation is reported as PASS.
- No candidate download omits configured required files.
- No previous test sign-off satisfies a changed active candidate.
- No read/startup operation seeds, republishes, or reconciles governed state.

### 11.2 Demo ERP UI-only acceptance

Using an authenticated administrator and the actual application UI:

1. Create Demo ERP with a configured workflow and an existing implementation adapter; add no ERP-name branch.
2. Add/publish global/ERP/stage prompts, a multi-file baseline package, knowledge, validation configuration, and output contracts.
3. Publish only after readiness succeeds.
4. Create a client/environment and request; select Demo ERP; upload requirement/context and complete clarification.
5. Generate and approve assessment, FDD, TDD, and adapted package with authorized role assignments.
6. Assert actual effective prompt content, retrieved knowledge/package sections, scope, profile version, file contracts, and provider settings from persisted evidence.
7. Request changes; verify new revision/diff and scoped feedback.
8. Backtrack upstream while downstream generation is running; verify invalidation/stale completion and preserved history.
9. Publish a new prompt/profile manifest through the UI; explicitly upgrade the request and regenerate affected work.
10. Verify the old output and its captured inputs remain available and the new run uses the new version.
11. Download the approved candidate, complete supported sandbox testing or the declared manual evidence path, sign off, and download the final bundle.
12. Confirm unauthorized users and another client's users cannot access or approve the request.

Run deterministic browser/contract tests in CI and a separately authorized live-provider scenario. Real ERP adapter qualification uses actual supported vendor sandboxes; a simulated Demo ERP proves configuration-driven onboarding but does not certify vendor installation.

### 11.3 Oracle regression and migration acceptance

- Verify Oracle prompt/compiler/strategy context matches the actual provider request.
- Verify configured SQL modes, spec/body signatures, helpers, exception behavior, and required outputs.
- Build the package for an explicitly configured execution target; report any unavailable build check as NOT_RUN/BLOCKED.
- Download SQL/spec/body/configured install/recovery/runbook files and verify manifest checksums.
- Exercise legacy upgrade and fresh installation to produce equivalent valid configuration bindings.
- Preserve original template assets and historical engineering records.

### 11.4 Reliability/security qualification

Test provider timeout/429/malformed output, worker crash, queue redelivery, database disconnect, duplicate mutation, stale reviewer, expired credentials, malicious file/archive, injected requirement instructions, unauthorized URL/network destination, lost vendor deployment response, partial installation, revoked runner, storage failure, and restore from backup.

Maintain a measured workload model and approve availability, latency, queue-delay, recovery-time, recovery-point, and retention targets. The count of clients alone is not a sizing specification.

## 12. Phase completion and production release gates

A phase is complete only when:

- Its real UI/API/domain/storage path works with no fabricated status.
- New and applicable existing tests pass; backend typing/lint and frontend typing/lint/build pass under the phase's ratcheted baseline.
- PostgreSQL migration clean-install/upgrade checks pass.
- Workflow and ownership invariants remain intact.
- Required administrative actions and failures have safe audit evidence.
- README, configuration examples, and operating instructions match demonstrated behavior.
- External dependencies are identified explicitly; unverified capability actions remain unavailable or labelled manual.

Production release additionally requires demonstrated client isolation, independent security review, resolution of critical/high findings under the approved policy, backup/restore and interrupted-deployment recovery evidence, signed release provenance/checksums, validated advertised adapter combinations, and verified privacy controls. Approve exception policy explicitly rather than silently waiving blockers.

Suggested milestones:

| Milestone | Evidence |
|---|---|
| M1: Protected existing engineering workflow | Phases 0–3; authenticated client access, correct approvals/backtracking, governed usable profiles |
| M2: Complete engineering-to-tested-download flow | Phases 4–8; document intake, templates, baseline adaptation, trusted checks, full candidate/final bundles, manual sandbox evidence |
| M3: Verified sandbox automation | Phases 9–10; connection discovery, controlled workers/runners, real supported deployments and tests |
| M4: Qualified enterprise coverage | Phase 11; agreed capabilities for all catalogue families, security/privacy and operational evidence |

These milestones organize delivery and do not redefine the final requirement. Do not declare the overall implementation complete at database/API scaffolding, mock generation, or a single working ERP.

## 13. First implementation work packages

The first reviewable changes should be small and ordered:

1. Baseline CI/testing configuration and defect register; no changes to approval semantics yet.
2. Explicit fixture command, read-only startup/query behavior, readiness, production provider validation, and redacted errors.
3. Client/installation/environment expand migration, typed models, identity integration, authorized onboarding and scoped request APIs.
4. Reviewed legacy ownership mapping, isolation constraints/RLS, audit actor migration, and client access tests.
5. Exact dependency revision records, atomic review/generation transitions, in-flight invalidation, and review UI revision binding.
6. Registry identity/manifests and publication readiness with UI editors and corrective migration tests.

For each work package, record changed files, design decisions, migration implications, test evidence, rollout/rollback compatibility, and remaining limitations. Continue through the later phases after their prerequisites pass. Do not deploy to external hosting, call customer ERP installations, or enable production execution as a side effect of implementing local code.
