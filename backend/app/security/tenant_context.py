"""Transaction-local PostgreSQL ownership context for HTTP and worker sessions.

The caller must supply client IDs from verified, authoritative memberships.
Setting the values locally prevents a pooled connection from carrying them into
the next request. The session hook also restores them after an explicit commit.
SQLite remains a development fixture and does not implement row-level security.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

_CONTEXT_KEY = "erpfusion_tenant_context"
_SET_CONTEXT = text(
    "SELECT set_config('app.client_ids', :client_ids, true), "
    "set_config('app.client_admin_ids', :client_admin_ids, true), "
    "set_config('app.subject_id', :subject_id, true), "
    "set_config('app.platform_admin', :platform_admin, true), "
    "set_config('app.erp_admin', :erp_admin, true), "
    "set_config('app.allow_unowned_legacy', :allow_unowned_legacy, true), "
    "set_config('app.execution_worker', :execution_worker, true)"
)


@dataclass(frozen=True)
class TenantContext:
    client_ids: tuple[str, ...] = ()
    client_admin_ids: tuple[str, ...] = ()
    subject_id: str | None = None
    is_platform_admin: bool = False
    is_erp_admin: bool = False
    allow_unowned_legacy: bool = False
    is_execution_worker: bool = False

    def parameters(self) -> dict[str, str]:
        return {
            "client_ids": json.dumps(self.client_ids),
            "client_admin_ids": json.dumps(self.client_admin_ids),
            "subject_id": self.subject_id or "",
            "platform_admin": "true" if self.is_platform_admin else "false",
            "erp_admin": "true" if self.is_erp_admin else "false",
            "allow_unowned_legacy": "true" if self.allow_unowned_legacy else "false",
            "execution_worker": "true" if self.is_execution_worker else "false",
        }


@event.listens_for(Session, "after_begin")
def _set_transaction_context(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    if connection.dialect.name != "postgresql":
        return
    context = session.info.get(_CONTEXT_KEY, TenantContext())
    connection.execute(_SET_CONTEXT, context.parameters())


async def apply_tenant_context(
    session: AsyncSession,
    *,
    client_ids: Iterable[str],
    client_admin_ids: Iterable[str] = (),
    subject_id: str | None = None,
    is_platform_admin: bool = False,
    is_erp_admin: bool = False,
    allow_unowned_legacy: bool = False,
    is_execution_worker: bool = False,
) -> None:
    """Apply a verified identity's ownership context to this session only."""
    context = TenantContext(
        client_ids=tuple(sorted(set(client_ids))),
        client_admin_ids=tuple(sorted(set(client_admin_ids))),
        subject_id=subject_id,
        is_platform_admin=is_platform_admin,
        is_erp_admin=is_erp_admin,
        allow_unowned_legacy=allow_unowned_legacy,
        is_execution_worker=is_execution_worker,
    )
    session.info[_CONTEXT_KEY] = context
    connection = await session.connection()
    if connection.dialect.name == "postgresql":
        await session.execute(_SET_CONTEXT, context.parameters())


async def assert_runtime_role(session: AsyncSession) -> None:
    """Refuse PostgreSQL roles that can bypass the configured RLS boundary.

    Migration tooling uses an independent privileged connection. The runtime
    role must have neither table ownership (including inherited ownership) nor
    SUPERUSER/BYPASSRLS. This is deliberately a read-only capability check.
    """
    connection = await session.connection()
    if connection.dialect.name != "postgresql":
        return
    unsafe = await session.scalar(
        text(
            "SELECT r.rolsuper OR r.rolbypassrls OR EXISTS ("
            " SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')"
            " AND c.relname IN ('clients', 'erp_installations', 'erp_environments',"
            " 'projects', 'artifacts', 'artifact_versions', 'validation_results',"
            " 'generation_runs', 'audit_entries', 'feedback_guidance', 'admin_audit_events',"
            " 'client_memberships', 'platform_role_assignments',"
            " 'project_input_revisions', 'requirement_documents', 'package_candidates',"
            " 'sandbox_evidence', 'package_releases', 'erp_connections',"
            " 'connection_verifications',"
            " 'execution_attempts', 'capability_qualifications', 'simulated_artifacts',"
            " 'integration_patterns', 'integration_pattern_versions', 'pattern_baselines')"
            " AND (pg_has_role(current_user, c.relowner, 'MEMBER')"
            " OR NOT c.relrowsecurity OR NOT c.relforcerowsecurity)"
            ") FROM pg_roles r WHERE r.rolname = current_user"
        )
    )
    if unsafe is not False:
        raise RuntimeError(
            "PostgreSQL runtime role must not own tables or bypass row security; "
            "owned tables must force row security"
        )
