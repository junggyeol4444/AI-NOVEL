"""PDF parser (stage 16): bounded, local, read-only text extraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import os
from pathlib import Path
import re
import stat

from .plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGES = 500
MAX_TEXT_CHARS = 2_000_000
MAX_PAGE_TEXT_CHARS = 100_000
MAX_BLOCKS = 50_000


@dataclass(frozen=True)
class ParsedPdfReference(ParsedReference):
    page_count: int = 0
    image_only_pages: tuple[int, ...] = field(default_factory=tuple)
    empty_pages: tuple[int, ...] = field(default_factory=tuple)


def _positive_bounded(value: int, maximum: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= maximum):
        raise ReferenceParseError(f"{label}이(가) 올바르지 않습니다.")
    return value


def _has_images(page: object) -> bool:
    try:
        return bool(page.images)
    except Exception:
        return False


def _page_paragraphs(page_text: str) -> list[str]:
    cleaned = page_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    if "\x00" in cleaned:
        raise ReferenceParseError("PDF 본문에서 잘못된 제어 문자를 발견했습니다.")
    return [p.strip() for p in re.split(r"\n[ \t]*\n+", cleaned) if p.strip()]


def parse_pdf_bytes(
    raw: bytes,
    *,
    max_pages: int = MAX_PAGES,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_page_text_chars: int = MAX_PAGE_TEXT_CHARS,
) -> ParsedPdfReference:
    if not isinstance(raw, bytes) or not raw:
        raise ReferenceParseError("PDF 바이트 입력이 필요합니다.")
    if len(raw) > MAX_PDF_BYTES:
        raise ReferenceParseError("PDF 파일이 허용 크기를 초과했습니다.")
    if not raw.startswith(b"%PDF-"):
        raise ReferenceParseError("올바른 PDF 파일 헤더가 없습니다.")
    _positive_bounded(max_pages, MAX_PAGES, "페이지 수 제한")
    _positive_bounded(max_text_chars, MAX_TEXT_CHARS, "본문 길이 제한")
    _positive_bounded(max_page_text_chars, MAX_PAGE_TEXT_CHARS, "페이지 본문 제한")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ReferenceParseError("PDF 처리를 위해 pypdf 설치가 필요합니다.") from None
    try:
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise ReferenceParseError("암호화된 PDF는 지원하지 않습니다.")
        page_count = len(reader.pages)
        if page_count < 1:
            raise ReferenceParseError("PDF 페이지가 없습니다.")
        if page_count > max_pages:
            raise ReferenceParseError("PDF 페이지 수 제한을 초과했습니다.")
        blocks: list[ParsedBlock] = []
        image_pages: list[int] = []
        empty_pages: list[int] = []
        total_chars = 0
        for number, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text(extraction_mode="plain") or ""
            if not isinstance(extracted, str):
                raise ReferenceParseError("PDF 텍스트 추출 결과가 올바르지 않습니다.")
            if len(extracted) > max_page_text_chars:
                raise ReferenceParseError("PDF 페이지 본문 길이 제한을 초과했습니다.")
            paragraphs = _page_paragraphs(extracted)
            if not paragraphs:
                (image_pages if _has_images(page) else empty_pages).append(number)
                continue
            for paragraph in paragraphs:
                if len(blocks) >= MAX_BLOCKS:
                    raise ReferenceParseError("PDF 본문 블록 수 제한을 초과했습니다.")
                total_chars += len(paragraph)
                if total_chars > max_text_chars:
                    raise ReferenceParseError("PDF 전체 본문 길이 제한을 초과했습니다.")
                blocks.append(ParsedBlock("paragraph", number, number, paragraph))
        if not blocks:
            if image_pages:
                raise ReferenceParseError("이미지 기반 PDF로 텍스트를 추출할 수 없습니다. OCR이 필요합니다.")
            raise ReferenceParseError("PDF에서 추출할 수 있는 텍스트가 없습니다.")
        return ParsedPdfReference(
            format="pdf", encoding=None,
            text="\n\n".join(block.text for block in blocks), blocks=tuple(blocks),
            page_count=page_count, image_only_pages=tuple(image_pages),
            empty_pages=tuple(empty_pages),
        )
    except ReferenceParseError:
        raise
    except Exception:
        raise ReferenceParseError("PDF 파일을 안전하게 해석할 수 없습니다.") from None


def parse_pdf_file(
    path: str | Path,
    *,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PAGES,
    max_text_chars: int = MAX_TEXT_CHARS,
    max_page_text_chars: int = MAX_PAGE_TEXT_CHARS,
) -> ParsedPdfReference:
    source = Path(path)
    if source.suffix.lower() != ".pdf":
        raise ReferenceParseError("PDF 확장자만 지원합니다.")
    _positive_bounded(max_bytes, MAX_PDF_BYTES, "파일 크기 제한")
    if source.is_symlink():
        raise ReferenceParseError("심볼릭 링크 PDF는 허용하지 않습니다.")
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(source, flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ReferenceParseError("일반 파일만 읽을 수 있습니다.")
            raw = stream.read(max_bytes + 1)
    except ReferenceParseError:
        raise
    except OSError:
        raise ReferenceParseError("PDF 파일을 읽을 수 없습니다.") from None
    if len(raw) > max_bytes:
        raise ReferenceParseError("PDF 파일이 허용 크기를 초과했습니다.")
    return parse_pdf_bytes(
        raw, max_pages=max_pages, max_text_chars=max_text_chars,
        max_page_text_chars=max_page_text_chars,
    )
