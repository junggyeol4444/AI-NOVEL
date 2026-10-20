"""Local-only Korean draft format screening, not human or literary certification."""
from __future__ import annotations
from dataclasses import dataclass
import math
import re

_SENTENCES = re.compile(r'(?<=[.!?。])\s+|\r?\n+')
_WHITESPACE = re.compile(r'\s+')
_NON_LETTERS = re.compile(r'[^가-힣A-Za-z]+')
# The real Windows Qwen manuscript mixed Chinese characters, Markdown
# headings, screenplay speaker tags and model-authored introduction text.
# Treat these as format defects, not as proof of literary merit.
_HAN_SCRIPT = re.compile(r'[\u3400-\u9fff]')
# The real ARM Qwen drafts contained Cyrillic letters, Japanese Kana and a
# broken UTF-8 replacement. Those cannot become Korean prose merely because
# the remaining 95% of the chapter is Hangul. Fail closed for any occurrence.
_OTHER_SCRIPT_CORRUPTION = re.compile(
    r'[\u3040-\u30ff\u0400-\u052f\ufffd]'
    r'|[가-힣](?:[A-Za-z]{2,}|[\u0100-\u024f\u1e00-\u1eff])')
# The latest real Windows11 ARM compiled EXE Qwen artifact generated
# "### 장면 1", "**(날짜: ...)**", "**조사자:**", "**(사서)**".
# This screen must agree with the native bridge; synthetic fixtures are
# NOT literature approval. Source text is never rewritten or translated.
_SCREENPLAY_LINE = re.compile(
    r'(?m)^[ \t]*(?:#{1,6}[ \t]*(?:장면[ \t]*[0-9]+'
    r'|제[ \t]*[0-9]+화|Scene[ \t]*[0-9]+)[^\r\n]{0,80}'
    r'|\*\*[ \t]*\([^()\r\n]{1,80}\)[ \t]*\*\*'
    r'|\*\*[ \t]*[가-힣][가-힣 ]{0,24}:[ \t]*\*\*)[ \t]*$')
_NON_PROSE_LINE = re.compile(
    r'(?m)^[ \t]*(?:#{1,6}[ \t]+\S|(?:\*\*)?(?:제목|등장인물|장면|'
    r'조사를 위한 준비|사서의 설명과 검토|조사자의 선택 및 행동|작성 계획)\s*:'
    r'|\*\*(?:시작|사건|장소|인물|시간|설명|내용|결과|결론)\*\*\s*:?' 
    r'|\*\*(?:장소|인물|시간|설명|내용|결과|결론):\*\*'
    r'|<날씨\s*:[^>\r\n]{1,80}>\s*$'
    r'|<[^>\r\n]{1,30}>\s*:|[-*]{3,}[ \t]*$'
    r'|다음은 첫 회차의 장면입니다\.|안녕하세요[,.!]|저는 인공지능)')


def has_foreign_script_corruption(text: str) -> bool:
    """Screen observed foreign scripts, broken decoding and fused Latin."""
    if type(text) is not str:
        raise ValueError('draft screening input invalid')
    return bool(_HAN_SCRIPT.search(text) or _OTHER_SCRIPT_CORRUPTION.search(text))


@dataclass(frozen=True)
class KoreanDraftScreen:
    total_chars: int
    nonspace_chars: int
    hangul_syllables: int
    latin_letters: int
    hangul_share: float
    repeated_sentence_share: float
    repeated_chunk_share: float
    sentence_units: int
    han_script_chars: int
    non_prose_markers: int
    format_gate_pass: bool


def screen_korean_draft(text: str, *, target_chars: int = 5000) -> KoreanDraftScreen:
    if not isinstance(text, str) or not isinstance(target_chars, int) or isinstance(target_chars, bool):
        raise ValueError('draft screening input invalid')
    if not 1 <= target_chars <= 1_000_000 or len(text) > 100_000:
        raise ValueError('draft screening limit exceeded')
    compact = _WHITESPACE.sub('', text)
    nonspace_chars = len(compact)
    hangul = sum('가' <= ch <= '힣' for ch in compact)
    latin = sum(('a' <= ch <= 'z') or ('A' <= ch <= 'Z') for ch in compact)
    hangul_share = hangul / max(1, nonspace_chars)
    sentences = [_NON_LETTERS.sub('', p).casefold() for p in _SENTENCES.split(text)]
    sentences = [p for p in sentences if len(p) >= 16]
    repeated_sentences = 1.0 - len(set(sentences)) / max(1, len(sentences))
    normalized = _NON_LETTERS.sub('', text).casefold()
    chunks = [normalized[i:i + 40] for i in range(0, len(normalized) - 39, 40)]
    repeated_chunks = 1.0 - len(set(chunks)) / max(1, len(chunks))
    han_script_chars = len(_HAN_SCRIPT.findall(text))
    non_prose_markers = (len(_NON_PROSE_LINE.findall(text))
                         + len(_SCREENPLAY_LINE.findall(text)))
    minimum = math.ceil(target_chars * 0.9)
    passed = (nonspace_chars >= minimum and hangul >= minimum
              and hangul_share >= 0.78
              and latin <= max(5, math.ceil(nonspace_chars * 0.05))
              and repeated_sentences <= 0.12
              and repeated_chunks <= 0.15
              and not has_foreign_script_corruption(text)
              and non_prose_markers == 0
              and len(sentences) >= (10 if target_chars >= 1000 else 2))
    return KoreanDraftScreen(
        total_chars=len(text), nonspace_chars=nonspace_chars,
        hangul_syllables=hangul, latin_letters=latin,
        hangul_share=round(hangul_share, 4),
        repeated_sentence_share=round(repeated_sentences, 4),
        repeated_chunk_share=round(repeated_chunks, 4),
        sentence_units=len(sentences),
        han_script_chars=han_script_chars,
        non_prose_markers=non_prose_markers,
        format_gate_pass=passed)
