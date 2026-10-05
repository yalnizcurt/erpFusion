# Home and Engineering Studio implementation plan

Date: 2 October 2026  
Status: Planned; this document does not implement the UI.  
Scope: Extend the existing HighStudio application and production plan with a project directory, requirement document intake, and a persistent project Engineering Studio.

The user subsequently approved `mock/` as the visual specification for the real product.
See [the product UI, Bedrock and Oracle sandbox plan](product-ui-bedrock-and-oracle-sandbox-plan.md)
for design transfer, Bedrock/privacy controls, all 22 ERP profiles, connection Ping and
the supported Fusion sandbox execution target. Prototype simulations and browser
storage must be replaced with real authorized server state and test evidence.

## 1. Product contract

Home displays a project table. Engineering work happens in a Studio belonging to one integration project. Users can open Studio from Home or the sidebar, leave it, and return later. Work, approvals, files and history persist on the server.

Opening an earlier stage or historical revision is navigation. Changing an approved input or artifact is an explicit revision action with a downstream impact preview. The latter invalidates affected active work while preserving historical decisions and release files.

Continue using the existing `Project` entity for one integration request. This change does not add a second business-project hierarchy.

## 2. Navigation and fixed application shell

| Location | Purpose |
|---|---|
| Home | Searchable, paginated project directory and Create New |
| Engineering Studio | Choose an authorized project or resume its current actionable stage |
| Clients | Client, ERP installation, environment and membership administration |
| ERP configuration | Governed profiles, prompts, packages, knowledge, rules and publication |

- Keep the HighRadius header, sidebar and bottom bar fixed.
- Scroll content inside the main region. Make the table header sticky within that region; wide table content scrolls horizontally without moving navigation off screen.
- Use stable project URLs, such as `/projects/{id}/studio`, with stage/tab/revision IDs in the URL when viewing a specific saved revision.
- Fetch a Studio project directly by its authorized ID. Its availability must not depend on the current Home page, filters, or first 25 results.
- Home's Open Studio action resumes the current actionable stage. A bookmarked revision URL reopens that exact revision with a visible historical/read-only label when appropriate.
- Sidebar Studio opens a project selector when no project is selected. Do not automatically choose an unrelated first row.
- Preserve Home search, filters, page and sorting when returning from Studio.

## 3. Home table

Place **+ Create New** above the table, with search and filters. No workflow diagram appears on Home.

| Column | Content and behavior |
|---|---|
| Client name | Authorized owning client |
| Project name | Link to the project Studio |
| ERP | Registry display name; pinned profile/version available as secondary information |
| Type | Standard or Custom |
| Status | Current business state and actionable blocker, derived from effective workflow state |
| Due date | Business date, or “Not set”; overdue badge independent of engineering status |
| Last updated | Last meaningful project activity, shown in the viewer's time zone |
| Package | Authorized current candidate/release download, or the reason it is unavailable |
| Action | Open Studio / Resume |

Directory behavior:

- Server-side search, pagination and sorting; do not load all 4,500 clients' projects into the browser.
- Filters: client, ERP, Standard/Custom, status, due-date range, overdue, and projects created by the signed-in user.
- Sort by last updated, due date, project name or client name, with a stable ID tie-breaker.
- Show clear empty, loading and failure states. Keep an existing page intact when a refresh fails.
- Use one summary query/response for the table; avoid separate workflow/download queries for every row.
- Enforce client authorization in the summary and download APIs, independently of visible controls.

### Dates and type

`due_date` is a calendar date interpreted using the client's configured business time zone. It is optional while a project is a draft; display “Not set” instead of inventing a deadline. Overdue means the business date has passed and the project is neither completed nor archived. It does not overwrite the engineering status.

Record project activity in UTC and display it locally. Existing `Project.updated_at` alone is insufficient: child artifact generation, reviews and document uploads do not necessarily update it. Add `last_activity_at` and update it transactionally on meaningful committed changes. Viewing a page, polling or downloading a package must not change Last updated.

Working definition, pending product review:

- **Standard:** reuse an approved baseline package with supported configuration changes.
- **Custom:** modify or extend a baseline package for the requirement.

Record project type separately from the selected baseline's identity/version. Do not infer type from ERP name. Permit an audited classification change; if it changes implementation inputs, use the same revision/impact flow.

### Status

Use actionable labels such as Draft, Parsing requirements, Clarification needed, Requirement review, FDD review, TDD review, Package review, Ready for sandbox, Testing, Changes requested, Blocked, Completed, and Archived.

