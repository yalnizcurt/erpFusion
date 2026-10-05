# Product UI, Bedrock and ERP sandbox implementation plan

Date: 2 October 2026  
Status: Implementation in progress. The local Home/Studio, durable engineering, connection and package-evidence slices are implemented; live vendor qualification and cloud deployment gates remain pending.  
Priority: Make the actual product match the approved JavaScript prototype and demonstrate a real Oracle Fusion sandbox extraction, with trustworthy test evidence.

## 1. Decisions for product review

1. Use `mock/` as the visual specification. Implement its design in the existing authenticated React application and reuse the FastAPI/PostgreSQL backend.
2. Keep Home as the project table. Requirements, engineering, reviews, package files, sandbox operations and history belong in a persistent project Studio.
3. Use Amazon Bedrock as the production model provider. Permit client data only in approved AWS services and the client's explicitly authorized ERP targets. Disable other AI providers and external document services in this deployment.
4. Onboard all 22 requested ERP families as governed registry data. Publish usable engineering configurations only after their prompts, assets, output contracts and rules are ready. Track actual connectivity, installation and testing support independently.
5. Separate **source ERP** from **execution target**. Oracle Fusion Cloud is not an endpoint for installing arbitrary Oracle database packages. Preserve PL/SQL generation for an explicitly configured external Oracle database or another qualified database target.
6. Use a Publisher report/data-model extraction as the first Fusion demo. Qualify native import on the actual tenant before promising automatic installation; otherwise use an assisted native import followed by automated report execution and tests.
7. Add **Ping / Check connection**, with separate reachability, authentication and capability results. A green network check never grants deployment permission.
8. Require approval of the exact package and installation plan before sandbox writes, and successful tests plus human sign-off before a final tested release.

These decisions supplement [the production implementation plan](production-implementation-plan.md) and [the Home and Engineering Studio plan](home-and-engineering-studio-plan.md). This document takes precedence for the mock design, Bedrock-only deployment, external data destinations and Fusion demo target.

## 2. Current implementation: what must change

| Inspected area | Current boundary | Delivery requirement |
|---|---|---|
| `mock/index.html`, `styles.css`, `app.mjs`, `model.mjs` | Approved visual prototype; sample state in browser storage; simulated generation and sandbox outcomes | Transfer the layout and interactions; replace sample state and results with authorized server records |
| `frontend/src/App.jsx` and existing components | Real product, with existing identity/client interfaces and workflow views | Adopt the mock's Home/Studio design, stable project routing and server-derived eligibility |
| `backend/app/models/identity.py`, client APIs | Client-owned installations/environments and authorization foundation | Add typed connection configuration, secret references, verification and test/deployment records |
| `backend/app/services/llm/factory.py`, `config.py` | Groq implementation; Bedrock explicitly not implemented | Implement and qualify Bedrock; production startup must reject unauthorized providers |
| `services/codegen/strategies.py`, `services/ai/` | Configured generation strategies exist; Oracle PL/SQL assumptions remain in the Oracle path | Give Fusion a report/API execution contract; retain the database package strategy for compatible targets |
| `services/ai/deployment_generator.py` | Generates installation instructions, not remote installation | Use deterministic, qualified execution code after an approved deployment plan |
| `frontend/src/components/DeploymentPackageView.jsx` | Browser package/readiness handling | Server-owned immutable candidates, manifests, downloads and test/release eligibility |
| Workflow/generation APIs | Current synchronous execution cannot establish the required durable resume and invalidation guarantees | Commit durable jobs and exact revision bindings before work; reject stale completions |
| AWS deployment foundation | Initial infrastructure does not establish the new provider, worker or ERP capabilities | Update infrastructure for API/workers, private data services, Bedrock and controlled ERP egress |

Do not describe the JavaScript mock's successful simulation as real compilation, installation, security testing or ERP qualification.

## 3. Production interface matching the prototype

### Application shell and navigation

- Match the prototype's HighRadius branding, blue sidebar, header, footer, spacing, type, colors, cards, table and Studio layout.
- Keep header, sidebar and bottom bar fixed. Use bounded content scrolling; long JSON, SQL, file paths, diffs and tables cannot expand the viewport or hide navigation.
- Reuse existing React components and local CSS where possible. Bundle icons/fonts/assets locally; add a UI dependency only for a concrete unmet requirement.
- Preserve keyboard navigation, visible focus, form labels, error announcements and usable smaller layouts.
- Show production identities and truthful loading, empty, blocked, error and historical states in the same design. Remove sample success claims and simulated metrics.

