"""Native GGUF 12,000-character context with author-input precedence.

A plain Python helper that never calls a model, loads files, writes data or
declares a manuscript canon/approved. Explicitly selected author documents and
saved Bible/POV constraints are indivisible: fail rather than silently
truncating a selected author's instruction. Only model-derived/retrieved
evidence may be excerpted, with a visible omission count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class NativeContextBudgetError(ValueError):
    """Sanitized; original private author material never appears in errors."""


@dataclass(frozen=True)
class PackedNativeContext:
    text: str
    max_chars: int
    omitted_sections: tuple[str, ...]
    selected_author_text_complete: bool
    local_only: bool = True
    quality_certified: bool = False
    publication_approved: bool = False


def _excerpt(text: str, maximum: int, label: str) -> str:
    if len(text) <= maximum:
        return text
    marker = f'\n[{label} 문맥 중간 생략: 실제 원문 원형 보존 / 모델에는 일부만 전달]\n'
    if maximum <= len(marker) + 48:
        return ''
    left = (maximum - len(marker)) // 2
    right = maximum - len(marker) - left
    return text[:left] + marker + text[-right:]


def pack_native_gguf_context(
    *,
    selected_author_sections: tuple[str, ...] = (),
    viewpoint: str,
    saved_canon: str,
    cast: str,
    previous_chapter: str,
    character_history: str,
    scene_context: str,
    previous_scenes: str = '',
    max_chars: int = 12000,
) -> PackedNativeContext:
    """Build a model input that never hides selected author text by slicing.

    The native bridge's explicit character limit is 12k. The author-owned
    selected source is NOT allowed to exceed that limit silently. All
    noncanonical retrieved prose/AI plots are optional evidence. When parts
    are omitted, a visible notice is included; no fake facts are generated.
    """
    if (type(selected_author_sections) is not tuple
            or any(type(s) is not str for s in selected_author_sections)
            or any(type(s) is not str for s in (
                viewpoint, saved_canon, cast, previous_chapter,
                character_history, scene_context, previous_scenes))
            or type(max_chars) is not int
            or not 3000 <= max_chars <= 12000):
        raise NativeContextBudgetError('로컬 GGUF 집필 문맥 자료가 올바르지 않습니다.')
    if any('\x00' in s for s in selected_author_sections):
        raise NativeContextBudgetError('작가 직접 선택 문맥에 허용되지 않는 문자가 있습니다.')
    # Selected author passages are retained verbatim, including line breaks.
    explicit = [s for s in selected_author_sections if s.strip()]
    mandatory: list[tuple[str, str]] = [
        (f'사용자가 이번 실행에 직접 선택한 원본 작가 문맥 {i + 1}', s)
        for i, s in enumerate(explicit)]
    mandatory += [
        ('작가 저장 서술 시점', viewpoint),
        ('작가 Novel Bible 현재 회차 설정', saved_canon),
        ('작가 저장 등장인물 정보', cast),
    ]
    primary = '\n'.join(
        f'[{label}]\n{value}' for label, value in mandatory if value.strip()
    )
    # Keep room for at least one warning and meaningful model-prose evidence.
    if len(primary) > max_chars - 96:
        raise NativeContextBudgetError(
            '작가가 선택한 원문·서술 시점·인물 설정이 GGUF 문맥 한도를 초과했습니다. '
            '원본은 자르지 않았으며 별도의 작가 선택이 필요합니다.')
    # Exact selected author passages are already ahead of the generated
    # context. Remove those duplicates ONCE so model inputs remain useful.
    supplemental = scene_context
    for section in explicit:
        supplemental = supplemental.replace(section, '', 1)
    optional = (
        ('이번 회차 앞선 실제 장면', previous_scenes),
        ('직전 회차 실제 결말', previous_chapter),
        ('현재 인물의 저장 과거 사건', character_history),
        ('현재 플롯·장면 및 이전 실제 원고 참고', supplemental),
    )
    # Reserve a short omission notice, even when all retrieved prose cannot
    # fit. The critical author-written primary text is always intact.
    reserve = 135
    available = max_chars - len(primary) - reserve - (1 if primary else 0)
    if available < 0:
        raise NativeContextBudgetError('작가 설정 뒤에 남는 모델 문맥이 없습니다.')
    selected: list[str] = []
    omitted: list[str] = []
    for label, value in optional:
        if not value.strip():
            continue
        # Do not spend all remaining space on an old chapter when today's
        # scene needs its own plan and previously written scene prose.
        later = sum(bool(x.strip()) for _, x in optional
                    if _ != label)  # informational only, no hidden defaults
        del later
        if label == '이번 회차 앞선 실제 장면':
            desired = min(1700, max(0, available // 2))
        elif label == '직전 회차 실제 결말':
            desired = min(2000, max(0, available // 3))
        elif label == '현재 인물의 저장 과거 사건':
            desired = min(1400, max(0, available // 2))
        else:
            desired = available
        header = f'[{label}]\n'
        limit = max(0, desired - len(header) - 1)
        passage = _excerpt(value, limit, label)
        if not passage:
            omitted.append(label)
            continue
        if len(passage) < len(value):
            omitted.append(label)
        chunk = header + passage
        if len(chunk) > available:
            omitted.append(label)
            continue
        selected.append(chunk)
        available -= len(chunk) + 1
    message = ('[로컬 GGUF 입력 분량 제한: ' + ', '.join(omitted)
               + ' 일부 생략. 해당 자료를 확인하지 못한 사실로 추측하지 말 것.]'
               if omitted else '')
    # The notice may list a maximum of three known labels; bounded by reserve.
    combined = '\n'.join(
        section for section in (primary, *selected, message) if section)
    if len(combined) > max_chars:
        raise NativeContextBudgetError('로컬 GGUF 문맥 길이 제한을 초과했습니다.')
    return PackedNativeContext(
        combined, max_chars, tuple(omitted), True)
