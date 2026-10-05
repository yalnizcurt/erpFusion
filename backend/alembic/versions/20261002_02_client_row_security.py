"""Enforce explicit ownership with composite constraints and PostgreSQL RLS.

Legacy ownership is preserved verbatim. NOT VALID foreign keys protect new
writes without rejecting historical rows awaiting reviewed reconciliation.
RLS quarantines those NULL or mismatched rows from normal runtime identities.
SQLite is an explicitly limited development fixture; it does not offer RLS.
"""

from alembic import op

revision = "20261002_02"
down_revision = "20261002_01"
branch_labels = None
depends_on = None

_OWNED_TABLES = (
    "clients", "erp_installations", "erp_environments", "projects", "artifacts",
    "artifact_versions", "validation_results", "generation_runs", "audit_entries",
    "feedback_guidance", "admin_audit_events", "client_memberships", "platform_role_assignments",
)

# Identifiers and predicates here are migration constants, never request input.
_COMPOSITE_KEYS = {
    "projects": ("id", "client_id"),
    "artifacts": ("id", "project_id", "client_id"),
    "artifact_versions": ("id", "artifact_id", "client_id"),
    "generation_runs": ("id", "client_id"),
    "erp_environments": ("id", "installation_id", "client_id"),
}
_FOREIGN_KEYS = (
    ("artifacts", "project_client", ("project_id", "client_id"),
     "projects", ("id", "client_id")),
    ("artifact_versions", "artifact_client", ("artifact_id", "client_id"),
     "artifacts", ("id", "client_id")),
    ("artifact_versions", "parent_artifact_client",
     ("parent_version_id", "artifact_id", "client_id"),
     "artifact_versions", ("id", "artifact_id", "client_id")),
    ("artifact_versions", "generation_client", ("generation_run_id", "client_id"),
     "generation_runs", ("id", "client_id")),
    ("validation_results", "version_client", ("artifact_version_id", "client_id"),
     "artifact_versions", ("id", "client_id")),
    ("audit_entries", "version_client", ("artifact_version_id", "client_id"),
     "artifact_versions", ("id", "client_id")),
    ("audit_entries", "project_client", ("project_id", "client_id"),
     "projects", ("id", "client_id")),
    ("generation_runs", "project_client", ("project_id", "client_id"),
     "projects", ("id", "client_id")),
    ("feedback_guidance", "project_client", ("project_id", "client_id"),
     "projects", ("id", "client_id")),
    ("projects", "environment_installation_client",
     ("erp_environment_id", "erp_installation_id", "client_id"),
     "erp_environments", ("id", "installation_id", "client_id")),
    ("generation_runs", "installation_client", ("erp_installation_id", "client_id"),
     "erp_installations", ("id", "client_id")),
    ("generation_runs", "environment_installation_client",
     ("erp_environment_id", "erp_installation_id", "client_id"),
     "erp_environments", ("id", "installation_id", "client_id")),
)


def _flag(name: str) -> str:
    return f"COALESCE(current_setting('app.{name}', true), '') = 'true'"


def _access(client: str) -> str:
    admin = _flag("platform_admin")
    legacy = _flag("allow_unowned_legacy")
    membership = (
        f"COALESCE(NULLIF(current_setting('app.client_ids', true), ''), '[]')::jsonb "
        f"? {client}"
    )
    return (
        f"(({client} IS NOT NULL AND (({admin}) OR ({membership}))) "
        f"OR ({client} IS NULL AND ({legacy})))"
    )


def _manage(client: str) -> str:
    membership = (
        "COALESCE(NULLIF(current_setting('app.client_admin_ids', true), ''), '[]')::jsonb "
        f"? {client}"
    )
    return f"{_access(client)} AND (({_flag('platform_admin')}) OR ({membership}))"


def _parent(table: str, parent: str, foreign_key: str, extra: str = "") -> str:
    return (
        f"EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {table}.{foreign_key} "
        f"AND p.client_id IS NOT DISTINCT FROM {table}.client_id {extra})"
    )


