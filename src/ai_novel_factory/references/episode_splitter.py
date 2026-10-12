"""Stage 17: read-only episode segmentation of parsed reference novels."""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from .plaintext_parser import ParsedReference, ReferenceParseError

_PATTERN = re.compile(
    r"^(?:(?:제\s*)?(?P<ko>\d{1,5})\s*(?:화|회|장)"
    r"|(?P<enlabel>episode|chapter|ep\.?|ch\.?)\s*[:#._\-]?\s*(?P<en>\d{1,5}))"
    r"(?:\s*(?:[:.\-–—]\s*|\s+)(?P<title>[^\n]{1,120}))?$",
    re.IGNORECASE,
)
MAX_EPISODES = 10000

@dataclass(frozen=True)
class Episode:
    number: int
    title: str
    start_block: int
    end_block: int
    text: str = field(repr=False)

@dataclass(frozen=True)
class SplitEpisodes:
    episodes: tuple[Episode, ...] = field(repr=False)
    preface: str = field(default="", repr=False)
    detected_markers: bool = False

    @property
    def count(self) -> int:
        return len(self.episodes)

def _heading_number(text: str) -> tuple[int, str] | None:
    match = _PATTERN.fullmatch(text.strip())
    if match is None:
        return None
    number = int(match.group("ko") or match.group("en"))
    return (number, (match.group("title") or "").strip()) if number > 0 else None

def split_episodes(document: ParsedReference, *, max_episodes: int = MAX_EPISODES) -> SplitEpisodes:
    """Detect only standalone titles, preserve preface and source order."""
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("분리 가능한 문서 형식이 아닙니다.")
    if (isinstance(max_episodes, bool) or not isinstance(max_episodes, int)
            or not 1 <= max_episodes <= MAX_EPISODES):
        raise ReferenceParseError("회차 개수 제한이 올바르지 않습니다.")
    if not document.blocks:
        raise ReferenceParseError("문서에 추출된 본문이 없습니다.")
    markers: list[tuple[int, int, str]] = []
    for index, block in enumerate(document.blocks):
        if block.kind not in ("heading", "paragraph") or "\n" in block.text.strip():
            continue
        parsed = _heading_number(block.text)
        if parsed is not None:
            markers.append((index, *parsed))
    if len(markers) > max_episodes:
        raise ReferenceParseError("회차 개수가 제한을 초과했습니다.")
    if not markers:
        text = "\n\n".join(b.text for b in document.blocks)
        return SplitEpisodes((Episode(1, "1화", 0, len(document.blocks) - 1, text),), "", False)
    previous = 0
    for _, number, _ in markers:
        if number <= previous:
            raise ReferenceParseError("회차 번호가 중복되거나 순서가 올바르지 않습니다.")
        previous = number
    preface = "\n\n".join(b.text for b in document.blocks[:markers[0][0]])
    episodes: list[Episode] = []
    for pos, (start, number, subtitle) in enumerate(markers):
        end = markers[pos + 1][0] if pos + 1 < len(markers) else len(document.blocks)
        text = "\n\n".join(b.text for b in document.blocks[start + 1:end])
        episodes.append(Episode(number, subtitle or f"{number}화", start, end - 1, text))
    return SplitEpisodes(tuple(episodes), preface, True)
