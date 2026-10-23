"""저장 초고와 최종본의 문단 단위 변경 근거를 읽기 전용으로 계산한다.

문단 일치 여부는 초고의 표현이 남았는지 확인하는 편집 보조 지표이며
문학 품질, 원고 완성, QC 합격 또는 출판 승인 판단에 사용할 수 없다.
원문과 문단 지문은 반환하거나 파일로 저장하지 않는다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import re


@dataclass(frozen=True)
class ChapterTextDelta:
    draft_nonspace_chars: int
    final_nonspace_chars: int
    draft_paragraphs: int
    final_paragraphs: int
    retained_paragraphs: int
    removed_or_rewritten: int
    new_or_rewritten: int
    retained_percent: int
    status: str = 'AUTHOR_MANUAL_COMPARISON_REQUIRED'
    publication_approved: bool = False


def _paragraph_counts(text: str) -> Counter[str]:
    """공백만 바뀐 문단은 동일하게 취급하되 중복 문단은 개별 집계한다."""
    counts: Counter[str] = Counter()
    for paragraph in re.split(r'\n\s*\n|\n', text):
        normalized = re.sub(r'\s+', ' ', paragraph).strip()
        if normalized:
            counts[sha256(normalized.encode('utf-8')).hexdigest()] += 1
    return counts


def compare_saved_draft_final(draft: str, final_text: str) -> ChapterTextDelta:
    """SQLite에서 이미 읽은 초고/최종본만 비교하고 외부 I/O는 하지 않는다."""
    if type(draft) is not str or type(final_text) is not str:
        raise ValueError('저장된 초고와 최종본의 형식을 확인하세요.')
    before = _paragraph_counts(draft)
    after = _paragraph_counts(final_text)
    retained = sum(min(count, after.get(key, 0)) for key, count in before.items())
    original = sum(before.values())
    latest = sum(after.values())
    if not draft.strip():
        status = 'DRAFT_NOT_SAVED'
    elif not final_text.strip():
        status = 'FINAL_NOT_SAVED'
    else:
        status = 'AUTHOR_MANUAL_COMPARISON_REQUIRED'
    return ChapterTextDelta(
        sum(not c.isspace() for c in draft),
        sum(not c.isspace() for c in final_text),
        original, latest, retained,
        original - retained, latest - retained,
        round(100 * retained / original) if original else 0,
        status,
    )