Derive status from configured stages, current eligible revisions, active jobs and test/release evidence. A historically approved downstream artifact with changed prerequisites cannot make a row appear complete. Stage labels and review roles continue to come from ERP configuration.

## 4. Create New and requirement document intake

Create a saved project draft before uploading files, so uploads always have an authorized client/project owner.

1. Select client, ERP installation/environment and a published profile version.
2. Enter project name, description, Standard/Custom and optional due date.
3. Save the draft and open its Studio Requirements workspace.
4. Upload the consulting requirement document through a visible drag/drop area and file chooser. Support multiple related files, initially PDF and DOCX; label unsupported or scanned content requiring OCR clearly.
5. Show file names, sizes, upload/extraction progress, outcomes and document revision history.
6. Preview the original document alongside extracted text/tables and source references. Allow corrections as a new structured requirement revision, preserving the source.
7. Run requirement assessment. Present ambiguities, contradictions, assumptions, missing information and clarification questions with source evidence.
8. Resolve questions and submit the exact assessment/requirement revision for human approval. Unlock FDD only after that approval.

Schema/context, package contracts and other technical evidence can be added within Studio when needed. Do not require consulting users to paste schema JSON merely to save an intake draft. ERP-configured readiness checks determine which evidence is required for each later stage.

Validate file content/type, size and access; keep files private; scan/quarantine before parsing; bound parser resources. Failed parsing or missing OCR cannot be silently treated as a complete requirement.

## 5. Studio layout and engineering flow

Studio header: client, project name, ERP/profile version, type, due date, current status, save state and Back to Home.

Inside the scrollable workspace:

- Stage navigation showing configured order, active stage, blocked stages and review state.
- Main document/artifact workspace with content preview, relevant source references and generation/validation progress.
- Contextual actions: save, analyze/generate, answer questions, submit for review, approve, request changes, revise, and download when eligible.
- Project sections for Requirements, Engineering, History/Diffs, Source/Generation Details, and Sandbox/Release. These are project workspaces, not a second global workflow.

Conceptual flow:

```text
Requirement upload → extraction/clarification → approved requirement assessment
    → FDD → review/fixes → approval
    → TDD → review/fixes → approval
    → approved AS-IS package adaptation → validation/review/fixes → approval
    → candidate download/install in sandbox → tests → tester sign-off
    → final tested release download
```

ERP profiles configure actual stages, artifact files and adapters. SQL/spec/body review may appear when configured, without imposing Oracle's stage layout on other ERPs. Every review targets the exact displayed revision.

## 6. Leaving, resuming and returning to earlier stages

### Leaving and resuming

- Persist drafts, clarification answers, review submissions and input revisions on the server.
- Display Saving, Saved or Save failed. Warn before leaving with unsaved changes; failed autosave must not masquerade as success.
- Keep authenticated document content and tokens out of browser storage. URLs carry identifiers, not document text or credentials.
- Generation, parsing and validation run as durable background jobs. Navigation, closing the browser, token expiry or a disconnected network do not delete jobs or their results.
- Studio reconnects using persisted job IDs and server status. Retry creates an explicit recorded attempt rather than blindly submitting duplicate generation.
- On reopen, fetch current inputs, artifact pointer, dependency validity, approvals, jobs and permissions. Reauthenticate when required before fetching project data.
- Support concurrent users with revision checks; return a conflict when another user changed the reviewed revision or draft. Never silently overwrite it.

### Revising an earlier stage

1. Open the earlier stage and inspect its current or historical revision.
2. Choose Revise and record the requested change/reason.
3. Show the downstream impact before committing: affected artifacts, approvals, jobs, candidate, sandbox tests and current release applicability.
4. Save a new input/artifact revision. Mark affected active descendants stale/blocked and revoke affected running-job ownership atomically.
5. Preserve old content, approval decisions, diffs, generation sources, test evidence and released file bytes. A late job completion is retained as stale evidence and cannot replace active work.
6. Resume approval/generation at the changed point. Regenerate and review affected stages in order.

Changing a deadline, returning Home, opening history or switching tabs does not invalidate engineering artifacts. Previously released packages remain in History with their original evidence, while the active project clearly shows that a new revision is being developed.

## 7. Package downloads

