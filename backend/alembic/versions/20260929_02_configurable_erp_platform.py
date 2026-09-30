"""Versioned ERP profiles, registries, assets, and generation provenance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_02"
down_revision = "20260929_01"
branch_labels = None
depends_on = None

json_type = postgresql.JSON(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("erp_profiles", sa.Column("display_name", sa.String(255), nullable=False, server_default=""))
    op.add_column("erp_profiles", sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"))
    op.add_column("erp_profiles", sa.Column("created_by", sa.String(255), nullable=False, server_default="system"))
    op.add_column("erp_profiles", sa.Column("updated_by", sa.String(255), nullable=False, server_default="system"))
    op.execute("UPDATE erp_profiles SET display_name = name, status = CASE WHEN active THEN 'PUBLISHED' ELSE 'RETIRED' END")

    op.create_table(
        "erp_profile_versions",
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("supported_artifact_types", json_type, nullable=False),
        sa.Column("configuration", json_type, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["erp_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "version", name="uq_erp_profile_version"),
    )
    op.create_index("ix_erp_profile_versions_profile_id", "erp_profile_versions", ["profile_id"])
    op.execute("""
        INSERT INTO erp_profile_versions
            (id, profile_id, version, status, supported_artifact_types, configuration, created_by, updated_by, published_at, created_at, updated_at)
        SELECT gen_random_uuid()::text, id, 1, CASE WHEN active THEN 'PUBLISHED' ELSE 'RETIRED' END,
            '["CONTEXT_ANALYSIS","FDD","TDD","SQL","PKS","PKB","DEPLOYMENT"]'::json,
            json_build_object('workflow', json_build_object('stages', json_build_array(
                json_build_object('type','CONTEXT_ANALYSIS','depends_on',json_build_array(),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_context_analysis' ELSE 'generic_json' END,'prompt_stage','CONTEXT_ANALYSIS','label','Context Analysis'),
                json_build_object('type','FDD','depends_on',json_build_array('CONTEXT_ANALYSIS'),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_fdd' ELSE 'generic_json' END,'prompt_stage','FDD','label','Functional Design'),
                json_build_object('type','TDD','depends_on',json_build_array('FDD'),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_tdd' ELSE 'generic_json' END,'prompt_stage','TDD','label','Technical Design'),
                json_build_object('type','SQL','depends_on',json_build_array('TDD'),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_sql' ELSE 'generic_json' END,'prompt_stage','SQL','label','SQL'),
                json_build_object('type','PKS','depends_on',json_build_array('SQL'),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_plsql' ELSE 'generic_json' END,'prompt_stage','PKS','label','Package Specification'),
                json_build_object('type','PKB','depends_on',json_build_array('SQL'),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_plsql' ELSE 'generic_json' END,'prompt_stage','PKB','label','Package Body'),
                json_build_object('type','DEPLOYMENT','depends_on',json_build_array('PKS','PKB'),'adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_deployment' ELSE 'generic_json' END,'prompt_stage','DEPLOYMENT','label','Deployment')
            )), 'generation', json_build_object('strategy','configured_adapters'), 'validation',
            json_build_object('schema_conformity',CASE WHEN key='oracle-fusion-cloud' THEN true ELSE false END,'adapters',CASE WHEN key='oracle-fusion-cloud' THEN json_build_object('SQL','oracle_sql','PKS','oracle_plsql','PKB','oracle_plsql') ELSE '{}'::json END,
                'cross_artifact_traceability',CASE WHEN key='oracle-fusion-cloud' THEN true ELSE false END,
                'traceability_adapter',CASE WHEN key='oracle-fusion-cloud' THEN 'oracle_attribute_lineage' ELSE NULL END)),
            'migration', 'migration', CASE WHEN active THEN now() ELSE NULL END, now(), now()
        FROM erp_profiles
    """)
    op.add_column("projects", sa.Column("erp_profile_version_id", sa.String(36), nullable=True))
    op.add_column("projects", sa.Column("requirement_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("projects", sa.Column("schema_context_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_projects_erp_profile_version_id", "projects", ["erp_profile_version_id"])
    op.create_foreign_key("fk_projects_erp_profile_version", "projects", "erp_profile_versions", ["erp_profile_version_id"], ["id"], ondelete="RESTRICT")
    op.execute("UPDATE projects p SET erp_profile_version_id = v.id FROM erp_profile_versions v WHERE p.erp_profile_id = v.profile_id AND v.version = 1")
    # Older prototype requests did not store an ERP id. Associate one only when the
    # request name identifies exactly one active profile; ambiguous requests stay untouched.
    op.execute(r"""
        WITH candidates AS (
            SELECT p.id AS project_id, profile.id AS profile_id, profile_version.id AS version_id,
                   count(*) OVER (PARTITION BY p.id) AS match_count
            FROM projects p
            JOIN erp_profiles profile ON (
                lower(p.name) LIKE '%' || lower(regexp_replace(coalesce(nullif(profile.display_name, ''), profile.name), '\s+(cloud|erp|system|suite|platform)$', '', 'i')) || '%'
                OR lower(p.name) LIKE '%' || lower(regexp_replace(profile.name, '\s+(cloud|erp|system|suite|platform)$', '', 'i')) || '%'
            )
            JOIN erp_profile_versions profile_version
              ON profile_version.profile_id = profile.id AND profile_version.version = 1
            WHERE p.erp_profile_id IS NULL AND p.erp_profile_version_id IS NULL AND profile.active = true
        )
        UPDATE projects p
        SET erp_profile_id = candidates.profile_id, erp_profile_version_id = candidates.version_id
        FROM candidates
        WHERE p.id = candidates.project_id AND candidates.match_count = 1
    """)

    op.add_column("erp_stage_prompts", sa.Column("profile_version_id", sa.String(36), nullable=True))
    op.add_column("erp_stage_prompts", sa.Column("name", sa.String(255), nullable=False, server_default="Stage prompt"))
    op.add_column("erp_stage_prompts", sa.Column("scope", sa.String(16), nullable=False, server_default="ERP"))
    op.add_column("erp_stage_prompts", sa.Column("status", sa.String(24), nullable=False, server_default="PUBLISHED"))
    op.add_column("erp_stage_prompts", sa.Column("variables", json_type, nullable=False, server_default="[]"))
    op.add_column("erp_stage_prompts", sa.Column("created_by", sa.String(255), nullable=False, server_default="migration"))
    op.add_column("erp_stage_prompts", sa.Column("updated_by", sa.String(255), nullable=False, server_default="migration"))
    op.create_index("ix_erp_stage_prompts_profile_version_id", "erp_stage_prompts", ["profile_version_id"])
    op.create_foreign_key("fk_erp_stage_prompts_profile_version", "erp_stage_prompts", "erp_profile_versions", ["profile_version_id"], ["id"], ondelete="CASCADE")
    op.execute("UPDATE erp_stage_prompts p SET profile_version_id = v.id FROM erp_profile_versions v WHERE p.profile_id = v.profile_id AND v.version = 1")

    op.create_table(
        "prompt_versions",
        sa.Column("scope", sa.String(16), nullable=False), sa.Column("profile_version_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("variables", json_type, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["profile_version_id"], ["erp_profile_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("scope", "profile_version_id", "name", "version", name="uq_prompt_scope_version"),
    )
    for col in ("scope", "stage", "status"):
        op.create_index(f"ix_prompt_versions_{col}", "prompt_versions", [col])
    op.create_index("ix_prompt_versions_profile_version_id", "prompt_versions", ["profile_version_id"])
    op.execute("""
        INSERT INTO prompt_versions
          (id, scope, profile_version_id, name, stage, content, version, status, variables, created_by, updated_by, created_at, updated_at)
        SELECT gen_random_uuid()::text, 'STAGE', p.profile_version_id, p.stage || ' instructions', p.stage,
               p.system_prompt, p.version, 'PUBLISHED', '[]'::json, 'migration', 'migration', now(), now()
        FROM erp_stage_prompts p WHERE p.profile_version_id IS NOT NULL
    """)

    op.create_table(
        "erp_asset_versions",
        sa.Column("asset_id", sa.String(36), nullable=False), sa.Column("profile_version_id", sa.String(36), nullable=False),
        sa.Column("asset_kind", sa.String(24), nullable=False), sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True), sa.Column("package_type", sa.String(80), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=True), sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True), sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True), sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["profile_version_id"], ["erp_profile_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("asset_id", "profile_version_id", "version", name="uq_erp_asset_profile_version"),
    )
    for col in ("asset_id", "profile_version_id", "asset_kind", "status"):
        op.create_index(f"ix_erp_asset_versions_{col}", "erp_asset_versions", [col])

    op.create_table(
        "feedback_guidance",
        sa.Column("project_id", sa.String(36), nullable=True), sa.Column("profile_id", sa.String(36), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False), sa.Column("stage", sa.String(80), nullable=True),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["erp_profiles.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    for col in ("project_id", "profile_id", "scope", "stage", "status"):
        op.create_index(f"ix_feedback_guidance_{col}", "feedback_guidance", [col])

    op.create_table(
        "generation_runs",
        sa.Column("project_id", sa.String(36), nullable=False), sa.Column("artifact_type", sa.String(80), nullable=False),
        sa.Column("profile_version_id", sa.String(36), nullable=False), sa.Column("model", sa.String(128), nullable=False),
        sa.Column("resolved_context", json_type, nullable=False), sa.Column("provenance", json_type, nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_version_id"], ["erp_profile_versions.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generation_runs_project_id", "generation_runs", ["project_id"])
    op.create_index("ix_generation_runs_profile_version_id", "generation_runs", ["profile_version_id"])
    op.add_column("artifact_versions", sa.Column("generation_run_id", sa.String(36), nullable=True))
    op.create_index("ix_artifact_versions_generation_run_id", "artifact_versions", ["generation_run_id"])
    op.create_foreign_key("fk_artifact_versions_generation_run", "artifact_versions", "generation_runs", ["generation_run_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "admin_audit_events",
        sa.Column("actor", sa.String(255), nullable=False), sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False), sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("details", json_type, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_events_action", "admin_audit_events", ["action"])
    op.create_index("ix_admin_audit_events_entity_id", "admin_audit_events", ["entity_id"])

    op.alter_column("artifacts", "artifact_type", type_=sa.String(80), postgresql_using="artifact_type::text")
    op.execute("DROP TYPE IF EXISTS artifact_type")


def downgrade() -> None:
    raise RuntimeError("This data migration is intentionally irreversible: it converts artifact enum values to extensible strings.")
