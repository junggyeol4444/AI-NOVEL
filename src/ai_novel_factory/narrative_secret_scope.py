"""Author-defined focal-character knowledge guard for actual local GGUF.

Never alters saved characters, scenes, manuscript databases or reference works.
A limited-POV focal character does not automatically possess other saved
characters' private Novel Bible secrets. Previously registered author
knowledge events may explicitly grant that information after an earlier
chapter. The module does not infer what the model or a character truly knows.
User-authored, explicitly selected narrative instructions remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass

from .database.characters import BibleCharacter
from .narrative_scene_canon import EpisodeCanonFocus


class NarrativeSecretScopeError(ValueError):
    """Diagnostics never reproduce an author's private secrets."""


_REDACTED = '[초점 인물에게 비공개인 작가 저장 비밀 생략]'


@dataclass(frozen=True)
class NarrativeSecretScope:
    focal: str
    episode: int
    permitted_character_names: tuple[str, ...]
    protected_character_names: tuple[str, ...]
    protected_values: tuple[str, ...]
    knowledge_verified: bool = False
    prose_certified: bool = False
    publication_approved: bool = False


def select_focal_secret_scope(
    characters: tuple[BibleCharacter, ...],
    canon: EpisodeCanonFocus,
    focal_name: str,
) -> NarrativeSecretScope:
    """Only explicit PRIOR author knowledge can unlock someone else's secret.

    Current-chapter author knowledge changes may be planned but are not
    assumed to have occurred before the current scene is actually written.
    No name matching, keyword similarity or invented fact grants access.
    Without a named POV focal, the old unrestricted author-story scope stays.
    """
    if (type(characters) is not tuple
            or not isinstance(canon, EpisodeCanonFocus)
            or type(focal_name) is not str
            or any(not isinstance(person, BibleCharacter) for person in characters)):
        raise NarrativeSecretScopeError('인물별 정보 접근 범위가 올바르지 않습니다.')
    named = {person.name for person in characters}
    if focal_name and focal_name not in named:
        raise NarrativeSecretScopeError(
            '서술 시점 인물이 저장된 작가 Novel Bible 인물에 없습니다.')
    if not focal_name:
        return NarrativeSecretScope('', canon.episode, tuple(sorted(named)), (), ())
    permitted: set[str] = {focal_name}
    blocked: list[tuple[str, str]] = []
    for person in characters:
        secret = person.secret.strip()
        if not secret or person.name == focal_name:
            permitted.add(person.name)
            continue
        # EpisodeCanonFocus.knowledge is author-written, episode effective.
        # A YES within the current chapter is not necessarily a reveal
        # before this specific scene, so demand an EARLIER chapter fact.
        known = any(
            name == focal_name and episode < canon.episode and knows is True
            and description.strip() == secret
            for name, episode, description, knows in canon.knowledge
        )
        if known:
            permitted.add(person.name)
        else:
            blocked.append((person.name, secret))
    return NarrativeSecretScope(
        focal_name, canon.episode, tuple(sorted(permitted)),
        tuple(person for person, _ in blocked),
        tuple(secret for _, secret in blocked))


def omit_unrevealed_secrets(
    value: str, scope: NarrativeSecretScope,
    *, structured: bool = False,
) -> str:
    """Guard assistant-created context only, not author-approved text.

    Exact phrases >=6 characters can be safely removed from contextual
    excerpts. Shorter phrases may be common Korean words, so suppress them
    only within explicitly labeled '비밀:' metadata; the caller should not
    claim this lexical screen is a full semantic privacy verifier.
    """
    if type(value) is not str or not isinstance(scope, NarrativeSecretScope):
        raise NarrativeSecretScopeError('비밀 정보 문맥 형식이 올바르지 않습니다.')
    if not scope.focal or not scope.protected_values:
        return value
    result = value
    for secret in scope.protected_values:
        if len(secret) >= 6:
            result = result.replace(secret, _REDACTED)
        # The stored cast and character Bible use these labels. Suppress
        # single-syllable or common-word private hints conservatively.
        for prefix in ('사용자 저장 비밀: ', '저장된 비밀: ', '비밀: ',
                       '비밀 | ', 'secret: '):
            result = result.replace(prefix + secret, prefix + _REDACTED)
    return result


def focal_secret_instruction(scope: NarrativeSecretScope) -> str:
    """One author-fact-backed model instruction, not an invented plot fact."""
    if not scope.focal or not scope.protected_character_names:
        return ''
    return (
        '[작가 지정 초점 인물의 정보 범위 / 직접 저장한 비밀의 자동 공개 금지]\n'
        f'현재 초점 인물: {scope.focal}; '
        f'자동 공개하지 않을 다른 인물의 비밀 수: '
        f'{len(scope.protected_character_names)}.\n'
        '다른 인물의 미공개 내면·비밀을 초점 인물의 지식·관찰 사실로 '
        '서술하지 말 것. 작가가 별도 선택한 장면 지시와 이미 실제 '
        '원고에 발생한 사실을 우선하며, 자동 추론으로 비밀 공개 금지.'
    )
