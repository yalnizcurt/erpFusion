# Phase 1 identity and client ownership evidence

Date: 2 October 2026  
Status: Implemented and verified locally; external identity rollout and legacy reconciliation remain prerequisites. Later production phases remain open.

## Delivered

- Provider-neutral identities use exact issuer and stable subject. Asymmetric OIDC verification checks signature, issuer, audience, required claims and expiry; optional introspection checks revocation on every request. Roles and active client memberships come from portal records, not token claims. Development identities are explicit fixtures and cannot run in deployed environments.
- Client memberships and platform configuration/publication roles are separate. Consultants can create and generate requests; functional/technical reviewers and testers act only on configured review stages. Client administrators manage installations, environments and memberships. Only platform administrators create clients and assign platform roles. Authenticated identities supply reviewers and audit actors.
- Typed client, membership, installation and environment APIs support multiple installations per client. URLs and metadata reject inline credentials. These are environment records, not verified ERP connections or a secret store.
- The UI supports searchable/paged client and request directories, ERP/status request filters, installation/environment creation, client role assignment/revocation, and explicit ownership selection when creating requests. Review controls consume the server's configured review role. Local fixture status and unavailable permissions are visible.
- Requests pin a published profile version matching the selected active installation. Ownership cannot be changed by an ordinary PATCH. Archived requests retain history and reject mutations. Active client/install/environment checks protect generation and reviews.
- Artifact, version, validation, audit, feedback, usage and workflow lookups verify authorized ownership and consistent parent client IDs. Mis-scoped feedback is excluded from prompt compilation. Guidance promotion requires a publisher and client administration access. Profile audit queries do not expose other clients' promotion events.
- PostgreSQL forces row security on 13 owned/authorization tables. Composite parent constraints enforce new writes; policies quarantine mismatched legacy children. Transaction-local context is restored after commits and does not carry into a new pooled session. Runtime role checks reject owners, inherited owners, superusers and `BYPASSRLS` roles.
- First-administrator bootstrap is an explicit, audited administration command using the migration connection. Normal authenticated APIs manage subsequent platform roles. Revocation cannot remove the last active administrator for the current issuer.

## Migration and legacy compatibility

`20261002_01` follows `20260929_02` and adds identities, clients, memberships, installations, environments, nullable ownership and authenticated actor references. `20261002_02` adds PostgreSQL ownership constraints and forced row security. Fresh upgrade, preserved legacy data, downgrade/reapply and non-owner operation were tested against disposable PostgreSQL.

Legacy records are not assigned to clients from project or ERP names. Unmapped rows remain quarantined from normal access. New composite constraints are initially `NOT VALID` so preserved malformed historical rows do not prevent migration; new writes are constrained. A reviewed ownership reconciliation must precede constraint validation and mandatory ownership rollout. No customer database was modified in this work.

SQLite remains a development option. It lacks PostgreSQL row security, and the additive unversioned compatibility command cannot rebuild legacy constraints. Explicit API parent checks provide defense in depth; SQLite results do not certify production isolation.

## Verification

| Check | Result |
|---|---|
| Full backend suite with actual PostgreSQL fixtures | **153 passed, zero skipped** |
| PostgreSQL migrations and non-owner isolation subset | **10 passed**, included above |
| Backend lint/type ratchet | Passed; **296 Ruff and 15 mypy inherited diagnostics** remain, 351 ledger entries resolved |
| New Phase 1 security/model/schema/routes/audit/bootstrap/migration/test Ruff check | Passed without diagnostics |
| Frontend unit regressions | **24 passed** |
| Frontend TypeScript, lint and production build | Passed; zero lint warnings; existing main chunk warning approximately 773 KB |
| Browser fixtures | **10 passed** across desktop and compact viewports |

Browser evidence includes client → installation → sandbox → membership onboarding, exact request ownership selection, permission controls, fixed shell, and long JSON containment. Backend regressions cover forged reviewer names, foreign IDs, malformed ownership, scoped retrieval, configurator/publication separation, issuer changes and last-administrator protection, and null update inputs. Provider tests use signed synthetic tokens and controlled JWKS/introspection responses. These checks do not represent real SSO login, customer data, live AI generation, or ERP sandbox execution.

## Deployment prerequisites

1. Obtain the actual organization issuer, audience, signing-key endpoint and browser login integration. Configure OIDC and supply access tokens through the frontend's in-memory token provider. Configure introspection if immediate provider-side revocation is required; without it, token expiry remains the provider-session boundary. Portal role and membership revocations are checked on every request.
2. Apply migrations using a privileged migration identity. Provision a separate non-owner PostgreSQL runtime role with the required table privileges; do not grant table ownership, superuser, `BYPASSRLS`, or membership in an owning role. Set this connection as `DATABASE_URL`. The Render template does not create this role automatically.
3. Keep `MIGRATION_DATABASE_URL` restricted to deployment/administration tooling. Bootstrap the first administrator once with `python -m app.cli.bootstrap_identity --issuer <configured-issuer> --subject <stable-subject>`. Repeat attempts are rejected; further assignments require authenticated platform administration.
4. Reconcile existing ownership through an explicitly reviewed mapping. Suspended/archived clients and unmapped legacy records remain unavailable. Do not enable legacy development flags in deployed environments.

## Continuing work

- Owner and authoritative next-action queue controls remain open; the API accepts owner filters, while next-action semantics depend on the exact-version workflow phase.
- Phase 2 must add durable generation claims, exact dependency checks at completion/approval, concurrent review conflicts, immutable input revisions, non-destructive invalidation and backtracking. Current generation is still one HTTP transaction and historical approval state can be rewritten by invalidation.
- Object storage, worker ownership, document intake, governed frozen manifests, package adaptation/compilation, secret storage, real ERP connection/install adapters, sandbox testing, immutable release bundles and retention/purge controls remain in their planned phases.
- No claim of production security certification, complete enterprise SSO integration, or end-to-end ERP installation is made by these results.
