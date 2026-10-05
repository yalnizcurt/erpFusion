"""Persist ERP files locally or in a private S3 bucket; metadata stays in SQL.

The optional AWS SDK uses its default credential chain, including deployed IAM
roles. No credential material, public URLs, or SDK error bodies are persisted.
"""

import asyncio
import os
from contextlib import closing
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings


class ArtifactStorageError(RuntimeError):
    """Safe operational storage failure without provider response details."""


def asset_directory(
    settings: Settings, profile_version_id: str, asset_id: str, version: int
) -> str:
    key = str(PurePosixPath("erp-assets", profile_version_id, asset_id, str(version)))
    if settings.artifact_storage_backend == "s3":
        return f"s3://{settings.artifact_s3_bucket}/{key}"
    return str(Path(settings.artifact_storage_path).resolve() / key)


def _s3_client(settings: Settings) -> Any:
    try:
        boto3 = import_module("boto3")
        sdk_configuration = import_module("botocore.config").Config
    except ImportError:
        raise ArtifactStorageError("artifact_storage_dependency_missing") from None
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        config=sdk_configuration(
            connect_timeout=1, read_timeout=2, retries={"total_max_attempts": 1}
        ),
    )


def assert_private_s3_bucket(settings: Settings) -> None:
    """Read bucket privacy configuration; never create a bucket or probe object."""
    try:
        with closing(_s3_client(settings)) as client:
            client.head_bucket(Bucket=settings.artifact_s3_bucket)
            flags = client.get_public_access_block(Bucket=settings.artifact_s3_bucket).get(
                "PublicAccessBlockConfiguration", {}
            )
            required = (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
            if any(flags.get(flag) is not True for flag in required):
                raise ArtifactStorageError("artifact_storage_bucket_not_private")
            try:
                policy = client.get_bucket_policy_status(Bucket=settings.artifact_s3_bucket)
            except Exception as exc:
                # Buckets without a policy remain protected by all four public
                # access blocks. Every other provider failure fails closed.
                response = getattr(exc, "response", {})
                if response.get("Error", {}).get("Code") != "NoSuchBucketPolicy":
                    raise
            else:
                if policy.get("PolicyStatus", {}).get("IsPublic") is not False:
                    raise ArtifactStorageError("artifact_storage_bucket_not_private")
    except ArtifactStorageError:
        raise
    except Exception:
        # SDK exceptions can contain response bodies, endpoint details and
        # credential-provider information. Only a stable safe code escapes.
        raise ArtifactStorageError("artifact_storage_unavailable") from None


def _save_file(
    settings: Settings, directory: str, filename: str, data: bytes, mime_type: str | None
) -> str:
    try:
        if settings.artifact_storage_backend == "s3":
            key = directory.removeprefix(f"s3://{settings.artifact_s3_bucket}/") + "/" + filename
            with closing(_s3_client(settings)) as client:
                client.put_object(
                    Bucket=settings.artifact_s3_bucket,
                    Key=key,
                    Body=data,
                    ContentType=mime_type or "application/octet-stream",
                    ServerSideEncryption="AES256",
                    IfNoneMatch="*",
                )
            return f"s3://{settings.artifact_s3_bucket}/{key}"
        destination = Path(directory) / filename
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(
            os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(data)
        return str(destination)
    except ArtifactStorageError:
        raise
    except Exception:
        raise ArtifactStorageError("artifact_storage_write_failed") from None


async def save_asset_file(
    settings: Settings, directory: str, filename: str, data: bytes, mime_type: str | None
) -> str:
    """Offload bounded SDK and filesystem work from the API event loop."""
    return await asyncio.to_thread(_save_file, settings, directory, filename, data, mime_type)


def _read_file(settings: Settings, storage_path: str, max_bytes: int) -> bytes:
    try:
        if max_bytes < 1 or max_bytes > 100 * 1024 * 1024:
            raise ArtifactStorageError("artifact_storage_limit_invalid")
        if settings.artifact_storage_backend == "s3":
            parsed = urlsplit(storage_path)
            if (
                parsed.scheme != "s3"
                or parsed.netloc != settings.artifact_s3_bucket
                or parsed.query
                or parsed.fragment
                or any(part == ".." for part in parsed.path.split("/"))
            ):
                raise ArtifactStorageError("artifact_storage_reference_invalid")
            with closing(_s3_client(settings)) as client:
                response = client.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
                with closing(response["Body"]) as body:
                    if response.get("ContentLength", 0) > max_bytes:
                        raise ArtifactStorageError("artifact_storage_limit_exceeded")
                    data = body.read(max_bytes + 1)
        else:
            base = Path(settings.artifact_storage_path).resolve()
            path = Path(storage_path).resolve()
            if not path.is_relative_to(base):
                raise ArtifactStorageError("artifact_storage_reference_invalid")
            with path.open("rb") as body:
                data = body.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ArtifactStorageError("artifact_storage_limit_exceeded")
        return data
    except ArtifactStorageError:
        raise
    except Exception:
        raise ArtifactStorageError("artifact_storage_read_failed") from None


async def read_asset_file(
    settings: Settings, storage_path: str, max_bytes: int = 10 * 1024 * 1024
) -> bytes:
    """Read only references within provisioned storage after the caller authorizes ownership."""
    return await asyncio.to_thread(_read_file, settings, storage_path, max_bytes)
