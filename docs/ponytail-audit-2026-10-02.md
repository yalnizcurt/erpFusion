# Ponytail repository audit

Date: 2 October 2026. Report only; none of these simplifications was applied.
Estimates are possible reductions, not measured changes. Security and correctness repairs
were reviewed separately and are recorded in the Phase 1 evidence.

shrink: Remove the test-only shared administrator key authorization path (~35 lines). Pass an explicit Identity in compatibility tests and retain server role authorization. [backend/app/api/admin_auth.py:11]

shrink: Remove duplicated artifact/version ownership resolution (~30 lines). Share one resolver between artifact reads and reviews, preserving every ownership check. [backend/app/api/reviews.py:133; backend/app/api/artifacts.py:282]

shrink: Collapse three repeated Artifact Studio tab button blocks (~30 lines). Map the three labels through existing button markup and shared styles. [frontend/src/components/BottomCards.jsx:124]

delete: Remove unused React/Vite scaffold graphics and social icon sprite (~26 lines). Nothing; application assets have separate references. [frontend/src/assets/react.svg; frontend/src/assets/vite.svg; frontend/src/assets/hero.png; frontend/public/icons.svg:1]

stdlib: Replace CheckResult constructor/serialization boilerplate (~16 lines). dataclasses.dataclass, field(default_factory=dict), and asdict; ValidationStatus already inherits str. [backend/app/services/validation/engine.py:23]

delete: Remove unused cached database engine/session wrappers (~16 lines). Existing create_database_engine and create_session_factory serve every caller. [backend/app/database.py:38]

delete: Remove unused ERPProfileCreate and StagePromptCreate contracts (~14 lines). Nothing; neither is referenced by routes or tests. [backend/app/schemas/__init__.py:129]

delete: Remove unused IdentityConfigurationError and require_authenticated_identity exports (~14 lines). Existing get_current_identity remains the authentication dependency. [backend/app/security/identity.py:23; backend/app/security/identity.py:277; backend/app/security/__init__.py:6]

yagni: Remove reserved AWS credentials and corresponding example/redaction entries (~10 lines). Add them with an implemented Bedrock adapter; preserve generic credential redaction. [backend/app/config.py:48; backend/.env.example:14]

delete: Remove unused duplicate Oracle prompt seed (~8 lines, 15 KB). Current development-v1 manifest contains all six identical prompt contents; update the old audit document reference. [backend/seed/oracle_fusion.prompts.json:1]

shrink: Build GenericJSONStrategy's identical LLMRequest once (~7 lines). Select generate_configured_json or generate_json once, then make one request. [backend/app/services/codegen/strategies.py:26]

net: -206 lines, -0 deps possible.