def _policy(table: str, read: str, write: str | None = None) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    # Separate SELECT and mutation policies keep shared approved guidance
    # readable while restricting its edits to a platform ERP administrator.
    op.execute(f'CREATE POLICY tenant_read ON "{table}" FOR SELECT USING ({read})')
    mutation = write or read
    op.execute(
        f'CREATE POLICY tenant_insert ON "{table}" FOR INSERT WITH CHECK ({mutation})'
    )
    op.execute(
        f'CREATE POLICY tenant_update ON "{table}" FOR UPDATE USING ({mutation}) '
        f'WITH CHECK ({mutation})'
    )
    op.execute(f'CREATE POLICY tenant_delete ON "{table}" FOR DELETE USING ({mutation})')


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table, columns in _COMPOSITE_KEYS.items():
        op.create_unique_constraint(f"uq_{table}_tenant_parent", table, list(columns))
    # Additional pairs are referenced by the narrower child constraints.
    op.create_unique_constraint("uq_artifacts_id_client", "artifacts", ["id", "client_id"])
    op.create_unique_constraint(
        "uq_artifact_versions_id_client", "artifact_versions", ["id", "client_id"]
    )
    for table, suffix, columns, parent, parent_columns in _FOREIGN_KEYS:
        op.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "fk_{table}_{suffix}_rls" '
            f'FOREIGN KEY ({", ".join(columns)}) REFERENCES "{parent}" '
            f'({", ".join(parent_columns)}) NOT VALID'
        )

    current_subject = "NULLIF(current_setting('app.subject_id', true), '')"
    _policy(
        "client_memberships",
        f"subject_id = {current_subject} OR {_access('client_id')}",
        _manage("client_id"),
    )
    _policy(
        "platform_role_assignments",
        f"subject_id = {current_subject} OR ({_flag('platform_admin')})",
        _flag("platform_admin"),
    )
    _policy("clients", _access("id"), _manage("id"))
    _policy("erp_installations", _access("client_id"), _manage("client_id"))
    environment_parent = _parent('erp_environments', 'erp_installations', 'installation_id')
    _policy(
        "erp_environments",
        f"{_access('client_id')} AND {environment_parent}",
        f"{_manage('client_id')} AND {environment_parent}",
    )
    project = _access("client_id")
    for column, parent in (
        ("erp_installation_id", "erp_installations"),
        ("erp_environment_id", "erp_environments"),
    ):
        extra = (
            "AND p.installation_id = projects.erp_installation_id"
            if parent == "erp_environments" else ""
        )
        project += (
            f" AND ({column} IS NULL OR "
            f"{_parent('projects', parent, column, extra)})"
        )
    _policy("projects", project)
    _policy(
        "artifacts",
        f"{_access('client_id')} AND {_parent('artifacts', 'projects', 'project_id')}",
    )
    _policy(
        "artifact_versions",
        f"{_access('client_id')} AND "
        f"{_parent('artifact_versions', 'artifacts', 'artifact_id')}",
    )
    _policy(
        "validation_results",
        f"{_access('client_id')} AND "
        f"{_parent('validation_results', 'artifact_versions', 'artifact_version_id')}",
    )
    project_binding = (
        "AND p.erp_installation_id IS NOT DISTINCT FROM generation_runs.erp_installation_id "
        "AND p.erp_environment_id IS NOT DISTINCT FROM generation_runs.erp_environment_id"
    )
    generation = (
        f"{_access('client_id')} AND "
        f"{_parent('generation_runs', 'projects', 'project_id', project_binding)}"
    )
    for column, parent in (
        ("erp_installation_id", "erp_installations"),
        ("erp_environment_id", "erp_environments"),
    ):
        extra = (
            "AND p.installation_id = generation_runs.erp_installation_id"
            if parent == "erp_environments" else ""
        )
        generation += (
            f" AND ({column} IS NULL OR "
            f"{_parent('generation_runs', parent, column, extra)})"
        )
    _policy("generation_runs", generation)
    audit = (
        f"{_access('client_id')} AND {_parent('audit_entries', 'projects', 'project_id')}"
        " AND EXISTS (SELECT 1 FROM artifact_versions v JOIN artifacts a ON a.id = v.artifact_id"
        " WHERE v.id = audit_entries.artifact_version_id"
        " AND a.project_id = audit_entries.project_id"
        " AND v.client_id IS NOT DISTINCT FROM audit_entries.client_id)"
    )
    _policy("audit_entries", audit)
    shared = (
        "project_id IS NULL AND client_id IS NULL AND "
        "((scope = 'GLOBAL' AND profile_id IS NULL) OR "
        "(scope = 'ERP' AND profile_id IS NOT NULL))"
    )
    scoped = (
        f"scope = 'PROJECT' AND {_access('client_id')} AND "
        f"{_parent('feedback_guidance', 'projects', 'project_id')}"
    )
    erp_admin = f"({_flag('platform_admin')}) OR ({_flag('erp_admin')})"
    _policy(
        "feedback_guidance",
        f"({scoped}) OR ({shared} AND (status = 'APPROVED' OR ({erp_admin})))",
        f"({scoped}) OR ({shared} AND ({erp_admin}))",
    )
    registry_event = (
        "entity_type IN ('ERPProfile', 'ERPProfileVersion', 'PromptVersion', 'ERPAssetVersion',"
        " 'ERP_PROFILE', 'ERP_PROFILE_VERSION', 'PROMPT_VERSION') OR "
        "(entity_type = 'FeedbackGuidance' AND EXISTS (SELECT 1 FROM feedback_guidance f"
        " WHERE f.id = admin_audit_events.entity_id AND f.project_id IS NULL"
        " AND f.client_id IS NULL AND f.scope IN ('GLOBAL', 'ERP')))"
    )
    _policy(
        "admin_audit_events",
        f"(client_id IS NOT NULL AND {_access('client_id')}) "
        f"OR (client_id IS NULL AND (({_flag('platform_admin')}) "
        f"OR ({_flag('allow_unowned_legacy')}) "
        f"OR (({_flag('erp_admin')}) AND ({registry_event}))))",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(_OWNED_TABLES):
        for name in ("tenant_read", "tenant_insert", "tenant_update", "tenant_delete"):
            op.execute(f'DROP POLICY "{name}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table, suffix, *_rest in reversed(_FOREIGN_KEYS):
        op.drop_constraint(f"fk_{table}_{suffix}_rls", table, type_="foreignkey")
    for table in ("artifact_versions", "artifacts"):
        op.drop_constraint(f"uq_{table}_id_client", table, type_="unique")
    for table in reversed(_COMPOSITE_KEYS):
        op.drop_constraint(f"uq_{table}_tenant_parent", table, type_="unique")
