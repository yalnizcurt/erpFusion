"""Bounded local document extraction. Uploaded code, macros and links are never executed."""

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_UPLOAD = 10 * 1024 * 1024
MAX_TEXT = 500000
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def extract_document(data: bytes, extension: str) -> tuple[str, str | None]:
    if len(data) > MAX_UPLOAD:
        return "", "UPLOAD_TOO_LARGE"
    try:
        if extension in {".txt", ".md"}:
            text = data.decode("utf-8-sig")
            if "\x00" in text:
                return "", "DOCUMENT_ENCODING_UNSUPPORTED"
        elif extension == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 1000
                    or sum(item.file_size for item in entries) > 20 * 1024 * 1024
                    or any(
                        item.flag_bits & 1 or item.file_size / max(1, item.compress_size) > 200
                        for item in entries
                    )
                ):
                    return "", "DOCUMENT_ARCHIVE_LIMIT_EXCEEDED"
                if any(
                    ".." in Path(item.filename).parts or item.filename.startswith("/")
                    for item in entries
                ):
                    return "", "DOCUMENT_ARCHIVE_UNSAFE"
                if "word/vbaProject.bin" in archive.namelist():
                    return "", "DOCUMENT_MACROS_FORBIDDEN"
                xml = archive.read("word/document.xml")
                if b"\x00" in xml or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    return "", "DOCUMENT_XML_UNSAFE"
                root = ElementTree.fromstring(xml)
                namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                text = "\n".join(
                    "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
                    for paragraph in root.iter(namespace + "p")
                )
        elif extension == ".pdf":
            if not data.startswith(b"%PDF-"):
                return "", "DOCUMENT_FORMAT_INVALID"
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                return "", "DOCUMENT_ENCRYPTED"
            if len(reader.pages) > 500:
                return "", "DOCUMENT_PAGE_LIMIT_EXCEEDED"
            parts = []
            length = 0
            for page in reader.pages:
                part = page.extract_text() or ""
                length += len(part)
                if length > MAX_TEXT:
                    return "", "DOCUMENT_TEXT_LIMIT_EXCEEDED"
                parts.append(part)
            text = "\n".join(parts)
        else:
            return "", "DOCUMENT_FORMAT_UNSUPPORTED"
        if len(text) > MAX_TEXT:
            return "", "DOCUMENT_TEXT_LIMIT_EXCEEDED"
        if not text.strip():
            return "", "OCR_REQUIRED" if extension == ".pdf" else "DOCUMENT_EMPTY"
        return text.strip(), None
    except ImportError:
        return "", "DOCUMENT_PARSER_UNAVAILABLE"
    except Exception:
        return "", "DOCUMENT_FORMAT_INVALID"


def _isolated_extract(data: bytes, extension: str) -> tuple[str, str | None]:
    try:
        result = subprocess.run(
            [sys.executable, "-I", __file__, extension],
            input=data,
            capture_output=True,
            timeout=20,
            check=False,
            env={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode != 0 or len(result.stdout) > 4 * 1024 * 1024:
            return "", "DOCUMENT_PARSER_FAILED"
        payload = json.loads(result.stdout)
        if not isinstance(payload.get("text"), str) or len(payload["text"]) > MAX_TEXT:
            return "", "DOCUMENT_PARSER_FAILED"
        return payload["text"], payload.get("error")
    except subprocess.TimeoutExpired:
        return "", "DOCUMENT_PARSER_TIMEOUT"
    except Exception:
        return "", "DOCUMENT_PARSER_FAILED"


async def parse_document(data: bytes, extension: str) -> tuple[str, str | None]:
    return await asyncio.to_thread(_isolated_extract, data, extension)


def _scan(data: bytes, command: list[str], timeout: float) -> str:
    if not command:
        return "NOT_CONFIGURED"
    if not Path(command[0]).is_absolute():
        return "UNAVAILABLE"
    try:
        with tempfile.TemporaryDirectory(prefix="erpfusion-scan-") as directory:
            filename = Path(directory) / "document"
            filename.write_bytes(data)
            filename.chmod(0o600)
            result = subprocess.run(
                [*command, str(filename)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                env={"PATH": os.defpath},
            )
            return (
                "CLEAN"
                if result.returncode == 0
                else "INFECTED"
                if result.returncode == 1
                else "UNAVAILABLE"
            )
    except Exception:
        return "UNAVAILABLE"


async def scan_document(data: bytes, command: list[str], timeout: float) -> str:
    return await asyncio.to_thread(_scan, data, command, timeout)


if __name__ == "__main__":
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    parsed_text, parsed_error = extract_document(sys.stdin.buffer.read(MAX_UPLOAD + 1), sys.argv[1])
    print(json.dumps({"text": parsed_text, "error": parsed_error}))
