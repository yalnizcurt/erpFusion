---
name: tenant-security
description: Change or review HighStudio identity, client ownership, authorization, PostgreSQL row security, worker access, ERP credentials, private artifacts or allowed data destinations. Use when a task crosses a client boundary or changes how sensitive data is stored, exposed or transmitted.
---

# Tenant security

## Use and ownership

This skill owns authenticated identity, authoritative permissions and client/data
boundaries across API, workers, database, storage and browser. Use for security
changes and for feature work that introduces a new sensitive read/write path.
It does not grant permission to provision accounts, change credentials or test
a live customer environment.

## Critical rules

- Never weaken tenant isolation. Reuse backend ownership/role checks and preserve
  PostgreSQL constraints/RLS; UI visibility is not authorization.
- Portal roles and memberships are server-owned. Verify tokens on the backend;
  browser claims, request client IDs and reviewer names are not authority.
- Preserve transaction-local authorization context, including after worker/API
  commits. A background job is not authorized merely because it was queued earlier.
- ERP credentials must never enter prompts, logs, generated documents, model
  context, public frontend variables or client-readable connection metadata.
- Private downloads need authenticated parent ownership and byte/checksum checks.
  Keep uploaded/retrieved content inside approved data destinations.

## Do not assume

An ERP administrator can read every client's project. SQLite verifies RLS.
Development identity headers or direct-test compatibility keys are production
authentication. Browser logout immediately revokes every issued JWT. “No external
telemetry” means security/audit records should be disabled.

## Pattern architecture reference

Read the [HighStudio pattern architecture](../../../docs/architecture/highstudio-integration-patterns.md)
when a task changes pattern selection, approved baseline pins, target runtime or qualification
claims. Reuse existing intelligence, ownership, revision and evidence services; installation
is required only when the selected pattern contract requires it.

## Source entry points

- [Identity](../../../backend/app/security/identity.py),
  [OIDC verifier](../../../backend/app/security/oidc.py),
  [ownership access](../../../backend/app/security/access.py).
- [Tenant context](../../../backend/app/security/tenant_context.py),
  [identity models](../../../backend/app/models/identity.py).
- [Browser PKCE](../../../frontend/src/auth/oidc.ts), [authenticated API](../../../frontend/src/api.ts).
- [Connections](../../../backend/app/services/erp_connections.py),
  [artifact storage](../../../backend/app/services/artifact_storage.py),
  [logging](../../../backend/app/core/logging.py), [configuration](../../../backend/app/config.py).

## Read as needed

- [Client isolation](references/client-isolation.md): auth, roles, RLS and workers.
- [Credentials and data boundaries](references/credentials-and-data-boundaries.md): secrets, files, providers and egress.
