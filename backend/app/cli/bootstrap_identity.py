"""One-time first-administrator bootstrap using a separate migration connection."""

import argparse
import asyncio
import os
import sys

from sqlalchemy import func, select, text

from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.models import IdentitySubject, PlatformRoleAssignment
from app.security.identity import Identity
from app.security.tenant_context import apply_tenant_context
from app.services.ownership_audit import record_ownership_event


async def bootstrap(settings: Settings, *, issuer: str, subject: str) -> str:
    """Provision exactly the first administrator; no token claim grants privileges."""
    if issuer != settings.oidc_issuer or not issuer or not subject.strip() or len(subject) > 255:
        raise ValueError("Use the configured issuer and a valid stable subject")
    migration_url = os.environ.get("MIGRATION_DATABASE_URL")
    if settings.is_production and not migration_url:
        raise ValueError("A separate MIGRATION_DATABASE_URL is required")
    configuration = settings.model_copy(
        update={
            "database_url": Settings.normalize_async_database_url(
                migration_url or settings.database_url
            )
        }
    )
    engine = create_database_engine(configuration)
    try:
        factory = create_session_factory(engine)
        async with factory() as db, db.begin():
            await apply_tenant_context(db, client_ids=[], is_platform_admin=True)
            if engine.dialect.name == "postgresql":
                await db.execute(text("SELECT pg_advisory_xact_lock(769398001)"))
            existing = await db.scalar(
                select(func.count())
                .select_from(PlatformRoleAssignment)
                .where(
                    PlatformRoleAssignment.role == "PLATFORM_ADMIN",
                    PlatformRoleAssignment.status == "ACTIVE",
                )
            )
            if existing:
                raise ValueError(
                    "First administrator already exists; use authenticated role administration"
                )
            principal = (
                await db.execute(
                    select(IdentitySubject).where(
                        IdentitySubject.issuer == issuer, IdentitySubject.subject == subject.strip()
                    )
                )
            ).scalar_one_or_none()
            if principal is None:
                principal = IdentitySubject(issuer=issuer, subject=subject.strip())
                db.add(principal)
                await db.flush()
            if principal.status != "ACTIVE":
                raise ValueError("Cannot bootstrap an inactive identity")
            assignment = PlatformRoleAssignment(
                subject_id=principal.id, role="PLATFORM_ADMIN", created_by_subject_id=principal.id
            )
            db.add(assignment)
            await db.flush()
            actor = Identity(user_id=principal.subject, issuer=issuer, subject_id=principal.id)
            await record_ownership_event(
                db,
                actor,
                "FIRST_ADMIN_BOOTSTRAPPED",
                "PlatformRoleAssignment",
                assignment.id,
                details={"subject_id": principal.id},
            )
            return principal.id
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap the first HighStudio platform administrator"
    )
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    arguments = parser.parse_args(argv)
    try:
        subject_id = asyncio.run(
            bootstrap(get_settings(), issuer=arguments.issuer, subject=arguments.subject)
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print(
            "Bootstrap failed; check the migrated schema and administration connection.",
            file=sys.stderr,
        )
        return 1
    print(f"First administrator provisioned: {subject_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
