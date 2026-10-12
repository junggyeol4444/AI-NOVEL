"""Stage 13: local, in-memory TXT and Markdown reference-novel parsing.

No source is copied, persisted, uploaded, logged, or sent to a model here.
This parser does not replace stage 12's comprehensive input validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

MAX_REFERENCE_BYTES = 16 * 1024 * 1024  # provisional parser safety cap
_FORMAT_BY_SUFFIX = {".txt": "txt", ".md": "markdown", ".markdown": "markdown"}
_ALLOWED_ENCODINGS = {"utf-8", "utf-8-sig", "utf-16", "cp949"}
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$")
_SETEXT_HEADING = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


class ReferenceParseError(ValueError):
    """Safe error with no original content or local path in its message."""


@dataclass(frozen=True)
class ParsedBlock:
    kind: str  # paragraph, heading, code
    start_line: int
    end_line: int
    text: str = field(repr=False)
    heading_level: int | None = None


@dataclass(frozen=True)
class ParsedReference:
    format: str
    encoding: str | None
    text: str = field(repr=False)  # transient normalized source, never log or persist
    blocks: tuple[ParsedBlock, ...] = field(repr=False)

    @property
    def paragraph_count(self) -> int:
        return sum(block.kind == "paragraph" for block in self.blocks)


def _reject_binary_text(text: str) -> None:
    if "\x00" in text or any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise ReferenceParseError("텍스트가 아닌 제어 문자가 포함되어 있습니다.")


def parse_text(text: str, *, format: str = "txt", encoding: str | None = None) -> ParsedReference:
    """Parse already-decoded content without touching disk or network.

    ``text`` retains original wording and line breaks (normalized to LF).
    Markdown heading markers are removed only from the corresponding block.
    """
    if not isinstance(text, str):
        raise ReferenceParseError("문자열 입력이 필요합니다.")
    if format not in ("txt", "markdown"):
        raise ReferenceParseError("지원하지 않는 텍스트 형식입니다.")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    _reject_binary_text(normalized)
    if not normalized.strip():
        raise ReferenceParseError("본문이 비어 있습니다.")

    lines = normalized.split("\n")
    blocks: list[ParsedBlock] = []
    paragraph: list[str] = []
    paragraph_start = 0

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraph_start
        if paragraph:
            blocks.append(ParsedBlock("paragraph", paragraph_start, paragraph_start + len(paragraph) - 1,
                                      "\n".join(paragraph)))
            paragraph = []

    i = 0
    while i < len(lines):
        line = lines[i]
        number = i + 1
        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        if format == "markdown":
            fence = _FENCE.match(line)
            if fence:
                flush_paragraph()
                marker = fence.group(1)
                content: list[str] = []
                opening = number
                i += 1
                while i < len(lines):
                    candidate = lines[i].strip()
                    if (candidate.startswith(marker[0] * len(marker))
                            and set(candidate) <= {marker[0]}):
                        i += 1
                        break
                    content.append(lines[i])
                    i += 1
                blocks.append(ParsedBlock("code", opening, i, "\n".join(content)))
                continue

            heading = _ATX_HEADING.match(line)
            if heading:
                flush_paragraph()
                heading_text = heading.group(2) or ""
                heading_text = re.sub(r"[ \t]+#+[ \t]*$", "", heading_text).strip()
                blocks.append(ParsedBlock("heading", number, number, heading_text, len(heading.group(1))))
                i += 1
                continue

            if (i + 1 < len(lines) and _SETEXT_HEADING.match(lines[i + 1])
                    and line.strip() and not paragraph):
                marker = lines[i + 1].strip()[0]
                blocks.append(ParsedBlock("heading", number, number + 1, line.strip(),
                                          1 if marker == "=" else 2))
                i += 2
                continue

        if not paragraph:
            paragraph_start = number
        paragraph.append(line)
        i += 1
    flush_paragraph()
    return ParsedReference(format, encoding, normalized, tuple(blocks))


def _decode_source(raw: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding is not None:
        encoding = encoding.lower().replace("_", "-")
        if encoding not in _ALLOWED_ENCODINGS:
            raise ReferenceParseError("허용되지 않은 인코딩입니다.")
        chosen = encoding
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        chosen = "utf-16"
    else:
        chosen = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        return raw.decode(chosen, errors="strict"), chosen
    except (UnicodeError, LookupError):
        raise ReferenceParseError("텍스트 디코딩에 실패했습니다. 인코딩을 명시하세요.") from None


def parse_reference_file(
    path: str | Path, *, encoding: str | None = None,
    max_bytes: int = MAX_REFERENCE_BYTES,
) -> ParsedReference:
    """Read only a bounded local TXT/MD file, without writing or publishing it.

    Stage 12 must later provide independent file identity, hash and policy checks.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in _FORMAT_BY_SUFFIX:
        raise ReferenceParseError("TXT/Markdown 확장자만 지원합니다.")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ReferenceParseError("파일 크기 제한이 올바르지 않습니다.")
    if source.is_symlink():
        raise ReferenceParseError("심볼릭 링크 파일은 허용하지 않습니다.")
    try:
        with source.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        raise ReferenceParseError("파일을 읽을 수 없습니다.") from None
    if len(raw) > max_bytes:
        raise ReferenceParseError("파일이 허용 크기를 초과했습니다.")
    decoded, used_encoding = _decode_source(raw, encoding)
    return parse_text(decoded, format=_FORMAT_BY_SUFFIX[suffix], encoding=used_encoding)