### Home

The table contains client, project, ERP/profile version, Standard/Custom, status, due date, last updated, authorized package link and Open Studio. Put **Create New** above the table. Use authorized server pagination/search/sorting, including stable ordering and saved filters; never fetch every project for 4,500 clients into the browser.

Download links distinguish an approved **candidate** from a **tested release**. Before eligibility, show the actual missing approval/check instead of an enabled empty download.

### Studio

Use `/projects/{id}/studio` with stage/tab/revision identifiers. The sidebar resumes the selected authorized project or opens a selector. Refreshing or reopening a link loads the saved project directly, independently of Home's current page.

The visible flow is Requirements → FDD → TDD → Package → Sandbox → Release. A published profile may add required engineering reviews; show SQL/spec/body or other configured files within the appropriate package workspace rather than assuming every ERP uses PL/SQL gates.

- Requirements has an obvious PDF/DOCX upload area, upload/extraction status, original preview, extracted content, source references and clarification questions. Add bounded parsing, scan handling and a reviewed OCR path when required.
- An authorized user approves the exact requirement assessment before FDD generation. FDD/TDD corrections create new revisions with differences and reviewer feedback.
- Package has baseline selection/version, changed files, protected sections, validations, provenance and complete downloads.
- Sandbox has the selected environment, Ping, connection capabilities, approved deployment plan, execution/test status, evidence and sign-off.
- History preserves input, artifact, decision, job, package, installation and test revisions. Browsing old content is read-only navigation. Revising earlier work previews and invalidates affected active descendants atomically.
- Save drafts/comments on the server. Do not store real requirements, access tokens or ERP credentials in the prototype's local-storage model.
- Keep committed jobs running across navigation. Show progress from durable server state. A changed prerequisite makes an old in-flight completion stale; it cannot restore active downstream approval.

## 4. Data boundary and Bedrock configuration

“No data exposed to external sources” will mean **no unauthorized recipients**. Bedrock processes selected content within AWS; calling the client's ERP necessarily sends the approved operation to that vendor. This is not a promise that content never leaves an application process or that vendor infrastructure belongs to our AWS account.

### Allowed destinations

- The approved AWS account/Region: authenticated application hosting, PostgreSQL, private S3, Secrets Manager, KMS, identity and Bedrock.
- Each client's approved, allowlisted ERP endpoints, only for explicitly permitted operations.
- A registered client runner for private ERP networks when an actual adapter requires it.

Staging/production make no runtime calls to Groq, OpenAI, Lovable, Google Docs, external CDNs, product analytics, session replay or third-party crash services. Local synthetic testing currently uses Groq by the user's explicit instruction. Maintain internal security/audit records with minimal metadata; do not turn off security auditing to satisfy “no telemetry.” Vendor knowledge acquisition is an administrative action; generation does not browse public websites with customer context.

### Bedrock slice

1. Implement the existing provider contract with the AWS SDK and an approved supported Bedrock API, initially Converse where the chosen model meets the output/privacy contract. Reuse the existing prompt compiler and JSON validation.
2. Use workload IAM roles; never copy locally logged-in AWS credentials into containers or configuration.
3. Pin an approved model identifier, API, Region, generation parameters and token budget. Record effective request/provenance and provider receipts in encrypted engineering storage.
4. Connect through a Bedrock runtime VPC endpoint with restricted IAM/endpoint policies. AWS documents PrivateLink connectivity without public internet routing for that connection. [AWS PrivateLink](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)
5. Approve the chosen model/API's retention behavior. Where applicable, enforce the account's `none` retention setting and prevent unauthorized changes. Block models that require incompatible retention; `store: false` alone is not a sufficient guarantee. [AWS retention policy](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html)
6. Keep content-bearing model invocation logging disabled. Record job/model/timing/error metadata in application operations logs, with source snapshots confined to authorized encrypted provenance storage. [Invocation logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)
7. Use approved regional inference by default. Cross-region/global inference profiles require an explicit residency decision; fail clearly if the selected model cannot satisfy it. [Cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html)
8. Retrieve only relevant, authorized requirement/schema/knowledge/package/feedback sections. ERP passwords, tokens, private keys and secret values never enter model context.
9. Treat uploads and model output as untrusted data. The model may propose structured changes; it cannot select arbitrary network destinations, execute scripts, fetch secrets or approve deployment.

