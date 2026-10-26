"""User-saved, episode/scene-specific character focus for local GGUF prose.

Model-generated plots and scene drafts only select relevance. They never
replace the author's stored Novel Bible facts or approve generated fiction.
This module reads no files and never modifies manuscripts or character data.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .database.characters import BibleCharacter


@dataclass(frozen=True)
class SceneCastFocus:
    names: tuple[str, ...]
    context: str
    matched_names: tuple[str, ...]


def focus_saved_cast(
    characters: tuple[BibleCharacter, ...],
    evidence: tuple[str, ...],
    *,
    max_participants: int = 8,
) -> SceneCastFocus:
    """Choose named author characters, not the first eight alphabetically.

    Earlier cues have stronger precedence: scene event, author-selected
    episode guide, preceding real scene prose, and full unreviewed plot.
    No fuzzy/inferred character identities or reference-novel passages.
    """
    if (type(characters) is not tuple or type(evidence) is not tuple
            or type(max_participants) is not int
            or not 1 <= max_participants <= 8):
        raise ValueError('인물 및 장면 집필 문맥의 형식이 올바르지 않습니다.')
    if any(not isinstance(item, BibleCharacter) for item in characters):
        raise ValueError('저장 인물 Novel Bible 정보만 사용할 수 있습니다.')
    if any(type(text) is not str for text in evidence):
        raise ValueError('장면 사건 정보의 형식이 올바르지 않습니다.')
    if not characters:
        return SceneCastFocus(('주인공',), '', ())
    longest = sorted(enumerate(characters),
                     key=lambda entry: (-len(entry[1].name), entry[0]))
    positions = {item.name.casefold(): i for i, item in enumerate(characters)}
    matcher = re.compile('|'.join(re.escape(item.name) for _, item in longest),
                         re.IGNORECASE)
    scores = [0] * len(characters)
    weights = (16, 9, 5, 2)
    for cue_number, text in enumerate(evidence[:4]):
        per_cue = {}
        for match in matcher.finditer(text[:12_000]):
            person_index = positions.get(match.group().casefold())
            if person_index is not None:
                per_cue[person_index] = min(8, per_cue.get(person_index, 0) + 1)
        for person_index, count in per_cue.items():
            scores[person_index] += weights[cue_number] * count
    ranked = sorted(range(len(characters)), key=lambda i: (-scores[i], i))
    if any(scores):
        chosen = [i for i in ranked if scores[i] > 0][:max_participants]
    else:
        chosen = list(range(min(max_participants, len(characters))))
    selected = tuple(characters[i] for i in chosen)
    matched = tuple(characters[i].name for i in chosen if scores[i] > 0)
    per_field = 90 if len(selected) <= 6 else 65
    lines = [
        '이번 소설 장면에 관련된 사용자가 저장한 인물 설정 '
        '(미검수 AI 기획이 아닌 원본 Novel Bible 우선):'
    ]
    for person in selected:
        description = (
            f'인물: {person.name[:120]}'
            f' | 성격: {person.personality[:per_field]}'
            f' | 목표: {person.goal[:per_field]}'
            f' | 말투: {person.speech_style[:per_field]}'
        )
        if person.secret.strip():
            description += ' | 사용자 저장 비밀: ' + person.secret[:per_field]
        lines.append(description)
    return SceneCastFocus(
        tuple(person.name for person in selected),
        '\n'.join(lines), matched,
    )
