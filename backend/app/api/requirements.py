"""Authorized requirement intake, source download and immutable input history."""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import ensure_project_mutation
from app.config import Settings, get_settings
from app.database import get_db
from app.models import ProjectInputRevision, RequirementDocument
from app.security.access import get_authorized_project, resolved_identity
from app.security.identity import Identity, get_current_identity
from app.services.artifact_storage import ArtifactStorageError, read_asset_file, save_asset_file
from app.services.ownership_audit import actor_subject, record_ownership_event
from app.services.project_revisions import lock_project, revise_inputs
from app.services.requirement_ingestion import MAX_UPLOAD, MIME_TYPES, parse_document, scan_document

router = APIRouter(prefix="/api/projects", tags=["Requirements"])


def document_response(document: RequirementDocument) -> dict:
    return {
        name: getattr(document, name)
        for name in (
            "id",
            "filename",
            "mime_type",
            "size_bytes",
            "checksum",
            "extraction_status",
            "extracted_text",
            "extraction_error",
            "scan_status",
            "requirement_version",
            "created_at",
        )
    }


@router.get("/{project_id}/requirements")
async def list_documents(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[dict]:
    project = await get_authorized_project(project_id, db, identity)
    documents = (
        await db.scalars(
            select(RequirementDocument)
            .where(
                RequirementDocument.project_id == project.id,
                RequirementDocument.client_id.is_not_distinct_from(project.client_id),
            )
            .order_by(RequirementDocument.created_at.desc())
            .limit(100)
        )
    ).all()
    return [document_response(item) for item in documents]


@router.post("/{project_id}/requirements", status_code=201)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    expected_requirement_version: int = Form(...),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = await get_authorized_project(project_id, db, identity)
    actor = resolved_identity(identity)
    await ensure_project_mutation(db, actor, project)
    filename = Path((file.filename or "").replace("\\", "/")).name
    filename = "".join(character for character in filename if ord(character) >= 32)[:255]
    extension = Path(filename).suffix.lower()
    if extension not in MIME_TYPES:
        raise HTTPException(422, "Upload PDF, DOCX, TXT or Markdown requirements")
    data = await file.read(MAX_UPLOAD + 1)
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Document must be between 1 byte and 10 MB")
    # Parse/scan before taking a project lock. Recheck the version after processing.
    scanned = await scan_document(
        data, settings.requirement_scan_command, settings.requirement_scan_timeout_seconds
    )
    if scanned == "INFECTED":
        raise HTTPException(422, "DOCUMENT_SCAN_REJECTED")
    error: str | None
    if scanned == "UNAVAILABLE" or settings.is_production and scanned != "CLEAN":
        text, error = "", "DOCUMENT_SCAN_REQUIRED"
    else:
        text, error = await parse_document(data, extension)
    await lock_project(db, project)
    if expected_requirement_version != project.requirement_version:
        raise HTTPException(409, "Requirements changed. Reload before uploading.")
    combined = "\n\n".join(
        part
        for part in [project.business_requirement, f"Source: {filename}\n{text}" if text else ""]
        if part
    )
    if len(combined) > 500000:
        text, error = "", "REQUIREMENT_TEXT_LIMIT_EXCEEDED"
    document_id = str(uuid.uuid4())
    key = f"client-documents/{project.client_id or 'legacy'}/{project.id}/{document_id}"
    directory = (
        f"s3://{settings.artifact_s3_bucket}/{key}"
        if settings.artifact_storage_backend == "s3"
        else str(Path(settings.artifact_storage_path).resolve() / key)
    )
    try:
        storage = await save_asset_file(
            settings, directory, "source" + extension, data, MIME_TYPES[extension]
        )
    except ArtifactStorageError:
        raise HTTPException(503, "DOCUMENT_STORAGE_UNAVAILABLE") from None
    subject = await actor_subject(db, actor)
    if text and not error:
        await revise_inputs(
            db,
            project,
            subject,
            requirement=combined,
            expected_requirement_version=expected_requirement_version,
        )
    document = RequirementDocument(
        id=document_id,
        project_id=project.id,
        client_id=project.client_id,
        filename=filename,
        mime_type=MIME_TYPES[extension],
        size_bytes=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        storage_path=storage,
        extraction_status="BLOCKED" if error else "READY",
        extracted_text=text,
        extraction_error=error,
        scan_status=scanned,
        requirement_version=project.requirement_version,
        created_by_subject_id=subject,
    )
    db.add(document)
    await db.flush()
    await record_ownership_event(
        db,
        actor,
        "REQUIREMENT_DOCUMENT_ADDED",
        "RequirementDocument",
        document.id,
        client_id=project.client_id,
        details={
            "checksum": document.checksum,
            "status": document.extraction_status,
            "scan_status": scanned,
            "requirement_version": project.requirement_version,
        },
    )
    return document_response(document)


@router.get("/{project_id}/requirements/{document_id}/download")
async def download_document(
    project_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = await get_authorized_project(project_id, db, identity)
    document = await db.get(RequirementDocument, document_id)
    if (
        document is None
        or document.project_id != project.id
        or document.client_id != project.client_id
    ):
        raise HTTPException(404, "Requirement document not found")
    if document.scan_status != "CLEAN" and not (
        settings.is_development and document.scan_status == "NOT_CONFIGURED"
    ):
        raise HTTPException(409, "Document quarantined")
    try:
        data = await read_asset_file(settings, document.storage_path, MAX_UPLOAD)
    except ArtifactStorageError:
        raise HTTPException(503, "DOCUMENT_STORAGE_UNAVAILABLE") from None
    if hashlib.sha256(data).hexdigest() != document.checksum:
        raise HTTPException(409, "DOCUMENT_CHECKSUM_MISMATCH")
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="requirement-{document.id}{Path(document.filename).suffix}"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{project_id}/input-revisions")
async def input_history(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[dict]:
    project = await get_authorized_project(project_id, db, identity)
    rows = (
        await db.scalars(
            select(ProjectInputRevision)
            .where(
                ProjectInputRevision.project_id == project.id,
                ProjectInputRevision.client_id.is_not_distinct_from(project.client_id),
            )
            .order_by(ProjectInputRevision.revision.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": row.id,
            "revision": row.revision,
            "snapshot": row.snapshot,
            "created_at": row.created_at,
        }
        for row in rows
    ]
