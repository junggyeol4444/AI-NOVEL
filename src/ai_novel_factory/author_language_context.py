"""Local author-specified terminology/voice context and review-only hints.

No model is launched; reading the manuscript is opt-in and does not constitute
quality approval. Nothing automatically rewrites text or certifies correctness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from .database.episodes import EpisodeStore
from .author_arc_ledger import canon_fingerprint
from .author_language_ledger import (
    AuthorLanguageError, AuthorLanguageRule, read_author_language_rules,
    language_ledger_fingerprint,
)


@dataclass(frozen=True)
class AuthorLanguageContext:
    episode: int
    prompt_text: str = field(repr=False)
    ledger_sha256: str = field(repr=False)
    applicable: tuple[AuthorLanguageRule, ...] = field(repr=False)
    stale: bool = False
    configured: bool = False
    quality_certified: bool = False
    publication_approved: bool = False


@dataclass(frozen=True)
class SpellingReviewHint:
    rule_id: str
    subject: str
    unexpected_form: str
    count: int
    first_offset: int
    review_only: bool = True


def build_author_language_context(store: EpisodeStore, project_id: str, *,
                                  episode: int, folder: str | Path,
                                  expected_ledger_sha256: str | None = None,
                                  max_prompt_chars: int = 6000) -> AuthorLanguageContext:
    if (type(episode) is not int or not 1 <= episode <= 1000
            or type(max_prompt_chars) is not int or not 500 <= max_prompt_chars <= 20000):
        raise AuthorLanguageError('작가 언어 규칙의 회차 또는 문맥 한도가 올바르지 않습니다.')
    current_stamp = language_ledger_fingerprint(folder)
    if expected_ledger_sha256 is not None and current_stamp != expected_ledger_sha256:
        raise AuthorLanguageError('언어 규칙 사건 파일이 변경되어 별도 승인이 필요합니다.')
    canon = canon_fingerprint(store, project_id)
    current = tuple(rule for rule in read_author_language_rules(folder, project_id)
                    if not rule.withdrawn and rule.first_episode <= episode <= rule.last_episode)
    if not current:
        return AuthorLanguageContext(episode, '', current_stamp, (), configured=False)
    if any(rule.canon_sha256 != canon for rule in current):
        return AuthorLanguageContext(episode, '', current_stamp, current, stale=True, configured=True)
    lines = ['[작가 직접 지정한 용어·인물 말투 규칙 / 아직 원고 품질 미검수]']
    for rule in current:
        if rule.kind == 'TERM':
            lines.append('고유명사/용어: ' + rule.subject + ' → 권장 표기: ' + rule.preferred)
            if rule.discouraged:
                lines.append('사용하지 않을 표기: ' + ', '.join(rule.discouraged))
        else:
            lines.append('인물: ' + rule.subject + ' · 작가 지정 호칭/말투: ' + rule.preferred)
            if rule.discouraged:
                lines.append('피할 호칭/표현: ' + ', '.join(rule.discouraged))
        if rule.guidance:
            lines.append('작가 추가 지시: ' + rule.guidance)
    lines.append('기존 Novel Bible·현재 확정 인물 설정을 우선하며 원문 참고작 문장 복제는 금지. 검수·출판 승인 아님.')
    content = '\n'.join(lines)
    if len(content) > max_prompt_chars:
        raise AuthorLanguageError('언어 문맥이 지정 한도를 초과해 임의로 자르지 않았습니다.')
    return AuthorLanguageContext(episode, content, current_stamp, current, configured=True)


def require_author_language_context(context: AuthorLanguageContext) -> str:
    if not isinstance(context, AuthorLanguageContext) or not context.configured or context.stale or not context.prompt_text:
        raise AuthorLanguageError('해당 회차의 현재 언어 규칙 문맥을 확인할 수 없어 모델 호출을 보류합니다.')
    return context.prompt_text


def review_discouraged_spelling(manuscript: str, context: AuthorLanguageContext,
                                 *, max_hints: int = 200) -> tuple[SpellingReviewHint, ...]:
    """Literal substring sightings; these are NOT verified writing errors.

    Context may include voice rules; searching their avoided words can produce
    false positives. The author must decide whether they are actually wrong.
    """
    if (type(manuscript) is not str or len(manuscript) > 1_000_000
            or not isinstance(context, AuthorLanguageContext)
            or context.stale or type(max_hints) is not int or not 1 <= max_hints <= 500):
        raise AuthorLanguageError('언어 규칙 검토 대상 또는 한도가 올바르지 않습니다.')
    findings: list[SpellingReviewHint] = []
    for rule in context.applicable:
        for form in rule.discouraged:
            count = manuscript.count(form)
            if count:
                findings.append(SpellingReviewHint(rule.rule_id, rule.subject, form,
                                                    count, manuscript.find(form)))
            if len(findings) >= max_hints:
                return tuple(findings)
    return tuple(findings)
