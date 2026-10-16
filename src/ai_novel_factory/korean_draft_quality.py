"""Local-only Korean draft format screening, not human or literary certification."""
from __future__ import annotations
from dataclasses import dataclass
import math
import re

_SENTENCES = re.compile(r'(?<=[.!?。])\s+|\r?\n+')
_WHITESPACE = re.compile(r'\s+')
_NON_LETTERS = re.compile(r'[^가-힣A-Za-z]+')


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
    minimum = math.ceil(target_chars * 0.9)
    passed = (nonspace_chars >= minimum and hangul >= minimum
              and hangul_share >= 0.78
              and latin <= max(5, math.ceil(nonspace_chars * 0.05))
              and repeated_sentences <= 0.12
              and repeated_chunks <= 0.15
              and len(sentences) >= (10 if target_chars >= 1000 else 2))
    return KoreanDraftScreen(
        total_chars=len(text), nonspace_chars=nonspace_chars,
        hangul_syllables=hangul, latin_letters=latin,
        hangul_share=round(hangul_share, 4),
        repeated_sentence_share=round(repeated_sentences, 4),
        repeated_chunk_share=round(repeated_chunks, 4),
        sentence_units=len(sentences),
        format_gate_pass=passed)
