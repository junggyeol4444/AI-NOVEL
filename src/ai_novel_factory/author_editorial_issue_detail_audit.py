"""기존 편집 이슈별 원고 revision·QC·참고작 연결 근거를 작가가 직접 읽는다.

기존 SQLite 및 작가가 선택한 로컬 JSON을 수정하지 않는다. 이슈 종료,
QC PASS, 저작권 판정, 자동 출판 및 모델 실행 기능은 의도적으로 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path

from .author_workflow_dependencies import build_author_workflow_dependencies
from .database.episodes import EpisodeStore
from .editorial_issue_ledger import EditorialIssueError, _directory, _read_events


class AuthorEditorialIssueDetailError(ValueError):
    """원고·메모·로컬 경로를 오류 메시지에 노출하지 않는다."""


@dataclass(frozen=True)
class EditorialIssueDetailRow:
    episode: int
    issue_id: str = field(repr=False)
    category: str = ''
    note: str = field(default='', repr=False)
    state: str = 'OPEN_CURRENT'
    opened_revision: int = 0
    closed_revision: int | None = None
    current_revision: int | None = None
    final_present: bool = False
    review_status: str = 'NOT_RUN'
    reference_status: str = 'NOT_RUN'
    publication_approved: bool = False


@dataclass(frozen=True)
class EditorialIssueDetailAudit:
    project_id: str = field(repr=False)
    folder: str = field(default='', repr=False)
    through_episode: int = 0
    rows: tuple[EditorialIssueDetailRow, ...] = ()
    open_count: int = 0
    stale_count: int = 0
    current_closed_count: int = 0
    source_fingerprint: str = field(default='', repr=False)
    publication_approved: bool = False
    quality_certified: bool = False


def _events_with_digest(folder: str | Path):
    """원본 JSON 실제 바이트까지 지문에 포함하고, 기록 손상 시 중단."""
    try:
        directory = _directory(folder)
        events = _read_events(directory)
        digest = sha256()
        paths = sorted(p for p in directory.iterdir()
                       if p.name.startswith('anf_editorial_') and p.name.endswith('.json'))
        # 이름 규칙 외의 파일은 기존 원장과 동일하게 무시한다.
        from .editorial_issue_ledger import _FILE_RE, _MAX_EVENT_BYTES
        for path in paths:
            if not _FILE_RE.fullmatch(path.name):
                continue
            if path.is_symlink() or not path.is_file():
                raise AuthorEditorialIssueDetailError('편집 기록 파일을 안전하게 읽지 못했습니다.')
            raw = path.read_bytes()
            if len(raw) > _MAX_EVENT_BYTES:
                raise AuthorEditorialIssueDetailError('편집 기록 크기 제한을 초과했습니다.')
            digest.update(path.name.encode('utf-8') + b'\0')
            digest.update(len(raw).to_bytes(8, 'big'))
            digest.update(sha256(raw).digest())
        if len(paths) > 20000:
            raise AuthorEditorialIssueDetailError('편집 기록 개수 제한을 초과했습니다.')
        return str(directory.resolve()), events, digest.hexdigest()
    except (EditorialIssueError, OSError, UnicodeError, ValueError) as exc:
        raise AuthorEditorialIssueDetailError('기존 편집 기록을 읽지 못했습니다.') from exc


def build_author_editorial_issue_detail_audit(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    issue_folder: str | Path,
) -> EditorialIssueDetailAudit:
    """1~1000화 모든 기존 이슈를 하나도 누락하지 않고 현재 원고와 연결."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise AuthorEditorialIssueDetailError('기존 작품과 1~1000화 범위를 선택하세요.')
    directory, events, ledger_sha = _events_with_digest(issue_folder)
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        saved = {ep.episode: ep for ep in store.list_episodes(project_id)}
        signature = sha256()
        for ep_number, ep in sorted(saved.items()):
            signature.update(str(ep_number).encode('ascii') + b'\0')
            signature.update(str(ep.revision).encode('ascii') + b'\0')
            for key in ('plot', 'draft', 'final_text', 'summary'):
                signature.update(sha256(getattr(ep, key).encode('utf-8')).digest())
            for scene in store.list_scenes(project_id, ep_number):
                signature.update(json.dumps((scene.scene_id, scene.position,
                    scene.text, scene.updated_at), ensure_ascii=False).encode('utf-8'))
            for check in store.list_checks(project_id, ep_number):
                signature.update(json.dumps((check.check_id, check.category,
                    check.outcome, check.note, check.content_revision, check.created_at),
                    ensure_ascii=False).encode('utf-8'))
    except (OSError, ValueError, LookupError, UnicodeError) as exc:
        raise AuthorEditorialIssueDetailError('현재 저장 원고·QC 기록을 읽지 못했습니다.') from exc
    opens: dict[str, dict] = {}
    closes: dict[str, list[dict]] = {}
    for event in events:
        if event['project_id'] != project_id:
            continue
        episode = event['episode']
        if not 1 <= episode <= 1000:
            raise AuthorEditorialIssueDetailError('편집 기록 회차가 올바르지 않습니다.')
        key = event['issue_id']
        if event['kind'] == 'OPEN':
            if key in opens:
                raise AuthorEditorialIssueDetailError('중복된 편집 이슈 원본이 있습니다.')
            opens[key] = event
        else:
            closes.setdefault(key, []).append(event)
    if set(closes) - set(opens):
        raise AuthorEditorialIssueDetailError('원본이 없는 편집 이슈 종료 기록이 있습니다.')
    chapters = {row.episode: row for row in workflow.chapters}
    rows = []
    for key, opening in opens.items():
        number = opening['episode']
        history = closes.get(key, ())
        if any(event['episode'] != number for event in history):
            raise AuthorEditorialIssueDetailError('편집 이슈 종료 회차가 원본과 다릅니다.')
        if number > through_episode:
            continue
        chapter = chapters[number]
        final_sha = chapter.manuscript_sha256
        last = max(history, key=lambda e: (e['created_at'], e['event_id'])) if history else None
        if last is not None and chapter.final_present and (
                last['revision'] == chapter.revision and last['final_sha256'] == final_sha):
            state = 'CLOSED_CURRENT'
        elif last is not None:
            state = 'CLOSED_STALE'
        elif chapter.final_present and (
                opening['revision'] == chapter.revision
                and opening['final_sha256'] == final_sha):
            state = 'OPEN_CURRENT'
        else:
            state = 'OPEN_STALE'
        rows.append(EditorialIssueDetailRow(
            episode=number, issue_id=key, category=opening['category'],
            note=opening['note'], state=state,
            opened_revision=opening['revision'],
            closed_revision=last['revision'] if last else None,
            current_revision=chapter.revision, final_present=chapter.final_present,
            review_status=chapter.review_status,
            reference_status=chapter.reference_status))
    rows.sort(key=lambda r: (r.episode, r.state == 'CLOSED_CURRENT', r.issue_id))
    identity = sha256()
    for item in (project_id, directory, str(through_episode), ledger_sha,
                 signature.hexdigest()):
        identity.update(item.encode('utf-8') + b'\0')
    for chapter in workflow.chapters:
        identity.update(json.dumps((chapter.episode, chapter.revision,
            chapter.manuscript_sha256, chapter.review_status,
            chapter.reference_status, chapter.remaining_actions),
            ensure_ascii=False).encode('utf-8'))
    return EditorialIssueDetailAudit(
        project_id=project_id, folder=directory,
        through_episode=through_episode, rows=tuple(rows),
        open_count=sum(r.state.startswith('OPEN') for r in rows),
        stale_count=sum(r.state.endswith('STALE') for r in rows),
        current_closed_count=sum(r.state == 'CLOSED_CURRENT' for r in rows),
        source_fingerprint=identity.hexdigest())


