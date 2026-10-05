"""Requirement document parsing stays bounded and treats uploads as data."""

import io
import zipfile

import pytest
from pypdf import PdfWriter

from app.services.requirement_ingestion import (
    MAX_TEXT,
    MAX_UPLOAD,
    extract_document,
    parse_document,
)


def make_docx(document_xml: bytes, extra: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        for name, contents in (extra or {}).items():
            archive.writestr(name, contents)
    return buffer.getvalue()


def make_pdf(*, pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password:
        writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_text_parser_handles_utf8_bom_and_rejects_unsupported_bytes():
    assert extract_document(b"\xef\xbb\xbfRequirement", ".txt") == ("Requirement", None)
    assert extract_document(b"bad\xff", ".txt")[1] == "DOCUMENT_FORMAT_INVALID"
    assert extract_document(b"bad\x00text", ".md")[1] == "DOCUMENT_ENCODING_UNSUPPORTED"
    assert extract_document(b"x" * (MAX_UPLOAD + 1), ".txt")[1] == "UPLOAD_TOO_LARGE"
    assert extract_document(b"x" * (MAX_TEXT + 1), ".txt")[1] == "DOCUMENT_TEXT_LIMIT_EXCEEDED"
    assert extract_document(b"text", ".exe")[1] == "DOCUMENT_FORMAT_UNSUPPORTED"


def test_docx_extracts_text_and_rejects_unsafe_archives():
    namespace = b"http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        b'<w:document xmlns:w="' + namespace + b'"><w:body><w:p><w:r><w:t>Map suppliers</w:t>'
        b'</w:r></w:p><w:p><w:r><w:t> nightly</w:t></w:r></w:p></w:body></w:document>'
    )
    assert extract_document(make_docx(document), ".docx") == ("Map suppliers\n nightly", None)
    assert extract_document(make_docx(document, {"../outside.txt": b"x"}), ".docx")[1] == (
        "DOCUMENT_ARCHIVE_UNSAFE"
    )
    assert extract_document(make_docx(document, {"word/vbaProject.bin": b"macro"}), ".docx")[1] == (
        "DOCUMENT_MACROS_FORBIDDEN"
    )
    unsafe_xml = b'<!DOCTYPE doc [<!ENTITY x "expanded">]><doc>&x;</doc>'
    assert extract_document(make_docx(unsafe_xml), ".docx")[1] == "DOCUMENT_XML_UNSAFE"


def test_docx_rejects_high_ratio_archive_before_reading_xml():
    compressed = make_docx(b"<doc>" + b"a" * 100_000 + b"</doc>")
    assert extract_document(compressed, ".docx")[1] == "DOCUMENT_ARCHIVE_LIMIT_EXCEEDED"


def test_pdf_parser_checks_format_encryption_and_page_limit():
    assert extract_document(b"not a pdf", ".pdf")[1] == "DOCUMENT_FORMAT_INVALID"
    assert extract_document(make_pdf(password="secret"), ".pdf")[1] == "DOCUMENT_ENCRYPTED"
    assert extract_document(make_pdf(), ".pdf")[1] == "OCR_REQUIRED"
    assert extract_document(make_pdf(pages=501), ".pdf")[1] == "DOCUMENT_PAGE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_isolated_parser_returns_text_for_supported_upload():
    assert await parse_document(b"Requirement from upload", ".txt") == (
        "Requirement from upload",
        None,
    )
