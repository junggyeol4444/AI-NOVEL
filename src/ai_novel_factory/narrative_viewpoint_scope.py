"""Bind author-written narrator and focal-character rules to local GGUF scenes.

Existing Style Bible rule keys are used; no new database, narrator detection,
future-fiction inference, or silent rewrite of the author's instructions.

Optional keys (save with the existing Style Bible editor):
    pov                       global narrator / voice directive
    pov_e0007                 chapter-seven override
    pov_e0007_s02             scene-two override for chapter seven
    pov_focus                 exact saved Bible character name, global
    pov_focus_e0007           episode-specific focal character
    pov_focus_e0007_s02       episode-and-scene-specific focal character

An explicit finer-grained 'pov' override resets an inherited focal character
unless a focal override is authored at that granularity or finer. Saved prose
is never interpreted as proof of a narrator or of another character's mind.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class SavedViewpointError(ValueError):
    """Invalid author-authored viewpoint directive (no private text in error)."""


@dataclass(frozen=True)
class SavedViewpointScope:
    episode: int
    scene: int
    directive: str
    focal_character: str
    directive_key: str
    focus_key: str
    prompt: str
    author_defined: bool = False


def select_saved_viewpoint(
    style_rules: Mapping[str, str],
    episode: int,
    scene: int,
    character_names: tuple[str, ...],
    *,
    max_prompt_chars: int = 2600,
) -> SavedViewpointScope:
    """Select the narrowest explicit rule and preserve its original wording.

    Scene=0 means chapter-wide plot generation. Do not let a scene-specific
    rule affect a different scene or the outline of an entire chapter. If the
    author did not save these keys, do not invent a narrator or viewpoint.
    """
    if (type(episode) is not int or not 1 <= episode <= 1000
            or type(scene) is not int or not 0 <= scene <= 20
            or type(character_names) is not tuple
            or any(type(name) is not str or not name.strip()
                   for name in character_names)
            or type(max_prompt_chars) is not int
            or not 500 <= max_prompt_chars <= 5000):
        raise SavedViewpointError('서술 시점 규칙의 회차·장면·인물 범위가 올바르지 않습니다.')
    if not isinstance(style_rules, Mapping):
        raise SavedViewpointError('작가 Style Bible 시점 규칙을 읽을 수 없습니다.')
    scopes = [('', 0), (f'_e{episode:04d}', 1)]
    if scene:
        scopes.append((f'_e{episode:04d}_s{scene:02d}', 2))

    def most_specific(base: str) -> tuple[str, str, int]:
        found = ('', '', -1)
        for suffix, level in scopes:
            key = base + suffix
            value = style_rules.get(key)
            if value is None:
                continue
            if type(value) is not str or '\x00' in value:
                raise SavedViewpointError('저장된 작가 시점 지시의 형식이 올바르지 않습니다.')
            if not value.strip():
                continue
            found = (key, value.strip(), level)
        return found

    directive_key, directive, directive_level = most_specific('pov')
    focus_key, focus, focus_level = most_specific('pov_focus')
    # A specifically authored new narrative POV must not silently keep an
    # older character's private-knowledge boundary.
    if focus and directive_level > focus_level:
        focus_key, focus = '', ''
    if focus and focus not in character_names:
        raise SavedViewpointError(
            '서술 시점 인물이 현재 저장된 Novel Bible 인물 목록에 없습니다.')

    if not directive and not focus:
        return SavedViewpointScope(
            episode, scene, '', '', '', '', '', False)
    parts = [
        '[작가가 직접 저장한 서술 시점·정보 범위 / 기존 Style Bible 최우선]',
        f'적용 범위: {episode}화' + (f' {scene}장면' if scene else ' 플롯 및 회차'),
    ]
    if directive:
        parts.append(f'작가 서술 시점 지시 ({directive_key}): {directive}')
    if focus:
        parts.extend((
            f'작가 지정 초점 인물 ({focus_key}): {focus}',
            '제한적 인물 시점이면 이 인물이 직접 인지한 일과 감정만 서술하고, '
            '다른 인물의 내면·숨긴 비밀을 관찰 사실인 것처럼 단정하지 말 것. '
            '미래의 관계변화·지식 공개를 앞당기지 말 것.',
        ))
    parts.append(
        '사건·시점·어조 충돌 시 사용자가 저장한 Novel Bible 및 '
        '더 구체적인 이 장면 지시를 적용. 모델 초고는 미검수이며 승인·출판이 아니다.')
    prompt = '\n'.join(parts)
    if len(prompt) > max_prompt_chars:
        raise SavedViewpointError(
            '작가가 저장한 서술 시점 규칙이 모델 입력 범위를 초과했습니다.')
    return SavedViewpointScope(
        episode, scene, directive, focus,
        directive_key, focus_key, prompt, True)
