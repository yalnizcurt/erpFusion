"""Add federated identity and explicit client/environment ownership.

Ownership columns on existing records are intentionally nullable for the
reviewed legacy reconciliation period.  This migration does not infer an
owner from a project name, ERP profile, or any other free text.  A later
reconciliation migration may enforce required ownership after an explicit
mapping has been reviewed.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261002_01"
down_revision = "20260929_02"
branch_labels = None
depends_on = None


def _add_column(table: str, column: sa.Column) -> None:
    """Add a nullable compatibility column without changing legacy rows."""
    op.add_column(table, column)
    op.create_index(f"ix_{table}_{column.name}", table, [column.name])


def upgrade() -> None:
    op.create_table(
        "identity_subjects",
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_identity_subject_issuer_subject"),
    )
    op.create_index("ix_identity_subjects_issuer", "identity_subjects", ["issuer"])
    op.create_index("ix_identity_subjects_subject", "identity_subjects", ["subject"])
    op.create_index("ix_identity_subjects_status", "identity_subjects", ["status"])

    op.create_table(
        "clients",
        sa.Column("client_key", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by_subject_id", sa.String(36), nullable=True),
        sa.Column("updated_by_subject_id", sa.String(36), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_key"),
        sa.UniqueConstraint("id", "client_key", name="uq_clients_id_client_key"),
    )
    op.create_index("ix_clients_client_key", "clients", ["client_key"], unique=True)
    op.create_index("ix_clients_status", "clients", ["status"])

    op.create_table(
        "client_memberships",
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("created_by_subject_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["identity_subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id", "subject_id", "role", name="uq_client_membership_subject_role"
        ),
    )
    for name in ("client_id", "subject_id", "role", "status"):
        op.create_index(f"ix_client_memberships_{name}", "client_memberships", [name])

    op.create_table(
        "platform_role_assignments",
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by_subject_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["identity_subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "role", name="uq_platform_role_subject_role"),
    )
    for name in ("subject_id", "role", "status"):
        op.create_index(f"ix_platform_role_assignments_{name}", "platform_role_assignments", [name])

    op.create_table(
        "erp_installations",
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("erp_profile_id", sa.String(36), nullable=False),
        sa.Column("installation_key", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("edition", sa.String(128), nullable=True),
        sa.Column("product_version", sa.String(128), nullable=True),
        sa.Column("external_tenant_reference", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_by_subject_id", sa.String(36), nullable=True),
        sa.Column("updated_by_subject_id", sa.String(36), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["erp_profile_id"], ["erp_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "installation_key", name="uq_erp_installation_client_key"),
        sa.UniqueConstraint("id", "client_id", name="uq_erp_installation_id_client"),
    )
    for name in ("client_id", "erp_profile_id", "status"):
        op.create_index(f"ix_erp_installations_{name}", "erp_installations", [name])

    op.create_table(
        "erp_environments",
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("environment_key", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("environment_type", sa.String(32), nullable=False, server_default="SANDBOX"),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("endpoint_url", sa.String(1024), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_by_subject_id", sa.String(36), nullable=True),
        sa.Column("updated_by_subject_id", sa.String(36), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["installation_id", "client_id"],
            ["erp_installations.id", "erp_installations.client_id"],
            ondelete="CASCADE",
            name="fk_erp_environment_installation_client",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_subject_id"], ["identity_subjects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id", "environment_key", name="uq_erp_environment_installation_key"
        ),
        sa.UniqueConstraint("id", "client_id", name="uq_erp_environment_id_client"),
    )
    for name in ("client_id", "installation_id", "status"):
        op.create_index(f"ix_erp_environments_{name}", "erp_environments", [name])

    # Existing records remain quarantinable until an explicit ownership map is
    # reviewed.  These fields are never populated from free text.
    _add_column("projects", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("projects", sa.Column("erp_installation_id", sa.String(36), nullable=True))
    _add_column("projects", sa.Column("erp_environment_id", sa.String(36), nullable=True))
    _add_column("projects", sa.Column("created_by_subject_id", sa.String(36), nullable=True))
    _add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    _add_column("artifacts", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("artifact_versions", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("artifact_versions", sa.Column("reviewer_subject_id", sa.String(36), nullable=True))
    _add_column("validation_results", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("audit_entries", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("audit_entries", sa.Column("actor_subject_id", sa.String(36), nullable=True))
    _add_column("feedback_guidance", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("generation_runs", sa.Column("client_id", sa.String(36), nullable=True))
    _add_column("generation_runs", sa.Column("erp_installation_id", sa.String(36), nullable=True))
    _add_column("generation_runs", sa.Column("erp_environment_id", sa.String(36), nullable=True))
    _add_column("admin_audit_events", sa.Column("actor_subject_id", sa.String(36), nullable=True))
    _add_column("admin_audit_events", sa.Column("client_id", sa.String(36), nullable=True))

    # Add constraints to upgraded PostgreSQL databases.  SQLite cannot add a
    # foreign key to an existing table without rebuilding it; fresh SQLite
    # databases still get the model constraints through create_all.
    if op.get_bind().dialect.name != "sqlite":
        for table, column in (
            ("projects", "client_id"),
            ("artifacts", "client_id"),
            ("artifact_versions", "client_id"),
            ("validation_results", "client_id"),
            ("audit_entries", "client_id"),
            ("feedback_guidance", "client_id"),
            ("generation_runs", "client_id"),
            ("admin_audit_events", "client_id"),
        ):
            op.create_foreign_key(
                f"fk_{table}_{column}_clients",
                table,
                "clients",
                [column],
                ["id"],
                ondelete="SET NULL",
            )
        for table, column in (
            ("projects", "created_by_subject_id"),
            ("artifact_versions", "reviewer_subject_id"),
            ("audit_entries", "actor_subject_id"),
            ("admin_audit_events", "actor_subject_id"),
        ):
            op.create_foreign_key(
                f"fk_{table}_{column}_subjects",
                table,
                "identity_subjects",
                [column],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_foreign_key(
            "fk_projects_installation_client", "projects", "erp_installations",
            ["erp_installation_id", "client_id"], ["id", "client_id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_projects_environment_client", "projects", "erp_environments",
            ["erp_environment_id", "client_id"], ["id", "client_id"], ondelete="SET NULL",
        )
        for table, column, target in (
            ("generation_runs", "erp_installation_id", "erp_installations"),
            ("generation_runs", "erp_environment_id", "erp_environments"),
        ):
            op.create_foreign_key(
                f"fk_{table}_{column}", table, target, [column], ["id"], ondelete="SET NULL"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        for name, table in (
            ("fk_generation_runs_erp_environment_id", "generation_runs"),
            ("fk_generation_runs_erp_installation_id", "generation_runs"),
            ("fk_projects_environment_client", "projects"),
            ("fk_projects_installation_client", "projects"),
            ("fk_admin_audit_events_actor_subject_id_subjects", "admin_audit_events"),
            ("fk_audit_entries_actor_subject_id_subjects", "audit_entries"),
            ("fk_artifact_versions_reviewer_subject_id_subjects", "artifact_versions"),
            ("fk_projects_created_by_subject_id_subjects", "projects"),
            ("fk_admin_audit_events_client_id_clients", "admin_audit_events"),
            ("fk_generation_runs_client_id_clients", "generation_runs"),
            ("fk_feedback_guidance_client_id_clients", "feedback_guidance"),
            ("fk_audit_entries_client_id_clients", "audit_entries"),
            ("fk_validation_results_client_id_clients", "validation_results"),
            ("fk_artifact_versions_client_id_clients", "artifact_versions"),
            ("fk_artifacts_client_id_clients", "artifacts"),
            ("fk_projects_client_id_clients", "projects"),
        ):
            op.drop_constraint(name, table, type_="foreignkey")

    for table, column in (
        ("admin_audit_events", "client_id"),
        ("admin_audit_events", "actor_subject_id"),
        ("generation_runs", "erp_environment_id"),
        ("generation_runs", "erp_installation_id"),
        ("generation_runs", "client_id"),
        ("feedback_guidance", "client_id"),
        ("audit_entries", "actor_subject_id"),
        ("audit_entries", "client_id"),
        ("validation_results", "client_id"),
        ("artifact_versions", "reviewer_subject_id"),
        ("artifact_versions", "client_id"),
        ("artifacts", "client_id"),
        ("projects", "archived_at"),
        ("projects", "created_by_subject_id"),
        ("projects", "erp_environment_id"),
        ("projects", "erp_installation_id"),
        ("projects", "client_id"),
    ):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_column(table, column)

    for table in (
        "erp_environments",
        "erp_installations",
        "platform_role_assignments",
        "client_memberships",
        "clients",
        "identity_subjects",
    ):
        op.drop_table(table)
