"""Stage 17: split parsed novel documents into episodes without altering the text.

Works entirely in memory and never copies, saves, logs, or uploads source novels.
Only explicitly marked episode titles are accepted; unrelated prose is never
split using vague numerical or semantic guesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .plaintext_parser import ParsedReference, ReferenceParseError

# Must be an entire standalone line. Chapter markers and episode markers are
# both supported, but a bare number or a mention within a sentence is not.
_EPISODE_HEADING = re.compile(
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
    # Do not parse arbitrary sentences as episode titles.
    match = _EPISODE_HEADING.fullmatch(text.strip())
    if match is None:
        return None
    number = int(match.group("ko") or match.group("en"))
    if number == 0:
        return None
    return number, (match.group("title") or "").strip()


def split_episodes(document: ParsedReference, *, max_episodes: int = MAX_EPISODES) -> SplitEpisodes:
    """Split a ParsedReference by explicit standalone episode/chapter headings.

    PDF uses page positions but the splitter uses block order only, so no line
    numbering assumptions are made. A heading block always counts; paragraph
    blocks count only if they consist of one standalone heading line. Code
    blocks never count. Non-monotonic/repeated episode numbers are rejected
    instead of silently losing or reordering source text.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("분리 가능한 문서 형식이 아닙니다.")
    if isinstance(max_episodes, bool) or not isinstance(max_episodes, int) or not 1 <= max_episodes <= MAX_EPISODES:
        raise ReferenceParseError("회차 개수 제한이 올바르지 않습니다.")
    if not document.blocks:
        raise ReferenceParseError("문서에 추출된 본문이 없습니다.")

    # Never split a line embedded in a longer multi-line paragraph or code.
    markers: list[tuple[int, int, str]] = []
    for index, block in enumerate(document.blocks):
        if block.kind not in ("heading", "paragraph"):
            continue
        if "\n" in block.text.strip():
            continue
        parsed = _heading_number(block.text)
        if parsed is not None:
            markers.append((index, *parsed))
    if len(markers) > max_episodes:
        raise ReferenceParseError("회차 개수가 제한을 초과했습니다.")

    if not markers:
        body = "\n\n".join(block.text for block in document.blocks)
        return SplitEpisodes((Episode(1, "1화", 0, len(document.blocks) - 1, body),), "", False)

    previous = 0
    for _, number, _ in markers:
        if number <= previous:
            raise ReferenceParseError("회차 번호가 중복되거나 순서가 올바르지 않습니다.")
        previous = number

    preface = "\n\n".join(block.text for block in document.blocks[:markers[0][0]])
    episodes: list[Episode] = []
    for pos, (start_idx, number, subtitle) in enumerate(markers):
        end_exclusive = markers[pos + 1][0] if pos + 1 < len(markers) else len(document.blocks)
        body_blocks = document.blocks[start_idx + 1:end_exclusive]
        text = "\n\n".join(block.text for block in body_blocks)
        episodes.append(Episode(number, subtitle or f"{number}화", start_idx, end_exclusive - 1, text))
    return SplitEpisodes(tuple(episodes), preface, True)