Bedrock setup includes model access, IAM, private DNS/endpoints, timeouts, bounded retries for generation, quotas and concurrency limits. Missing model access is a visible blocker, never a switch to another provider or mock response.

### Proposed AWS topology

```text
Browser → CloudFront → private S3 application assets
                    → private ALB → FastAPI on ECS Fargate
                                       → private PostgreSQL / S3
                                       → committed jobs + outbox → SQS
                                                                    → Fargate workers
                                                                        → Bedrock via VPC endpoint
                                                                        → approved ERP connection
                                                                        → operation-scoped secrets
```

Reuse the existing application/container and artifact-storage work. Use one queue/worker mechanism, not a new workflow platform alongside it. Database job state and exact revision checks remain authoritative; queue delivery is at least once and workers must tolerate duplicates. Deploy code/build validation without ERP credentials and with restricted network/resource access; a separately permissioned execution worker performs approved sandbox operations.

CloudFront supports a private ALB VPC origin. Cache only static application assets; disable shared caching for authenticated APIs and client content. Review the CDN/data-residency policy before enabling client downloads through it. [CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)

Use private service endpoints for supported AWS dependencies. ERP calls use controlled outbound routing with explicit destinations, stable egress identity when the tenant requires allowlisting, and no arbitrary internet access from generation/build workers. Restrict task roles independently for API, generation, secret-onboarding and ERP execution. Public site availability remains subject to the existing account-verification blocker; this is a proposed topology, not an already deployed system.

## 5. Connections and the Ping button

### Client environment setup

Add environment-specific connection fields to Clients → Installation → Environment, and link them from Studio → Sandbox:

- Product/profile, edition/release, tenant/company identity and SANDBOX/TEST/PRODUCTION classification.
- Source endpoint and separate implementation execution target where applicable.
- Adapter-supported authentication: integration account, OAuth, certificate, token or other qualified mechanism.
- Secret reference/version, network route, approved hosts and permitted operations.
- Discovery/context snapshot, test-data scope and independent capability evidence.

Store credential material only through a dedicated authenticated secret-onboarding operation into Secrets Manager. Application rows contain references, never password JSON. The UI shows “configured,” expiry/rotation state and a replace action; it cannot read back passwords. Scope retrieval to client, installation, environment and the required operation. Read/report execution and package-management access may use different identities.

### Ping behavior

The button runs a **server-side, non-mutating HTTPS/API connection check**, not browser requests or ICMP. It creates a verification record for the exact connection configuration and secret version.

| Check | What the UI displays |
|---|---|
| DNS/network/TLS | Reachable, timeout, DNS failure, invalid certificate or blocked destination |
| Authentication | Authenticated, rejected credentials, expired token or unsupported authentication |
| Tenant identity | Confirmed expected tenant/environment, mismatch, or verification unavailable |
| Read/discovery permissions | Available API/schema/catalog access and missing permissions |
| Report/implementation capabilities | Verified execution capability; import/deployment remains unverified unless separately qualified |

Display last checked, latency, safe diagnostic code and next action. A 401 can mean reachable but unauthenticated. A login-page redirect is not a successful API login. Unsupported discovery is “Not verified,” not PASS. Connection checks do not refresh project Last updated.

Use bounded operation timeouts and per-user/environment rate limits. Give evidence a documented lifetime; configuration/secret changes invalidate it immediately. Recheck required access before deployment, even when an older Ping was green.

### Network and authorization safeguards

- Authorize the client/environment before probing or looking up secrets. Never accept an arbitrary URL/secret reference from a job caller.
- Validate schemes, hosts, ports, DNS resolution and redirects; never forward credentials to another origin. Reject metadata/loopback/internal destinations from public workers.
- Authorize private ERP destinations through a separately constrained runner/network policy. Do not expose a general internal-network probing endpoint.
- Verify TLS certificates and validate parsed SOAP/XML safely. Bound response bodies and redact errors; log no authorization headers or raw vendor responses.
- Audit checks and administrative changes. Ping grants no write permission and never creates ERP business records or imports code.

## 6. Can URL, username and password deploy a package?