- Before package approval: unavailable, with an actionable explanation.
- After coherent package approval and required checks: Download candidate for sandbox testing.
- After current sandbox evidence and authorized tester sign-off: Download release.
- When an upstream change invalidates the active candidate: block its normal current-package link. Historical approved/tested packages remain explicitly accessible from History according to permissions.
- Assemble/check packages on the server from an immutable manifest of exact approved file revisions/checksums. Include all ERP-configured outputs; individual PL/SQL files are available when configured.
- Authorize every download. Use scoped expiring links or authenticated delivery rather than permanent public bucket URLs. Audit downloads separately without changing Last updated.

## 8. Implementation changes and current gaps

### Reuse existing parts

- Retain the fixed shell, identity/client/install/environment ownership and ERP registry.
- Move current pipeline/document/diff/traceability components into the project Studio and reuse their validated content renderers.
- Retain pinned profile behavior, prompt compilation and artifact provenance; strengthen exact-version transitions instead of introducing ERP-name branches.

### Backend/API

- Add project type, due date and last activity through additive migrations. Do not guess historical type/deadlines; expose legacy unknown values until explicitly classified.
- Permit draft intake before approved requirement content exists; do not disguise empty inputs as an engineering-ready request.
- Add a typed, paginated project summary API with joined client/ERP metadata, derived status and download eligibility.
- Add immutable requirement/document/context revisions, exact dependency bindings, append-only review decisions and active validity/current pointers.
- Replace the existing prohibition on input edits after generation with explicit revision/backtracking commands and impact preview.
- Add durable jobs/runs/attempts and scoped document ingestion/download contracts. Persist a claim before executing a provider; verify exact inputs/dependencies at completion and approval.
- Add authoritative candidate/test/release eligibility and immutable manifests; replace browser-only approval counts and package ZIP assembly.

### Frontend

- Separate Home, Clients, ERP configuration and project Studio through stable navigation.
- Replace Home pipeline panels with the project table and Create New.
- Replace the current text/JSON intake form with draft creation and visible document upload in Studio.
- Bind stage content, comments, validation and review actions to one exact revision.
- Restore pending work and display actionable save/job/conflict states. Allow Home navigation during background work.

Current code stores page/project/stage selections in component state, selects projects from the currently loaded table page, runs generation inside an HTTP transaction, prohibits input changes after generation, and assembles downloads in the browser. A cosmetic Home refactor cannot provide the required resume/history guarantees by itself.

## 9. Delivery slices

Each slice includes API, UI, migrations where applicable, automated regression/type/build checks and PostgreSQL/state-machine evidence.

| Slice | End-to-end outcome |
|---|---|
| 1 — Home and Studio navigation | Authorized project table, Create New, dates/type, direct project Studio links, fixed shell and filter-preserving return |
| 2 — Draft document intake | Saved draft → private upload → parsing preview → clarification → exact requirement approval in Studio |
| 3 — Durable revisions and resume | Persisted jobs, atomic transitions, concurrent review protection, history, impact preview and safe backtracking |
| 4 — Engineering workspaces | FDD/TDD/package generation and corrections through configured stages using exact approved dependencies and AS-IS baseline |
| 5 — Sandbox and downloads | Approved candidate → test evidence/sign-off → immutable final release; Home package link reflects eligibility |

Slices map onto existing production phases 2, 4–8. Implement the minimum durable execution needed for Studio resume with slices 2–3; do not leave it behind a later visual milestone. Complete and verify a slice before depending on it.

## 10. Acceptance scenarios

1. Home shows the required table, due date and Last updated, with Create New above it and no workflow diagram.
2. Any authorized table row opens that exact project's Studio, including projects outside the first page or current filters.
3. Users can create a draft, upload PDF/DOCX and review extraction/questions without manually pasting requirement text or schema JSON.
4. A user leaves while parsing/generation runs, signs in later and sees its persisted status/result without duplicate work.
5. Saved draft changes and clarification answers survive navigation/reload; failed saves show an error and leaving warns about unsaved changes.
6. Approved requirement → approved FDD → approved TDD → approved adapted package remains strictly ordered.
7. Revising an earlier approved requirement blocks affected current downstream work, preserves old approvals/history and prevents stale jobs from becoming current.
8. Two conflicting reviews produce one decision and one conflict. Viewing history produces no mutation.
9. Due date renders correctly across time zones; overdue is independent of engineering state. Committed generation/review/upload activity updates Last updated; viewing/downloading does not.
10. Home shows candidate download only when eligible and final release only after exact sandbox evidence/sign-off. Invalidated current work cannot expose a misleading current package.
11. Client A cannot see Client B's table rows, Studio URLs, files, jobs, history or downloads.
12. Header, sidebar, bottom bar and navigation remain visible on narrow screens, long JSON content and wide tables.
