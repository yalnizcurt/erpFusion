# Product interaction contracts

## Navigation and shell

Read [App.jsx](../../../../frontend/src/App.jsx),
[product.css](../../../../frontend/src/product.css) and
[index.css](../../../../frontend/src/index.css). The current product uses browser
history/path parsing, not an installed routing library. Preserve deep links,
back/forward behavior and query-selected Studio tab/stage/revision when editing
navigation.

Header, sidebar and footer/bottom bar remain stable. Content regions own overflow;
grid/flex children must be allowed to shrink, and code/JSON/text previews must
remain bounded at desktop/compact widths. Reuse existing shell/preview classes.
Do not solve a wide artifact by hiding the navigation or clipping actions.

## Home and Studio

[ProjectDirectory](../../../../frontend/src/components/ProjectDirectory.jsx)
shows client, project, ERP, Standard/Custom type, status, due date, last update and
eligible package download, with Create New above the table. Preserve search,
filters, pagination and selection when returning from a project. The workflow
belongs in [ProjectStudio](../../../../frontend/src/components/ProjectStudio.jsx).

Project creation selects an explicit client, ERP installation, environment and
published profile version. RequirementsWorkspace provides document upload,
extraction/scan status, editable requirement/context, expected-version saves and
explicit profile upgrade confirmation. Do not obscure intake behind the artifact
viewer or silently change a request's ERP version.

Committed generation runs survive navigation. Studio loads/polls server job state
and refreshes terminal results. Project/tab URLs enable resumption; unsaved edits
are guarded, but durable saving of every draft is not implemented. Do not claim
the product preserves drafts the way `mock/` browser-local data does.

## Reviews, progression and history

Use server `can_generate`, effective gate status and review blockers. Show why a
stage is unavailable; pending upstream work cannot coexist with actively approved
descendants in the presentation. Current backend approval unlocks generation;
the user still triggers it. Avoid UI text implying automatic next-stage execution.

[BottomCards](../../../../frontend/src/components/BottomCards.jsx) and Studio bind
review submissions to the current revision and offer explicit confirmation.
Prevent duplicate submissions, preserve comments on failure and show conflicts
without applying optimistic approval. Historical revisions remain readable;
their earlier approval is distinct from current validity. Earlier-stage changes
must explain downstream invalidation and retained history.

Render generic configured artifact fields, code and JSON as safe bounded content.
Do not assume every package is PL/SQL or drop unknown fields from exports.
[PDF generation](../../../../frontend/src/utils/generatePdf.js) currently renders
structured content locally; it is not a Google Docs or Word-template service.

## Permissions, downloads and privacy

[Identity contracts](../../../../frontend/src/contracts/identity.ts) and the
authenticated identity response govern available actions. Distinguish ERP editing
from publication and client request creation from reviewing/testing. UI controls
communicate permission; backend checks remain mandatory.

Use [api.ts](../../../../frontend/src/api.ts), including `downloadApiFile`, for
authenticated downloads and session-rejection handling. File choices must refer
to exact candidate bytes and explicit historical versions. Preserve object URL
cleanup. Source bundles/manual sign-off must retain their assurance labels; the
sandbox screen cannot claim automatic import or independent remote execution.

Never persist ERP secrets, tokens, requirement text or generated client artifacts
in local storage for convenience. OIDC transient transaction storage is a
separate controlled mechanism. Clear private state when sessions change and keep
code/content as text rather than executable HTML. Do not add external analytics,
session replay, fonts or content exports without an approved data-boundary change.

## Regression anchors

[Fixed-shell browser tests](../../../../frontend/e2e/fixed-shell.spec.ts),
[ownership browser tests](../../../../frontend/e2e/ownership.spec.ts), component
tests beside Studio dependencies, and
[full-stack onboarding](../../../../frontend/e2e-fullstack/onboarding.spec.ts)
cover different guarantees. The mock is a product reference with simulated data;
fixture browsers are not live ERP evidence. Refer to the current test configs
before reporting which dimensions were actually verified.
