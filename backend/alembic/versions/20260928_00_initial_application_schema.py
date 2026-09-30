"""Create the original project and artifact tables for fresh deployments."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260928_00"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("business_requirement", sa.Text(), nullable=False),
        sa.Column("erp_schema_context", sa.JSON(), nullable=False),
        sa.Column("fdd_template_path", sa.String(512), nullable=True),
        sa.Column("tdd_template_path", sa.String(512), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_name", "projects", ["name"])

    op.create_table(
        "artifacts",
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("artifact_type", sa.String(80), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("gate_status", sa.String(24), nullable=False, server_default="LOCKED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])

    op.create_table(
        "artifact_versions",
        sa.Column("artifact_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="DRAFT"),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("parent_version_id", sa.String(36), nullable=True),
        sa.Column("input_context_snapshot", sa.JSON(), nullable=True),
        sa.Column("ai_model_version", sa.String(128), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comments", sa.Text(), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_version_id"], ["artifact_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifact_versions_artifact_id", "artifact_versions", ["artifact_id"])

    op.create_table(
        "validation_results",
        sa.Column("artifact_version_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["artifact_version_id"], ["artifact_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validation_results_artifact_version_id", "validation_results", ["artifact_version_id"])

    op.create_table(
        "audit_entries",
        sa.Column("artifact_version_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["artifact_version_id"], ["artifact_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_entries_artifact_version_id", "audit_entries", ["artifact_version_id"])
    op.create_index("ix_audit_entries_project_id", "audit_entries", ["project_id"])
    op.create_index("ix_audit_entries_timestamp", "audit_entries", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_entries_timestamp", table_name="audit_entries")
    op.drop_index("ix_audit_entries_project_id", table_name="audit_entries")
    op.drop_index("ix_audit_entries_artifact_version_id", table_name="audit_entries")
    op.drop_table("audit_entries")
    op.drop_index("ix_validation_results_artifact_version_id", table_name="validation_results")
    op.drop_table("validation_results")
    op.drop_index("ix_artifact_versions_artifact_id", table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_projects_name", table_name="projects")
    op.drop_table("projects")
