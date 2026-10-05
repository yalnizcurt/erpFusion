"""Explicit importer for the governed ERP-family draft catalogue."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AdminAuditEvent, ERPProfile, ERPProfileVersion


class CatalogueFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    vendor: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    implementation_route: str = Field(min_length=1)
    qualification_needed: str = Field(min_length=1)
    configuration: dict[str, Any]
    legacy_keys: list[str] = Field(default_factory=list)


class CatalogueManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalogue_id: str
    version: int = Field(ge=1)
    families: list[CatalogueFamily] = Field(min_length=22, max_length=22)


def read_catalogue() -> CatalogueManifest:
    payload = (
        files("app.cli").joinpath("fixtures", "erp-catalogue-v1.json").read_text(encoding="utf-8")
    )
    catalogue = CatalogueManifest.model_validate_json(payload)
    if catalogue.catalogue_id != "erp-catalogue":
        raise ValueError("Unexpected catalogue identifier")
    if len({family.key for family in catalogue.families}) != 22:
        raise ValueError("Catalogue family keys must be unique")
    return catalogue


async def import_catalogue(
    db: AsyncSession,
    *,
    catalogue: CatalogueManifest,
    actor: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Insert missing drafts only; existing profiles and versions are immutable here."""
    if not actor.strip() or len(actor) > 255:
        raise ValueError("A valid audit actor is required")
    checksum = hashlib.sha256(
        json.dumps(catalogue.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    created: list[str] = []
    skipped: list[str] = []
    for family in catalogue.families:
        existing = await db.scalar(
            select(ERPProfile).where(ERPProfile.key.in_([family.key, *family.legacy_keys])).limit(1)
        )
        if existing is not None:
            skipped.append(family.key)
            continue
        created.append(family.key)
        if dry_run:
            continue
        profile = ERPProfile(
            key=family.key,
            name=family.name,
            display_name=family.display_name,
            vendor=family.vendor,
            product_version=None,
            description=family.description,
            active=True,
            status="DRAFT",
            created_by=actor,
            updated_by=actor,
            configuration=family.configuration,
        )
        db.add(profile)
        await db.flush()
        version = ERPProfileVersion(
            profile_id=profile.id,
            version=1,
            status="DRAFT",
            supported_artifact_types=["CONTEXT_ANALYSIS", "FDD", "TDD"],
            configuration=family.configuration["profile_version"],
            created_by=actor,
            updated_by=actor,
        )
        db.add(version)
        await db.flush()
        db.add(
            AdminAuditEvent(
                actor=actor,
                action="ERP_CATALOGUE_DRAFT_IMPORTED",
                entity_type="ERPProfile",
                entity_id=profile.id,
                details={
                    "catalogue_id": catalogue.catalogue_id,
                    "catalogue_version": catalogue.version,
                    "catalogue_checksum": checksum,
                    "profile_version": version.version,
                    "key": family.key,
                },
            )
        )
    if not dry_run:
        await db.flush()
    return {
        "catalogue_id": catalogue.catalogue_id,
        "catalogue_version": catalogue.version,
        "catalogue_checksum": checksum,
        "dry_run": dry_run,
        "created": created,
        "skipped_existing": skipped,
    }


async def _import_database(*, actor: str, dry_run: bool) -> dict[str, Any]:
    from app.database import create_database_engine, create_session_factory

    settings = get_settings()
    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as db, db.begin():
            from app.security.tenant_context import apply_tenant_context

            # This explicit operator command imports registry drafts, never client content.
            await apply_tenant_context(db, client_ids=[], is_erp_admin=True)
            return await import_catalogue(
                db, catalogue=read_catalogue(), actor=actor, dry_run=dry_run
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the governed ERP draft catalogue")
    parser.add_argument("--actor", required=True, help="Audit actor for created draft records")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        result = asyncio.run(_import_database(actor=arguments.actor, dry_run=arguments.dry_run))
        print(json.dumps(result, sort_keys=True))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print(
            "Catalogue import failed; check the migrated database and connection.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