**Not as a general rule, and not for installing PL/SQL into Oracle Fusion Cloud.** Connection details must match a supported operation, authentication policy, permissions and execution target.

| Requested operation | Are a Fusion URL and username/password sufficient? |
|---|---|
| Check an API connection | Sometimes, when that API accepts the configured authentication and the account has access |
| Run an existing Publisher report | Potentially, with the supported service/policy and report/data permissions |
| Import a new/changed report | Only after the actual tenant's supported import service or native import procedure and permissions have been qualified |
| Install `.pks` / `.pkb` inside Fusion's managed database | No; this is not a supported deployment target for this portal |
| Compile/run PL/SQL on a separate Oracle database | Requires that database's own endpoint/service, network access, credentials/certificates and approved grants |
| Deploy to another ERP | Product/edition-specific; may require OAuth, SDK tooling, transports, a customer pipeline or a private runner |

Oracle documents report-based SQL extraction through Publisher rather than database queries through the ERP Cloud Adapter. This supports the report route; it does not establish a customer database-package installation API. [ERP Cloud Adapter capabilities](https://docs.oracle.com/en/cloud/paas/integration-cloud/erp-adapter/oracle-erp-cloud-adapter-capabilities.html)

The connection wizard asks for the minimum fields required by the selected capability. A user can have a working data connection while Install remains unavailable with a specific prerequisite list.

## 7. Oracle Fusion sandbox demo: concrete execution plan

### 7.1 Demo scope and early qualification

Use a real **non-production Fusion tenant/pod** with synthetic invoice data. An in-application Fusion configuration “sandbox” is not assumed to be a separate environment for running integration tests.

The demonstration requirement is an invoice-header/line outbound extract with reviewed date/business-unit filters and a defined CSV contract. Confirm actual schemas, relationships, statuses and authorized data scope from the client's approved context; do not invent joins, standard helper signatures or delta semantics.

Before investing in package generation, qualify on the supplied tenant:

1. Confirm tenant identity/release and a successful authenticated read probe.
2. Execute a small existing approved Publisher report using the documented service/policy.
3. Establish authorized report/data-model authoring and the permitted Custom folder/ACL.
4. Export an approved AS-IS report/data-model through the actual tenant tooling and identify its native archive format.
5. Determine whether supported programmatic import is available and permitted. Generic Publisher CatalogService documentation is not proof that a particular Fusion tenant exposes that operation.
6. Import and execute a disposable baseline copy using the qualified route; record exact limitations and cleanup behavior.

The protected `ExternalReportWSSService` is a documented report execution route. Oracle distinguishes it from the public ReportService authentication shape and recommends synchronous calls for small, short-running reports; larger jobs need a qualified asynchronous route. [Fusion Publisher report services](https://docs.oracle.com/en/cloud/paas/integration-cloud/soap-adapter/call-oracle-fusion-applications-business-intelligence-publisher-report-services.html)

### 7.2 Package construction

Register a new reviewed Fusion profile version with a **Publisher extraction** strategy and a report execution target. Preserve old profile versions and their history; do not silently replace PL/SQL in pinned projects. Explicitly upgrade a project and invalidate affected work when changing its target.

The baseline contains the approved SQL/data model, report definition/layout as applicable, parameters, helper contracts, output schema, native exported assets and installation/test instructions.

The agent proposes bounded changes from approved TDD to a copy of that baseline. Deterministic code validates and applies the structured changes, preserving protected sections. Native packaging must use a proven serializer/tool or vendor tooling for the actual format. An arbitrary ZIP renamed to a catalog extension is not an importable Fusion package. If native serialization cannot be reproduced safely, retain an assisted native editing/export step and verify the resulting export before approval.

The downloadable candidate contains:

- Generated SQL and readable configured source files.
- Importable report/data-model assets only in the tenant-qualified native format.
- Parameters/output contract and baseline-to-candidate differences.
- Installation, execution, test and cleanup/recovery instructions.
- Immutable manifest: client/project, profile/prompts/assets/feedback, approved input/artifact revisions, strategy/build version, execution target, file hashes and test-plan version.

Catalog formats depend on the actual product/tooling. Oracle documents both native catalog archive workflows and Publisher object archives in different products; qualify the exported artifact rather than assuming an extension. [Fusion catalog archive workflow](https://docs.oracle.com/en/cloud/saas/sales/facaa/archive-and-move-analytics.html), [Publisher object archives](https://docs.oracle.com/en/middleware/bi/analytics-server/user-publisher-oas/download-and-upload-catalog-objects.html)

### 7.3 Installation and execution

**Automatic path:** enable Install only for a qualified tenant/product/release/authentication/artifact combination. The deployment plan names all changed objects and permissions. Import into a versioned approved Custom path, verify resulting objects and record remote identifiers/content evidence before executing the report.

**Assisted path:** provide the exact approved download and native import instructions; an authorized user imports it. Capture the exported/resulting object evidence and verify it against the candidate before running automated execution tests. Label this “Assisted installation”; do not advertise one-click deployment. If remote bytes cannot be verified, report the assurance gap and do not claim an exact-package automatic test result.

Both paths use the same candidate/test lineage. Never overwrite seeded reports or another project's files. Prefer versioned new objects over replacement. Do not copy broad ACLs, grant BI Administrator by default or delete unrelated catalog folders.

Execute with fixed approved test parameters, parse the response with size limits, and compare outputs to independent expected fixtures. The initial demo uses bounded synchronous execution. ESS/UCM or another larger-output route is a separate qualified capability; exceeding synchronous limits blocks or selects that route, never truncates output silently.

### 7.4 Data security and PL/SQL boundaries

Report execution permissions, catalog permissions and row/data security are separate. Do not assume a raw-table query inherits the operator's business-unit restrictions. Approve secured views/predicates and authorized scope, and test excluded business units. Oracle warns that direct-table Publisher SQL can bypass application data security. [Report security](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fassc/overview-of-security-for-oracle-fusion-cloud-scm-reports.html)

If the demo must specifically include `.pks`/`.pkb`, add an explicitly named external Oracle database sandbox:

```text
Fusion Publisher/API extract → approved test payload
  → external Oracle database package → output assertions
```

Configure that database's independent connection, service identity, grants and dependencies. Compile the exact spec/body, inspect actual compiler errors, then run package tests on that database. Label evidence “External Oracle database PL/SQL test,” with Fusion extraction evidence separately. Do not claim the package was installed in Fusion.

## 8. Durable sandbox execution and release gates

Extend the existing domain with the smallest records needed for real operations: connection/secret references, verification snapshots, deployment plan/job/attempt, environment operation lock, test plan/run/case evidence and tester sign-off. Reuse existing project, artifact, review, storage and audit entities.

- Authorize and commit a job for an exact approved candidate hash, environment/configuration version and permitted operation before execution. Process it outside the HTTP request/transaction.
- Worker credentials come from the operation-scoped secret reference. The deterministic adapter executes only supported vendor operations; model-generated shell or SQL is never automatically treated as an installation command.
- Prevent conflicting deployments to the same target. Use remote identifiers/versioned paths and reconcile after timeouts before retrying writes; represent unknown or partial remote status honestly.
- Approval, job claim and dependency checks use atomic concurrency control. Worker restart, duplicate delivery or stale reviewer cannot bypass a gate.
- Backtracking invalidates applicability of old deployments/tests to the new active candidate; it does not erase remote changes or historical evidence. Show any required cleanup/recovery task.
- Recovery is a declared capability. Versioned Custom objects may support deactivation/removal or restoration of an approved prior object; do not promise universal transactional rollback.
- A tested release requires current successful mandatory cases and authenticated tester sign-off. Retain approved candidate and historical release downloads under client permissions.

## 9. Complete Oracle sandbox test configuration

“Configured completely” requires a real tenant, authorized identities, approved baseline and test fixtures. Application records or a green login alone cannot meet it.

| Area | Configuration and required evidence |
|---|---|
| Environment | Confirmed non-production tenant/release, allowed host/route, Custom folder, owners, permitted operations and cleanup policy |
| Credentials | Dedicated integration identity, actual SOAP/REST policy, least privilege, secret storage/rotation; missing author/import access visible |
| Baseline | Client-approved native export, source/output contracts, compatibility and protection rules |
| Test data | Authorized synthetic fixtures, independently expected rows/values, permitted business-unit scope and reset procedure |
| Connectivity | Valid TLS, authenticated API/report operation, denied/expired credentials and wrong-tenant negative tests |
| SQL/report | Parameter binding/types, query restrictions, aliases, relationships, null/empty output, date boundaries, currency/precision and CSV escaping |
| Security | Excluded business units/PII, cross-client access denial, forbidden SQL/operations, malicious prompt/file handling and secret redaction |
| Runtime | Exact candidate installed or verified assisted import, real report response, row/value assertions, bounded size/duration, safe transient failure handling |
| Delta mode | If required: independently specified watermark storage, update window, overlap/deduplication and late-arrival tests; do not claim incremental behavior from a date filter alone |
| Reliability | Worker restart, duplicate job, unknown remote result, configuration/secret rotation, changed prerequisite and stale completion |
| Release | Coherent approvals, all required cases passed, exact environment/candidate lineage, tester sign-off and complete hash-verified ZIP |

Each case records PASSED, FAILED, BLOCKED or NOT_RUN, actual observations, expected results, timestamps and evidence references. AI may summarize failures; it cannot issue a substitute PASS or sign-off. Use minimal result samples and access-controlled retention, not production invoice dumps in logs or prompts.

The demo must also show: request a TDD correction → downstream active package/test/release becomes ineligible → generate/approve a new candidate → rerun sandbox tests → retain the previous release/history unchanged.

## 10. Configure all 22 ERP families

Use an explicit, idempotent administrative import/seed command and the same governed registry services as the UI. No startup seeding and no `if erp == ...` workflow branches. Include the user's product names/aliases; edition/version and execution target belong to configuration.

For every family, track independent engineering, connection, discovery, build, install, runtime-test and recovery capabilities, with states such as Configuration only, In development, Assisted/manual, Verified or Unsupported. Profile lifecycle and adapter capability status are separate. Publish only approved, complete engineering manifests; install remains disabled without a qualified target and permissions.

The following are **routes to investigate and qualify**, not claims that those adapters or vendor sandboxes already exist:

| ERP family | Candidate implementation/installation route | Sandbox qualification needed |
|---|---|---|
| SAP S/4HANA | Edition-approved extensions/transports or external integration | Separate Public Cloud from private/on-premises; released interfaces and permitted tooling |
| SAP ECC | Customer ABAP transport pipeline/private runner | Actual version, development/test landscape, transport permissions and rollback procedure |
| SAP Business One | Supported add-on/extension tooling or external integration | API access separately from add-on installation; actual server/company database |
| Oracle Fusion Cloud ERP | Publisher report/data model; supported API/integration; separate database target if needed | First priority: real non-production pod, native import route and report output assertions |
| Oracle E-Business Suite (EBS) | Customer-approved application/database customization deployment | Release-specific patch/customization standards, grants and private runner |
| Oracle NetSuite | SuiteCloud project/tooling or external integration | Sandbox account/roles, supported authentication, object compatibility and deployment proof |
| Microsoft Dynamics 365 Finance & Operations | Compatible package through the customer's Microsoft deployment pipeline | Current deployment topology, build environment and actual test tenant permissions |
| Microsoft Dynamics AX | Version-specific model/package/customer tooling | Installed release and private development/test infrastructure |
| Microsoft Dynamics GP | Customer customization/integration tooling | Installed runtime, application/company permissions and supported package type |
| Microsoft Business Central | AL extension and supported app-management route | SaaS/on-premises distinction, environment, toolchain and installation permissions |
| Workday Financial Management | Authorized tenant integration tooling or approved handoff | Tenant/licensing, supported integration type and execution permissions |
| Sage Intacct | External integration or qualified native customization | Test company, authorized API access and separately established customization route |
| Sage X3 | Version-specific native package/update tooling or external integration | Development/test folders, exact package format and installation permissions |
| Sage 300 | Customer SDK/web customization or external integration | Installed services, runtime, test company and private connectivity |
| Infor CloudSuite | Underlying product's qualified route | Identify the actual CloudSuite product; avoid claiming a single universal adapter |
| Infor M3 | Supported integration/extension tooling | Exact environment/version, approved extension lifecycle and test access |
| Infor LN | Supported extension management or external integration | Extension compatibility, environment and management permissions |
| Infor Syteline (SyteLine) | Supported Mongoose/IDO tooling or integration | Hosting/edition restrictions and actual management interface |
| Epicor Kinetic | Supported native solution/tooling or external integration | Hosting/version-specific package format and installation procedure |
| Epicor Prophet 21 | Supported customization/integration tooling or handoff | Actual APIs/runtime, authorized test system and package mechanism |
| Acumatica ERP | Qualified customization import/publish or external integration | Business API access separately from package publication rights |
| QuickBooks Online | Authorized external application runtime and API integration | Test company/OAuth and integration behavior; no arbitrary native database-package installation |

Each profile needs its own approved prompts, documentation/examples, baseline assets, output contracts, validation and feedback scopes. Do not substitute Oracle prompts or fabricate vendor standard packages. A profile can reuse an existing supported protocol strategy through configuration; a genuinely new native protocol needs an isolated deterministic adapter implementation.

Obtain real vendor/customer sandboxes and licenses for live qualification. Fixtures/emulators can exercise failure handling in CI but cannot certify live installation. Complete coverage means each requested capability has evidence or an explicit unsupported/manual decision for the chosen edition; it does not mean identical functionality for every ERP.

## 11. Implementation order and phase gates

Deliver each slice through backend, UI, persistence and checks before moving on. Preserve the existing ownership/RLS work and local changes; use additive migrations and explicit backfills.

| Slice | Deliverable | Exit gate |
|---|---|---|
| 0 — Qualification | Confirm Fusion target/auth/native assets/import route; approve AWS Region/model/data policy | Baseline report runs on the real pod; install route and Bedrock access/privacy limitations documented |
| 1 — Real Home/Studio | Transfer mock design; project summaries/routes, document intake and server drafts | Matching fixed shell; visible upload; authorized create/resume; bounded JSON at desktop/smaller widths |
| 2 — Durable engineering + Bedrock | Exact input/dependency revisions, committed jobs, real provider, FDD/TDD correction/review | Real generation survives navigation/restart; source provenance visible; stale completions and unauthorized providers rejected |
| 3 — Connections/Ping | Secret onboarding, endpoint policies, capability checks and diagnostics | Actual Fusion checks; wrong credential/tenant/TLS/SSRF/cross-client tests; no write from Ping |
| 4 — Fusion package | Reviewed new profile, approved baseline adaptation, deterministic native build or declared assisted export | Reviewable changed files; real native asset qualification; approved immutable candidate download |
| 5 — Fusion sandbox/release | Supported automatic or verified assisted import; real execution, assertions, corrections and sign-off | Complete live requirement-to-tested-download demo; historical release retained after backtracking |
| 6 — ERP catalogue | All 22 governed records/configuration work queues and capability status | No hidden Oracle fallback; each published profile passes readiness; UI-only Demo ERP onboarding passes |
| 7 — Remaining ERP qualification | Obtain approved assets/sandboxes, implement only required protocol adapters, certify edition-specific routes | Each advertised operation has live evidence; unsupported/manual cases are visible and safely gated |
| 8 — Cloud/operational readiness | Update API/worker deployment, private services, restricted egress, recovery and capacity controls | Migrations/build/type checks/security isolation pass; backup restore and deployment recovery demonstrated |

Catalogue data preparation can run alongside the first slices, but publishing empty profiles does not count as engineering support. Fusion qualification precedes assumptions about native artifact generation. The existing production plan's workflow, registry, ingestion and release requirements remain prerequisites; a visual port alone does not satisfy these gates.

Missing vendor access does not stop independent UI, workflow, provider or connection-security implementation. Use clearly identified fixtures for that work while live qualification remains pending; do not declare the Fusion sandbox demo complete until its live exit gates pass.

At each executable slice run the relevant unit/integration tests, migration checks, frontend type checks/build and browser scenarios. Use real PostgreSQL to certify isolation/concurrency. Separate deterministic CI fixtures from explicitly authorized live Bedrock and vendor sandbox tests. Inspect browser/worker egress and logs for content leakage.

### Implementation evidence — 2 October 2026

| Slice | Current evidence | Remaining exit gate |
|---|---|---|
| 0 | AWS model availability checked; Nova Pro is `NOT_AUTHORIZED` in `us-east-1`. No invocation logging configuration was returned at check time. | Real Fusion tenant/native baseline and Bedrock model access/privacy qualification |
| 1 | Real Home/Studio UI, fixed shell, server search/filter/page/sort, due/type fields, upload/extraction, private originals, draft save and unsaved-navigation protection | Broader accessibility review and production identity verification |
| 2 | Version-bound committed jobs, independent worker, scoped relevant corrections, source metadata, stale/duplicate/recovery regression checks. Actual UI intake and four real Groq assessment revisions preserved correction history. A reviewed test-only assessment approval unlocked only FDD; real FDD completed and remains pending review, with later gates locked. | Live Bedrock, cloud queue/outbox and real PostgreSQL concurrency evidence |
| 3 | Environment connection UI, scoped write-only Secrets Manager credentials, HTTPS/host/DNS restrictions, Ping with separate capability states; deterministic connection-security tests | Real tenant authentication/identity/permissions and network qualification |
| 4 | Immutable complete source bundles and exact per-file downloads, approval/validation/input binding checks | An approved native Publisher baseline and qualified adaptation/build/import route; the compatibility PL/SQL profile is not a Fusion SaaS installer |
| 5 | Assisted evidence and authenticated sign-off, independent expected-result checks, immutable releases and historical downloads | Real native installation and report execution/output assertions. Assisted evidence explicitly does not verify remote bytes or automatic import |
| 6 | Explicit audited catalogue manifest/importer covers all 22 requested families as drafts; legacy profiles and published versions are preserved | Approved intelligence assets and publication per family; a complete real-stack UI-only onboarding demonstration |
| 7 | Unsupported/unqualified capabilities are recorded; no fabricated vendor package or credentials | Edition-specific live adapters, baselines and sandbox evidence |
| 8 | Production guards for Bedrock/OIDC/private storage, scoped PostgreSQL policies, additive migration chain and CI checks | Updated private worker infrastructure, queue delivery, controlled egress, real PostgreSQL certification and recovery/load qualification |

The user explicitly selected Groq for current local testing and deferred Bedrock invocation. This exception authorizes the synthetic local tests; staging/production retain the Bedrock-only guard. Provider credentials are not included in source, receipts or this document. Historical provider receipts are filtered to metadata so API/UI output cannot expose provider reasoning.

The development upload scanner is not configured and the UI labels that fact. Production/staging uploads and downloads require a `CLEAN` local scan. Bounded PDF/DOCX parsing does not claim OCR support. Local SQLite migration/backfill/round-trip checks pass; PostgreSQL checks require the dedicated test service and are explicitly skipped when absent. See [local verification](architecture/local-verification.md) for the reproducible checks and limitations.

## 12. Inputs required to execute the live demo

- Authorized Fusion non-production tenant URL/identity/release and an ERP administrator contact.
- Dedicated account/authentication setup with report execution and, separately, any approved author/import permissions. Enter secrets through the secure onboarding UI/store, not chat or source files.
- An approved AS-IS Publisher report/data model exported by the actual tenant's tools, plus documentation, output contract and permitted Custom folder.
- Synthetic invoice fixtures, permitted business-unit scope, expected output and reset/cleanup authorization.
- AWS account/Region, approved Bedrock model/API and access, retention/residency policy, and deployment workload roles.
- Network allowlisting/private route where required and agreed evidence retention.
- For PL/SQL specifically: a separate authorized Oracle database sandbox and approved package dependencies/grants.

These are execution prerequisites, not assumptions to fill with invented URLs, credentials or packages. CloudFront account verification is a separate existing public-site blocker; it does not establish ERP or Bedrock readiness.

## 13. Definition of done

- The authenticated product matches the mock's visual design and fixed-shell behavior.
- A user creates a project, uploads a real requirement document, completes clarifications and follows sequential exact-revision approval gates.
- Bedrock uses approved bounded context and recorded configuration; no unauthorized external data destination or content-bearing operational logging is present.
- All 22 ERP families are represented by governed configuration, with honest independent capability status and no ERP-name workflow branches.
- Ping reports a real environment's reachability/authentication/permissions without writing ERP data.
- The Fusion demo adapts an approved baseline and executes a real supported artifact on the designated non-production pod, with independent output assertions and human sign-off.
- PL/SQL downloads and tests identify their actual external database execution target where configured.
- Native import gaps appear as an explicit assisted path/blocker; no simulation is represented as successful automatic deployment.
- Candidate/test/release provenance identifies exact versions/hashes, and a final complete package is downloadable from Studio and Home.
- Revising earlier work invalidates affected active descendants; previous approvals, runs and releases remain available as history.
- Authorization, client isolation, migrations, durable-job recovery and production UI/network behavior have recorded verification evidence.