def require_current_author_editorial_issue_detail_audit(
    snapshot: EditorialIssueDetailAudit, store: EpisodeStore, project_id: str,
) -> None:
    """두 번째 직접 클릭에서 전체 원고·QC·편집 JSON 변경을 재확인."""
    if not isinstance(snapshot, EditorialIssueDetailAudit) or snapshot.project_id != project_id:
        raise AuthorEditorialIssueDetailError('작품이 변경됐습니다. 다시 직접 조회하세요.')
    current = build_author_editorial_issue_detail_audit(
        store, project_id, through_episode=snapshot.through_episode,
        issue_folder=snapshot.folder)
    if (current.source_fingerprint != snapshot.source_fingerprint
            or current.rows != snapshot.rows):
        raise AuthorEditorialIssueDetailError('원고·QC·편집 기록이 변경됐습니다. 다시 직접 조회하세요.')

@dataclass(frozen=True)
class EditorialIssueSavedFinal:
    """작가가 선택한 이슈 메모와 현재 저장 최종본의 읽기 전용 묶음."""
    episode: int
    issue_id: str = field(repr=False)
    category: str = ''
    state: str = ''
    revision: int = 0
    final_sha256: str = field(default='', repr=False)
    note: str = field(default='', repr=False)
    final_text: str = field(default='', repr=False)
    audit_fingerprint: str = field(default='', repr=False)


def read_author_editorial_issue_saved_final(
    snapshot: EditorialIssueDetailAudit, store: EpisodeStore, project_id: str,
    *, issue_id: str,
) -> EditorialIssueSavedFinal:
    """전수 감사 후 작가가 고른 단일 이슈의 원문만 로컬 메모리로 연다.

    저장된 최종본·이슈 JSON·QC·작품 상태를 읽기 전후 전수 재확인한다.
    종료 처리, 수정, 원고 저장 및 출판 승인과는 독립적이다.
    """
    if (not isinstance(snapshot, EditorialIssueDetailAudit)
            or type(issue_id) is not str or not issue_id):
        raise AuthorEditorialIssueDetailError('전수 조회한 이슈를 직접 선택하세요.')
    require_current_author_editorial_issue_detail_audit(
        snapshot, store, project_id)
    row = next((item for item in snapshot.rows if item.issue_id == issue_id), None)
    if row is None or not row.final_present or row.current_revision is None:
        raise AuthorEditorialIssueDetailError('현재 저장 최종본이 있는 이슈만 열 수 있습니다.')
    try:
        episode = store.get_episode(project_id, row.episode)
        if (episode.revision != row.current_revision
                or not episode.final_text.strip()):
            raise AuthorEditorialIssueDetailError('저장 최종본이 변경됐습니다. 다시 조회하세요.')
        digest = sha256(episode.final_text.encode('utf-8')).hexdigest()
        require_current_author_editorial_issue_detail_audit(
            snapshot, store, project_id)
    except (OSError, ValueError, LookupError, UnicodeError) as exc:
        raise AuthorEditorialIssueDetailError(
            '현재 저장 최종본·편집 기록을 다시 확인하세요.') from exc
    return EditorialIssueSavedFinal(
        episode=row.episode, issue_id=row.issue_id, category=row.category,
        state=row.state, revision=episode.revision, final_sha256=digest,
        note=row.note, final_text=episode.final_text,
        audit_fingerprint=snapshot.source_fingerprint)
