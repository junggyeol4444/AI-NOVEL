"""Stage 35: select generic statistical reference elements, never source prose.

The only transferable values are six fixed category keys and anonymous,
aggregate numeric observations. No model prompts, quotations or author imitation.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .genre_patterns import GENRE_NAMES, _FEATURES
from .pattern_strength import PatternStrengthPreview

FEATURE_KEYS = tuple(item[0] for item in _FEATURES)
FEATURE_LABELS = {key: label for key, label, _, _ in _FEATURES}


class ElementSelectionError(ValueError):
    """Fixed error messages without untrusted source content."""


@dataclass(frozen=True)
class SelectedElement:
    key: str
    label: str
    observed_mean: float  # bounded generic metric; not a generation target


@dataclass(frozen=True)
class ElementSelection:
    genre: str
    weighting: str
    selected_keys: tuple[str, ...]
    reference_count: int
    max_share_percent: float
    elements: tuple[SelectedElement, ...]


def validate_element_keys(keys: object) -> tuple[str, ...]:
    """Require 1-6 distinct keys, then canonicalize in published schema order."""
    if type(keys) not in (tuple, list) or not 1 <= len(keys) <= len(FEATURE_KEYS):
        raise ElementSelectionError("참고할 통계 항목을 1~6개 선택하세요.")
    if any(type(key) is not str or key not in FEATURE_LABELS for key in keys):
        raise ElementSelectionError("허용된 통계 항목만 선택할 수 있습니다.")
    if len(set(keys)) != len(keys):
        raise ElementSelectionError("통계 항목을 중복 선택할 수 없습니다.")
    return tuple(key for key in FEATURE_KEYS if key in keys)


def select_elements(preview: PatternStrengthPreview, keys: object) -> ElementSelection:
    """Fail closed when the genre/strength preview is stale or over-dominated."""
    selected = validate_element_keys(keys)
    if (type(preview) is not PatternStrengthPreview
            or preview.genre not in GENRE_NAMES
            or preview.weighting not in ("equal", "characters")
            or preview.status != "ready" or preview.usable_for_selection is not True
            or not 2 <= preview.active_count <= preview.reference_count <= 50
            or not 0 <= preview.max_share_percent <= 60.00000001
            or len(preview.features) != len(FEATURE_KEYS)
            or tuple(item.key for item in preview.features) != FEATURE_KEYS):
        raise ElementSelectionError("참고작 구성이 유효하지 않습니다. 패턴과 강도를 확인하세요.")
    elements = []
    for feature in preview.features:
        if type(feature.weighted_mean) not in (int, float) or not isfinite(feature.weighted_mean):
            raise ElementSelectionError("선택한 통계 값이 올바르지 않습니다.")
        if feature.key in selected:
            elements.append(SelectedElement(feature.key, FEATURE_LABELS[feature.key],
                                            feature.weighted_mean))
    return ElementSelection(preview.genre, preview.weighting, selected,
                            preview.reference_count, preview.max_share_percent,
                            tuple(elements))


def render_element_selection(value: ElementSelection) -> str:
    """Show safe bounded labels and aggregate numbers only."""
    if (type(value) is not ElementSelection or value.genre not in GENRE_NAMES
            or value.weighting not in ("equal", "characters")
            or validate_element_keys(value.selected_keys) != value.selected_keys
            or not 2 <= value.reference_count <= 50
            or not 0 <= value.max_share_percent <= 60.00000001
            or len(value.elements) != len(value.selected_keys)):
        raise ElementSelectionError("선택 결과 형식이 올바르지 않습니다.")
    lines = [f"참고 요소 선택: {GENRE_NAMES[value.genre]} ({value.weighting})",
             f"참고작 수: {value.reference_count} · 최고 개별 비중: {value.max_share_percent:.2f}%",
             "선택된 통계적 관찰 항목 (집필 지시나 문체 복제 목표가 아님):"]
    for key, item in zip(value.selected_keys, value.elements):
        if (type(item) is not SelectedElement or item.key != key
                or item.label != FEATURE_LABELS[key]
                or type(item.observed_mean) not in (int, float)
                or not isfinite(item.observed_mean)):
            raise ElementSelectionError("선택 항목 데이터가 손상되었습니다.")
        lines.append(f"- {FEATURE_LABELS[key]} [{key}]: {item.observed_mean:.4f}")
    lines.append("원문·인물명·특정 표현을 복제하거나 작가 문체를 재현하지 않습니다.")
    return "\n".join(lines)
