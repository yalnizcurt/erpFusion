# Security verification register

Date: 2 October 2026  
Owner: Platform engineering  
Status: Implementation evidence register; not a security certification.

The verification targets are OWASP ASVS 5.0 Level 2 with stronger selected execution controls,
NIST SSDF practices and signed provenance informed by SLSA. Targets need demonstrated evidence.

Phase 0 adds no runtime analytics, session replay, crash-upload or tracking SDK. CI tool downloads
and synthetic failure evidence are separate from application runtime telemetry. Internal audit/
operational records need explicit access/retention policies. External AI providers can collect
metadata under their own terms; destinations/settings require later verification.

| Control | Evidence location | Qualification |
|---|---|---|
| No silent production mock; safe unsupported/missing-provider errors | `test_production_configuration.py` | Deterministic regression |
| Settings/logs exclude secrets and ordinary logs exclude document/provider bodies | `test_production_configuration.py` | Deterministic regression |
| Startup/read/liveness do not initialize or publish fixtures | `test_startup_readiness.py`, `test_seed_and_pure_reads.py` | Isolated database regression |
| Missing/wrong schema fails readiness without repair | `test_startup_readiness.py` | Isolated database regression |
| Fixture commands reject deployed environments | `test_seed_and_pure_reads.py` | Deterministic regression |
| Locked dependencies and immutable CI action versions | Lock files and CI | Reproducible resolution; scan policy still required |
| New lint/type debt blocks changes | Quality scripts/ledgers | Inherited debt explicitly retained |
| Long structured output is text and cannot hide navigation | Vitest/Playwright | Synthetic component/browser evidence |
| Fresh/legacy PostgreSQL preserves required records and bindings | `test_migration_smoke.py` | Requires real PostgreSQL execution |
| Signed identity claims, exact issuer/audience, expiry and optional revocation | `test_oidc_authentication.py` | Synthetic signing keys and controlled identity provider; real SSO integration pending |
| Active client roles and authenticated reviewer identity | `test_identity_ownership.py`, `test_phase1_ownership.py` | API regression, includes spoofed reviewer and unauthorized publication |
| Parent ownership quarantine across artifacts, reviews, feedback and audit | `test_phase1_ownership.py`, `test_postgres_isolation.py` | HTTP defense plus actual PostgreSQL policy evidence |
| Non-owner runtime role, forced RLS, transaction context and pool reset | `test_postgres_isolation.py` | Actual disposable PostgreSQL; production role provisioning pending |
| Client/install/environment onboarding and permission-aware request intake | Frontend Vitest/Playwright | Synthetic APIs; no ERP connection attempted |
| Last usable administrator cannot be revoked | `test_phase1_ownership.py` | Includes inactive subjects and foreign issuers |

| Remaining control evidence | Owning phase |
|---|---|
| Live organization SSO/browser login, reviewed legacy ownership mapping, production role provisioning | 1 rollout |
| Object-link, worker-job and cache ownership | 4–5, 8–10 as these resources are implemented |
| Exact revision approvals, concurrency and late-result invalidation | 2 |
| Immutable manifests/publication/typed configuration | 3 |
| Safe uploads/OCR/archives, scoped retrieval and source treatment | 4 |
| Effective model request evidence and prompt-injection boundaries | 5 |
| AS-IS boundaries, compilation and meaningful validators | 6–7 |
| Complete immutable bundles/test sign-off | 8 |
| Secret store, scoped/revocable connections and environment permissions | 9 |
| Isolated execution, runners, reconciliation/recovery | 10 |
| Egress/privacy inventory, scans, penetration tests, restore and capacity | 11 |

The Phase 1 verification run passed 153 backend tests (including real PostgreSQL, zero skips),
24 frontend tests, strict frontend type checks, lint/build and 10 browser fixture cases.
Backend quality ratchets retain 296 Ruff and 15 mypy diagnostics from inherited modules;
the new Phase 1 files pass their direct Ruff check. These checks are insufficient to claim
production security or end-to-end ERP installation.
