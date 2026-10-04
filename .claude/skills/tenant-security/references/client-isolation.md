# Identity and client isolation

## OIDC responsibilities

[Browser auth](../../../../frontend/src/auth/oidc.ts) implements authorization code
with S256 PKCE, state/nonce checks, token exchange/refresh and hosted logout.
Access/refresh tokens stay in memory; session storage holds only the transient
login transaction. Claims parsed in the browser control UI/session state, not
backend authorization. [api.ts](../../../../frontend/src/api.ts) attaches tokens
only to configured application API paths and handles rejection.

[OIDCVerifier](../../../../backend/app/security/oidc.py) validates signatures,
pinned issuer/algorithm/audience, token use and temporal claims using configured
JWKS. Cognito access tokens use the configured `client_id` audience/token-use
contract. Optional introspection provides per-request provider revocation checks.
Without it, provider token expiry is a boundary; browser logout does not certify
immediate revocation of all copies or federated sessions.

See [browser authentication](../../../../frontend/AUTHENTICATION.md) for setup.
Synthetic token tests do not prove a real organization login is configured.

## Authoritative permissions

[get_current_identity](../../../../backend/app/security/identity.py) resolves the
stable issuer/subject to active portal records, server-assigned platform roles
and active client memberships. ERP configurator/publisher roles differ from
client administration, request creation, review and testing permissions.
`platform_admin` has intentional elevated authority; ERP configurator status
alone does not grant client data access.

Use [ensure_client_access/get_authorized_project](../../../../backend/app/security/access.py)
and the appropriate mutation/review role checks. Child resources must match their
authorized parent project/client. Foreign identifiers and unmapped legacy rows
are hidden/quarantined; never infer ownership from a project name or ERP label.
Reviewer/audit actor identity must be derived from authenticated portal identity.

Development headers and `identity_for_direct_call` are explicit fixtures.
[admin_auth.py](../../../../backend/app/api/admin_auth.py) retains a shared-key path
only for direct Python compatibility tests; normal HTTP handlers receive an
authenticated identity. Do not expose that fallback as deployed authorization.

## Database and worker boundary

[tenant_context.py](../../../../backend/app/security/tenant_context.py) uses
transaction-local PostgreSQL settings and re-applies context after commits.
Preserve this when adding new sessions, worker operations or pooled transactions.
Production runtime roles must be non-owner, non-superuser, without BYPASSRLS or
inherited table ownership. Migrations/bootstrap use a separate privileged role.

The [RLS migration](../../../../backend/alembic/versions/20261002_02_client_row_security.py)
and subsequent [Studio](../../../../backend/alembic/versions/20261002_03_engineering_studio.py)/
[connection](../../../../backend/alembic/versions/20261002_04_erp_connections.py)
migrations implement forced policies/ownership constraints. Some legacy constraints
are NOT VALID to preserve quarantined historical data while protecting new writes.
Do not bypass them to reconcile legacy records. SQLite has no equivalent RLS.

[Generation workers](../../../../backend/app/cli/generation_worker.py) require
explicit production client scope. `authorize_job` in
[generation.py](../../../../backend/app/api/generation.py) rechecks the initiating
actor's active authority before invocation/completion. Role revocation, archived
clients/projects and stale bindings must remain effective for queued work.

Verification anchors: [ownership tests](../../../../backend/tests/test_phase1_ownership.py),
[PostgreSQL isolation](../../../../backend/tests/test_postgres_isolation.py) and
[OIDC tests](../../../../backend/tests/test_oidc_authentication.py).
