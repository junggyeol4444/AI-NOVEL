"""Stage 15: bounded, local-only DOCX text extraction.

The returned original text is transient: callers must not log, persist, send to
AI, or reuse passages in a new novel. This module neither extracts ZIP members
onto disk nor resolves external hyperlinks. Stage 12's input/hash validation is
still a separate, not-yet-integrated prerequisite.
"""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import re
import stat
from zipfile import BadZipFile, ZipFile

from .plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

MAX_DOCX_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1024
MAX_TEXT_CHARS = 2_000_000
MAX_BLOCKS = 50_000
_HEADING_NAME = re.compile(r"^(?:heading|제목)\s*([1-6])$", re.IGNORECASE)


def _validate_docx_archive(raw: bytes) -> None:
    """Reject malformed, encrypted, or unbounded OOXML containers before parsing."""
    try:
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
                raise ReferenceParseError("DOCX 압축 항목 수가 허용 범위를 벗어났습니다.")
            total = 0
            names: set[str] = set()
            for item in infos:
                name = item.filename
                parts = PurePosixPath(name).parts
                if (not name or name.startswith(("/", "\\")) or "\\" in name
                        or ".." in parts or ":" in name or name in names):
                    raise ReferenceParseError("DOCX 내부 경로가 안전하지 않습니다.")
                names.add(name)
                if item.flag_bits & 0x1:
                    raise ReferenceParseError("암호화된 DOCX는 지원하지 않습니다.")
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ReferenceParseError("DOCX 내부 링크는 허용하지 않습니다.")
                if item.file_size > MAX_MEMBER_BYTES:
                    raise ReferenceParseError("DOCX 내부 항목이 너무 큽니다.")
                total += item.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ReferenceParseError("DOCX 압축 해제 크기 제한을 초과했습니다.")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise ReferenceParseError("DOCX 필수 구성요소가 없습니다.")
            if "word/vbaProject.bin" in names:
                raise ReferenceParseError("매크로 포함 문서는 지원하지 않습니다.")
    except (BadZipFile, OSError, EOFError):
        raise ReferenceParseError("DOCX 압축 파일을 읽을 수 없습니다.") from None


def _heading_level(paragraph: object) -> int | None:
    style = getattr(paragraph, "style", None)
    if style is None:
        return None
    for value in (getattr(style, "style_id", ""), getattr(style, "name", "")):
        match = _HEADING_NAME.match(value or "")
        if match:
            return int(match.group(1))
    return None


def _table_text(table: object) -> str:
    """Flatten rows in order; tabs delimit cells and newlines delimit rows."""
    rows: list[str] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            # Paragraph order inside each cell; ignore nested tables at this stage.
            cell_text = "\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
            cells.append(cell_text)
        rows.append("\t".join(cells))
    return "\n".join(rows).strip()


def parse_docx_bytes(
    raw: bytes, *, max_text_chars: int = MAX_TEXT_CHARS,
) -> ParsedReference:
    """Parse an in-memory .docx with ordered body paragraphs and tables.

    ParsedBlock.start_line/end_line are *sequential document-block indices* for
    DOCX, not Word page/line numbers. Headers, footers, comments, revisions,
    drawings, embedded objects, and nested tables are not extracted.
    """
    if not isinstance(raw, bytes) or not raw:
        raise ReferenceParseError("DOCX 바이트 입력이 필요합니다.")
    if len(raw) > MAX_DOCX_BYTES:
        raise ReferenceParseError("DOCX 파일이 허용 크기를 초과했습니다.")
    if (not isinstance(max_text_chars, int) or isinstance(max_text_chars, bool)
            or max_text_chars < 1):
        raise ReferenceParseError("본문 길이 제한이 올바르지 않습니다.")
    _validate_docx_archive(raw)
    try:
        from docx import Document
    except ImportError:
        raise ReferenceParseError("DOCX 처리를 위해 python-docx 설치가 필요합니다.") from None

    try:
        document = Document(BytesIO(raw))
        blocks: list[ParsedBlock] = []
        total_chars = 0
        for item in document.iter_inner_content():
            if len(blocks) >= MAX_BLOCKS:
                raise ReferenceParseError("DOCX 본문 블록 수 제한을 초과했습니다.")
            if hasattr(item, "rows"):
                kind = "table"
                content = _table_text(item)
                heading_level = None
            else:
                content = item.text.strip()
                heading_level = _heading_level(item)
                kind = "heading" if heading_level is not None else "paragraph"
            if not content:
                continue
            total_chars += len(content)
            if total_chars > max_text_chars:
                raise ReferenceParseError("DOCX 본문 길이 제한을 초과했습니다.")
            index = len(blocks) + 1
            blocks.append(ParsedBlock(kind, index, index, content, heading_level))
    except ReferenceParseError:
        raise
    except Exception:
        # python-docx may raise errors containing local paths or source text.
        raise ReferenceParseError("DOCX 본문을 안전하게 해석할 수 없습니다.") from None
    if not blocks:
        raise ReferenceParseError("DOCX 본문이 비어 있습니다.")
    text = "\n\n".join(block.text for block in blocks)
    return ParsedReference("docx", None, text, tuple(blocks))


def parse_docx_file(
    path: str | Path, *, max_bytes: int = MAX_DOCX_BYTES,
    max_text_chars: int = MAX_TEXT_CHARS,
) -> ParsedReference:
    """Read a local DOCX without modifying it; never send data over a network."""
    source = Path(path)
    if source.suffix.lower() != ".docx":
        raise ReferenceParseError("DOCX 확장자만 지원합니다.")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not (1 <= max_bytes <= MAX_DOCX_BYTES):
        raise ReferenceParseError("파일 크기 제한이 올바르지 않습니다.")
    if source.is_symlink():
        raise ReferenceParseError("심볼릭 링크 파일은 허용하지 않습니다.")
    try:
        # O_NOFOLLOW (where available) reduces symlink substitution races.
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(source, flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ReferenceParseError("일반 파일만 읽을 수 있습니다.")
            raw = stream.read(max_bytes + 1)
    except ReferenceParseError:
        raise
    except OSError:
        raise ReferenceParseError("DOCX 파일을 읽을 수 없습니다.") from None
    if len(raw) > max_bytes:
        raise ReferenceParseError("DOCX 파일이 허용 크기를 초과했습니다.")
    return parse_docx_bytes(raw, max_text_chars=max_text_chars)