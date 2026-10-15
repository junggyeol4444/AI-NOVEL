"""Stage 20: local-only reference import integration (no network, no source persistence).

The pipeline reads a local regular file once into bounded memory, calculates the
identity of precisely those bytes, parses it, splits episodes, measures prose,
and *then* writes only metadata to the stage-19 SQLite catalog.

EPUB spine XHTML is parsed locally with strict ZIP/XML limits.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat

from ai_novel_factory.database import ReferenceCatalog, ReferenceRecord
from .basic_statistics import ReferenceStatistics, measure_reference
from .docx_parser import MAX_DOCX_BYTES, parse_docx_bytes
from .epub_parser import MAX_EPUB_BYTES, parse_epub_bytes
from .episode_splitter import split_episodes
from .pdf_parser import MAX_PDF_BYTES, parse_pdf_bytes
from .plaintext_parser import (
    MAX_REFERENCE_BYTES, ParsedReference, ReferenceParseError, _decode_source, parse_text,
)

# Do not claim EPUB support merely because its suffix is accepted by the catalog.
_LIMITS = {
    ".txt": MAX_REFERENCE_BYTES,
    ".md": MAX_REFERENCE_BYTES,
    ".markdown": MAX_REFERENCE_BYTES,
    ".docx": MAX_DOCX_BYTES,
    ".epub": MAX_EPUB_BYTES,
    ".pdf": MAX_PDF_BYTES,
}


@dataclass(frozen=True)
class ImportResult:
    """Only document statistics and registered metadata are exposed.

    In-memory ParsedReference and raw bytes are intentionally not returned.
    """

    reference: ReferenceRecord
    statistics: ReferenceStatistics


def _open_bounded(path: Path, max_bytes: int) -> bytes:
    """Check the actual opened descriptor, not just a possibly raced pathname."""
    if path.is_symlink():
        raise ReferenceParseError("심볼릭 링크 파일은 가져올 수 없습니다.")
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ReferenceParseError("일반 파일만 가져올 수 있습니다.")
            if info.st_size > max_bytes:
                raise ReferenceParseError("파일이 허용 크기를 초과했습니다.")
            raw = source.read(max_bytes + 1)
    except ReferenceParseError:
        raise
    except OSError:
        # Never expose the absolute user path in application errors.
        raise ReferenceParseError("참고소설 파일을 안전하게 읽을 수 없습니다.") from None
    if len(raw) > max_bytes:
        raise ReferenceParseError("파일이 허용 크기를 초과했습니다.")
    if not raw:
        raise ReferenceParseError("비어 있는 참고소설은 등록할 수 없습니다.")
    return raw


def _parse_bytes(raw: bytes, suffix: str, encoding: str | None) -> ParsedReference:
    if suffix in {".txt", ".md", ".markdown"}:
        decoded, used = _decode_source(raw, encoding)
        return parse_text(decoded, format="txt" if suffix == ".txt" else "markdown", encoding=used)
    if encoding is not None:
        raise ReferenceParseError("바이너리 문서에는 텍스트 인코딩을 지정할 수 없습니다.")
    if suffix == ".docx":
        return parse_docx_bytes(raw)
    if suffix == ".epub":
        return parse_epub_bytes(raw)
    if suffix == ".pdf":
        return parse_pdf_bytes(raw)
    raise ReferenceParseError("지원하지 않는 참고소설 형식입니다.")


def import_reference_file(
    path: str | Path,
    *,
    catalog: ReferenceCatalog,
    encoding: str | None = None,
    max_bytes: int | None = None,
) -> ImportResult:
    """Testable offline importer for TXT/Markdown/DOCX/PDF/EPUB into local metadata.

    Does not save the extracted text, copy the reference file, call local/remote
    AI, or contact the internet. On parser/splitter/statistics errors, the
    catalog is untouched. `max_bytes` can only tighten, never expand the limit.
    """
    if not isinstance(path, (str, Path)) or not str(path):
        raise ReferenceParseError("파일 경로가 올바르지 않습니다.")
    if not isinstance(catalog, ReferenceCatalog):
        raise ReferenceParseError("참고소설 목록 저장소가 필요합니다.")
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in _LIMITS:
        raise ReferenceParseError("지원하지 않는 참고소설 확장자입니다.")
    if max_bytes is not None and (isinstance(max_bytes, bool) or
                                  not isinstance(max_bytes, int) or max_bytes < 1):
        raise ReferenceParseError("파일 크기 제한이 올바르지 않습니다.")
    limit = min(_LIMITS[suffix], max_bytes) if max_bytes is not None else _LIMITS[suffix]
    raw = _open_bounded(source, limit)
    parsed = _parse_bytes(raw, suffix, encoding)
    split = split_episodes(parsed)
    statistics = measure_reference(parsed, split=split)
    digest = hashlib.sha256(raw).hexdigest()
    # Do not record a bad import in the catalog: validation is atomic by order.
    # `register` itself remains the authority for uniqueness and identity.
    record = catalog.register(file_name=source.name, source_format=suffix.lstrip("."),
                              byte_count=len(raw), sha256=digest)
    if record.status == "registered" or record.status == "failed":
        record = catalog.change_status(record.reference_id, "analyzing")
    if record.status == "analyzing":
        record = catalog.change_status(record.reference_id, "analyzed")
    return ImportResult(record, statistics)
