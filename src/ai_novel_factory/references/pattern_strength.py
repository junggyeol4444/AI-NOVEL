"""Stage 34: describe user-selected influence over reference *statistics*.

A strength controls only a local numeric preview. It is NOT a request to
reproduce a book, mimic an author, instruct an LLM, or copy any wording.
No original phrases, filenames or personal paths occur in the return value.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_novel_factory.database.genre_patterns import GenrePatternStore, GenreStorageError
from ai_novel_factory.database.pattern_strengths import (
    PatternStrengthStore, PatternStrengthStorageError,
)
from ai_novel_factory.database.reference_profiles import ProfileStorageError, ReferenceProfileStore
from .genre_patterns import GENRE_NAMES, _FEATURES
from .profile_collection import WEIGHTING_MODES
from .plaintext_parser import ReferenceParseError

# A single work should never account for a supermajority of a future blended
# pattern. We flag, rather than silently manipulate, user-chosen settings.
MAX_SINGLE_WORK_SHARE = 0.60


class PatternStrengthError(ValueError):
    """Privacy-safe failure containing no original source content."""


@dataclass(frozen=True)
class WorkInfluence:
    reference_id: str
    configured_strength: int
    effective_percent: float  # 0..100; display only, rounded to 4 places


@dataclass(frozen=True)
class StrengthFeature:
    key: str
    weighted_mean: float


@dataclass(frozen=True)
class PatternStrengthPreview:
    genre: str
    weighting: str
    reference_count: int
    active_count: int
    max_share_percent: float
    usable_for_selection: bool
    status: str  # ready | fewer_than_two | over_concentrated | empty
    influences: tuple[WorkInfluence, ...]
    features: tuple[StrengthFeature, ...]


def _feature_values(profile: object) -> tuple[float, ...]:
    return (
        float(profile.dialogue_ratio),
        float(profile.average_sentence_characters),
        float(profile.lexical_diversity),
        float(profile.emotion_balance),
        profile.cliffhanger_candidate_episodes / profile.episode_count,
        1000 * profile.event_cue_candidates / profile.total_characters
        if profile.total_characters else 0.0,
    )


def preview_strengths(
    genres: GenrePatternStore,
    strengths: PatternStrengthStore,
    genre: str,
    *, weighting: str = "equal",
) -> PatternStrengthPreview:
    """Read current genre cohort and setting values without a DB write.

    Strength=0 excludes a work from this preview, never from the original
    reference profile or saved genre recipe. At least two nonzero contributors
    and at most 60% share for any single work are required for later selection.
    This stage does not yet provide a writer or prompt-consumption API.
    """
    if not isinstance(genres, GenrePatternStore) or not isinstance(strengths, PatternStrengthStore):
        raise PatternStrengthError("로컬 패턴과 강도 저장소가 필요합니다.")
    if type(genre) is not str or genre not in GENRE_NAMES:
        raise PatternStrengthError("장르 코드가 올바르지 않습니다.")
    if type(weighting) is not str or weighting not in WEIGHTING_MODES:
        raise PatternStrengthError("통합 가중치가 올바르지 않습니다.")
    try:
        # get() checks saved recipe freshness. Never use a changed cohort
        # before the user explicitly rebuilds the pattern in stage 32.
        genres.get(genre, weighting=weighting)
        ids = tuple(reference_id for reference_id, _ in genres.list_assignments(genre))
        profiles = genres._profiles
        data = tuple(profiles.get(reference_id) for reference_id in ids)
        settings = tuple(strengths.get(reference_id) for reference_id in ids)
    except (GenreStorageError, PatternStrengthStorageError, ProfileStorageError, ReferenceParseError):
        raise PatternStrengthError("패턴 자료가 없거나 오래되었습니다. 장르 패턴을 다시 구축하세요.") from None

    if not 2 <= len(data) <= 50:
        raise PatternStrengthError("장르 패턴 구성원 수가 올바르지 않습니다.")

    if weighting == "characters":
        chars = tuple(p.total_characters for p in data)
        # Match the stage-31 all-empty fallback, but do not silently give a
        # zero-length reference a vote when nonempty profiles also exist.
        multiplier = chars if any(chars) else (1,) * len(chars)
    else:
        multiplier = (1,) * len(data)
    raw = tuple(a * b for a, b in zip(settings, multiplier))
    total = sum(raw)
    shares = tuple(weight / total if total else 0.0 for weight in raw)
    active_count = sum(weight > 0 for weight in raw)
    highest = max(shares)
    if not total:
        status = "empty"
    elif active_count < 2:
        status = "fewer_than_two"
    elif highest > MAX_SINGLE_WORK_SHARE + 1e-12:
        status = "over_concentrated"
    else:
        status = "ready"
    features = tuple(
        StrengthFeature(key, round(sum(share * values[index]
                                       for share, values in zip(shares, map(_feature_values, data))), 6))
        for index, (key, _label, _min, _max) in enumerate(_FEATURES)
    )
    return PatternStrengthPreview(
        genre=genre,
        weighting=weighting,
        reference_count=len(data),
        active_count=active_count,
        max_share_percent=round(highest * 100, 4),
        usable_for_selection=(status == "ready"),
        status=status,
        influences=tuple(WorkInfluence(reference_id, setting, round(share * 100, 4))
                         for reference_id, setting, share in zip(ids, settings, shares)),
        features=features,
    )


def render_strength_preview(result: PatternStrengthPreview) -> str:
    """Only anonymous UUIDs, bounded numeric data and fixed labels."""
    if (type(result) is not PatternStrengthPreview or result.genre not in GENRE_NAMES
            or result.weighting not in WEIGHTING_MODES
            or type(result.usable_for_selection) is not bool
            or result.status not in {"ready", "fewer_than_two", "over_concentrated", "empty"}
            or not 2 <= result.reference_count <= 50
            or len(result.influences) != result.reference_count
            or len(result.features) != len(_FEATURES)):
        raise PatternStrengthError("강도 미리보기 자료형이 올바르지 않습니다.")
    reasons = {
        "ready": "조건 충족 (향후 통계 패턴 선택에만 사용 가능)",
        "fewer_than_two": "참여 참고작이 두 개 미만이므로 선택 불가",
        "over_concentrated": "한 참고작에 60%를 초과해 편중되므로 선택 불가",
        "empty": "모든 실효 강도가 0이므로 선택 불가",
    }
    lines = [f"참고 작품별 패턴 강도 · {GENRE_NAMES[result.genre]} ({result.weighting})",
             f"총 {result.reference_count}작품 · 참여 {result.active_count}작품 · 최대 점유 {result.max_share_percent:.2f}%",
             f"검토 결과: {reasons[result.status]}",
             "익명 참고작 ID | 사용자 설정(0~100) | 실효 비중(%)"]
    from ai_novel_factory.database.pattern_strengths import validate_reference_id, validate_strength
    for entry in result.influences:
        if type(entry) is not WorkInfluence:
            raise PatternStrengthError("강도 기록 자료형이 올바르지 않습니다.")
        try:
            validate_reference_id(entry.reference_id)
            validate_strength(entry.configured_strength)
        except PatternStrengthStorageError:
            raise PatternStrengthError("강도 기록이 손상되었습니다.") from None
        if not 0 <= entry.effective_percent <= 100:
            raise PatternStrengthError("강도 비중이 올바르지 않습니다.")
        lines.append(f"{entry.reference_id} | {entry.configured_strength} | {entry.effective_percent:.2f}")
    lines.append("--- 통계 지표 (관찰치의 가중 평균, 글쓰기 목표 아님) ---")
    for feature, (key, name, _lo, _hi) in zip(result.features, _FEATURES):
        if type(feature) is not StrengthFeature or feature.key != key or not 0 <= abs(feature.weighted_mean) < 1e10:
            raise PatternStrengthError("통계 강도 지표가 올바르지 않습니다.")
        lines.append(f"{name}: {feature.weighted_mean:.4f}")
    lines.append("주의: 0은 미리보기에서만 제외합니다. 원문·프로필·장르 분류는 그대로 유지됩니다.")
    lines.append("주의: 통계 설정일 뿐, 원문 복제·작가 문체 모방·AI 집필 기능이 아닙니다.")
    return "\n".join(lines)
