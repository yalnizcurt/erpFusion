"""Add ERP profiles and immutable stage prompt versions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_01"
down_revision = "20260928_00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_profiles",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=False),
        sa.Column("product_version", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("configuration", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_erp_profiles_key", "erp_profiles", ["key"], unique=True)
    op.create_table(
        "erp_stage_prompts",
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["erp_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "stage", "version", name="uq_profile_stage_version"),
    )
    op.create_index("ix_erp_stage_prompts_profile_id", "erp_stage_prompts", ["profile_id"])
    op.add_column("projects", sa.Column("erp_profile_id", sa.String(length=36), nullable=True))
    op.create_index("ix_projects_erp_profile_id", "projects", ["erp_profile_id"])
    op.create_foreign_key(
        "fk_projects_erp_profile_id_erp_profiles", "projects", "erp_profiles",
        ["erp_profile_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_erp_profile_id_erp_profiles", "projects", type_="foreignkey")
    op.drop_index("ix_projects_erp_profile_id", table_name="projects")
    op.drop_column("projects", "erp_profile_id")
    op.drop_index("ix_erp_stage_prompts_profile_id", table_name="erp_stage_prompts")
    op.drop_table("erp_stage_prompts")
    op.drop_index("ix_erp_profiles_key", table_name="erp_profiles")
    op.drop_table("erp_profiles")
