"""작가 지정 용어·말투 규칙과 저장 최종본 1~1000화 전수 대조.

기존 작가 언어 규칙과 SQLite 저장 원고만 읽는다. 후보 출현은 품질 불합격
확정이나 자동 교정 근거가 아니며, 검수·출판·모델 실행 승인을 만들지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .author_arc_ledger import canon_fingerprint
from .author_language_ledger import (
    AuthorLanguageError, language_ledger_fingerprint, read_author_language_rules,
)
from .database.episodes import EpisodeStore


@dataclass(frozen=True)
class AuthorLanguageScopeFinding:
    kind: str
    subject: str
    avoided_form: str
    occurrences: int


@dataclass(frozen=True)
class AuthorLanguageScopeChapter:
    episode: int
    revision: int | None
    final_characters: int
    active_rules: int
    stale_rules: int
    preferred_occurrences: int
    avoided_occurrences: int
    avoided_forms: int
    findings_preview: tuple[AuthorLanguageScopeFinding, ...] = field(repr=False)
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_CERTIFIED'


@dataclass(frozen=True)
class AuthorLanguageScopeAudit:
    project_id: str = field(repr=False)
    through_episode: int
    source_sha256: str = field(repr=False)
    chapters: tuple[AuthorLanguageScopeChapter, ...]
    missing_final: int
    stale_rule_chapters: int
    chapters_with_candidates: int
    total_candidate_occurrences: int
    status: str = 'READ_ONLY_LANGUAGE_SCOPE_NOT_VERIFIED'
    quality_certified: bool = False
    publication_approved: bool = False


def _source_snapshot(store: EpisodeStore, project_id: str,
                     folder: str | Path, through_episode: int):
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorLanguageError('기존 작품을 먼저 선택해야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise AuthorLanguageError('전수 조회 범위는 1~1000화입니다.')
    store.get_project(project_id)
    ledger = language_ledger_fingerprint(folder)
    canon = canon_fingerprint(store, project_id)
    rows = {row.episode: row for row in store.list_episodes(project_id)
            if 1 <= row.episode <= through_episode}
    digest = sha256()
    for token in (project_id, str(through_episode), ledger, canon):
        raw = token.encode('utf-8')
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
    for number in range(1, through_episode + 1):
        row = rows.get(number)
        digest.update(number.to_bytes(4, 'big'))
        if row is None:
            digest.update(b'ABSENT')
            continue
        digest.update(str(row.revision).encode('ascii') + b'\0')
        for name in ('plot', 'draft', 'final_text', 'summary'):
            value = getattr(row, name, '') or ''
            if type(value) is not str:
                raise AuthorLanguageError('저장 원고 문자열 형식이 올바르지 않습니다.')
            data = value.encode('utf-8')
            digest.update(len(data).to_bytes(8, 'big'))
            digest.update(sha256(data).digest())
    return digest.hexdigest(), rows, canon


def build_author_language_scope_audit(
    store: EpisodeStore, project_id: str, *, folder: str | Path,
    through_episode: int,
) -> AuthorLanguageScopeAudit:
    """선택 범위의 모든 저장 최종본을 전체 문자열로 조사하고 후보를 집계."""
    stamp, rows, canon = _source_snapshot(store, project_id, folder, through_episode)
    rules = tuple(rule for rule in read_author_language_rules(folder, project_id)
                  if not rule.withdrawn)
    chapters: list[AuthorLanguageScopeChapter] = []
    for number in range(1, through_episode + 1):
        row = rows.get(number)
        final = (row.final_text or '') if row is not None else ''
        if type(final) is not str:
            raise AuthorLanguageError('저장 최종본 형식이 올바르지 않습니다.')
        applicable = tuple(rule for rule in rules
                           if rule.first_episode <= number <= rule.last_episode)
        stale = sum(rule.canon_sha256 != canon for rule in applicable)
        current = tuple(rule for rule in applicable if rule.canon_sha256 == canon)
        preferred_hits = 0
        avoided_hits = 0
        avoided_forms = 0
        previews: list[AuthorLanguageScopeFinding] = []
        if final.strip():
            for rule in current:
                preferred_hits += final.count(rule.preferred)
                for form in rule.discouraged:
                    count = final.count(form)
                    if count:
                        avoided_hits += count
                        avoided_forms += 1
                        if len(previews) < 30:
                            previews.append(AuthorLanguageScopeFinding(
                                rule.kind, rule.subject, form, count))
        status = ('MISSING_FINAL_REQUIRES_AUTHOR_ACTION' if not final.strip()
                  else 'STALE_AUTHOR_RULES_REVIEW_REQUIRED' if stale
                  else 'AVOIDED_FORMS_AUTHOR_REVIEW' if avoided_forms
                  else 'NO_AVOIDED_FORMS_FOUND_NOT_CERTIFIED' if current
                  else 'NO_APPLICABLE_RULES_NOT_CERTIFIED')
        chapters.append(AuthorLanguageScopeChapter(
            number, row.revision if row else None, len(final.replace(' ', '').replace('\n', '')),
            len(applicable), stale, preferred_hits, avoided_hits, avoided_forms,
            tuple(previews), status))
    # The scan is discarded if an author edit or ledger change occurred mid-read.
    if _source_snapshot(store, project_id, folder, through_episode)[0] != stamp:
        raise AuthorLanguageError('전수 조회 도중 저장 원고 또는 작가 규칙이 변경됐습니다.')
    result = tuple(chapters)
    return AuthorLanguageScopeAudit(
        project_id, through_episode, stamp, result,
        sum(ch.status == 'MISSING_FINAL_REQUIRES_AUTHOR_ACTION' for ch in result),
        sum(ch.stale_rules > 0 for ch in result),
        sum(ch.avoided_forms > 0 for ch in result),
        sum(ch.avoided_occurrences for ch in result))


def require_current_author_language_scope_audit(
    audit: AuthorLanguageScopeAudit, store: EpisodeStore,
    project_id: str, *, folder: str | Path,
) -> None:
    """GUI 인계 직전 전체 저장 원고·작가 규칙 지문을 다시 확인."""
    if not isinstance(audit, AuthorLanguageScopeAudit) or project_id != audit.project_id:
        raise AuthorLanguageError('작품 또는 이전 조회 결과가 변경됐습니다.')
    current = _source_snapshot(store, project_id, folder, audit.through_episode)[0]
    if current != audit.source_sha256:
        raise AuthorLanguageError('저장 원고·작가 언어 규칙 변경으로 이전 조회가 무효화됐습니다.')