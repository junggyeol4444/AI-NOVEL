"""Offline, deterministic stage-51 premise scaffolding (no AI or network calls)."""
from __future__ import annotations

from dataclasses import dataclass
import re


class PlanningError(ValueError):
    """Input error without echoing potentially private user content."""


@dataclass(frozen=True)
class PlanningInput:
    genre: str
    subject: str
    episodes: int
    mood: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class PremiseDraft:
    title: str
    logline: str
    world_outline: str
    episode_count: int
    status: str = "DRAFT_REQUIRES_USER_APPROVAL"
    origin: str = "USER_INPUT_TEMPLATE_NOT_AI"


def _clean(value: str, name: str, maximum: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PlanningError(f"{name}: 입력 길이 또는 형식이 올바르지 않습니다.")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise PlanningError(f"{name}: 제어 문자를 사용할 수 없습니다.")
    return value.strip()


def draft_premise(spec: PlanningInput) -> PremiseDraft:
    """Construct an editable outline solely from the user's original inputs.

    Reference titles/contents are deliberately not incorporated into prose.
    No persistence, model inference, approval, or publication occurs.
    """
    if not isinstance(spec, PlanningInput):
        raise PlanningError("기획 입력 형식이 올바르지 않습니다.")
    genre = _clean(spec.genre, "장르", 60)
    subject = _clean(spec.subject, "소재")
    mood = _clean(spec.mood, "분위기", 60)
    if type(spec.episodes) is not int or not 1 <= spec.episodes <= 10000:
        raise PlanningError("회차 수는 1~10000 사이의 정수여야 합니다.")
    if not isinstance(spec.references, tuple) or len(spec.references) > 30:
        raise PlanningError("참고작 목록 형식이 올바르지 않습니다.")
    for reference in spec.references:
        _clean(reference, "참고작 식별자", 120)
    title = f"{subject} — {genre} 기획 초안"
    logline = f"{subject}을(를) 중심 소재로, {mood} 분위기의 {genre} 장편 이야기를 {spec.episodes}회에 걸쳐 전개한다."
    world = (f"장르: {genre}. 중심 소재: {subject}. 분위기: {mood}. "
             "세계관의 법칙, 인물, 갈등, 결말은 사용자가 Novel Bible에서 확정해야 한다.")
    return PremiseDraft(title, logline, world, spec.episodes)
