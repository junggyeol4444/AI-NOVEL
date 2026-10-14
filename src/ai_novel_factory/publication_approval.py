"""Stage 89 / ANF-REQ-067: explicit, offline publication-review consent gate.

Approval is scoped to a particular immutable evidence snapshot. It is not
identity authentication, a manuscript-finalization operation, or a publisher.
No manuscript, source novel, API key or confirmation phrase is persisted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import hmac
import json
from pathlib import Path
import re
import secrets
from typing import Mapping
from uuid import uuid4

from .database.novel_bible import _id, _now
from .database.reference_catalog import ReferenceCatalog
from .ending_audit import EndingReport, EndingReviewStore
from .manuscript_versions import ManuscriptVersionStore
from .reference_similarity_checker import ReferenceMaterial, TextSpan
from .reference_similarity_records import ReferenceSimilarityReviewStore

_SHA = re.compile(r'[0-9a-f]{64}\Z')


class PublicationApprovalError(ValueError):
    """Messages deliberately omit manuscript and secret material."""


@dataclass(frozen=True)
class EpisodeSimilarityInput:
    episode: int
    scenes: tuple[TextSpan, ...]
    beats: tuple[str, ...]


@dataclass(frozen=True)
class PublicationReviewEvidence:
    ending_report: EndingReport
    reference_catalog: ReferenceCatalog
    similarity_store: ReferenceSimilarityReviewStore | None
    references: tuple[ReferenceMaterial, ...] = field(default_factory=tuple, repr=False)
    annotations: tuple[EpisodeSimilarityInput, ...] = ()
    no_references_confirmed: bool = False
    foreshadow_inventory_reviewed: bool = False
    conflict_inventory_reviewed: bool = False
    timeline_inventory_reviewed: bool = False


@dataclass(frozen=True)
class ApprovalRequest:
    project_id: str
    request_id: str
    ending_episode: int
    episode_count: int
    manifest_sha256: str
    status: str
    created_at: str
    decided_at: str | None
    identity_authenticated: bool = False
    publication_executed: bool = False


@dataclass(frozen=True)
class ApprovalChallenge:
    request: ApprovalRequest
    code: str = field(repr=False)

    def confirmation(self, decision: str) -> str:
        if decision not in ('APPROVE', 'REJECT'):
            raise PublicationApprovalError('승인 또는 거절만 선택할 수 있습니다.')
        return f'{decision} {self.request.request_id} {self.code}'


@dataclass(frozen=True)
class PublicationGateReceipt:
    project_id: str
    request_id: str
    manifest_sha256: str
    status: str = 'LOCAL_APPROVAL_CURRENT_NOT_PUBLISHED'
    identity_authenticated: bool = False
    publication_executed: bool = False


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


class PublicationApprovalStore(EndingReviewStore):
    """No publishing or manuscript writes. A separate gate for future adapters.

    The caller must supply a freshly evaluated stage-88 ending report and,
    when references exist, stage-78 current-clear recorded similarity inputs.
    All evidence is re-evaluated at request, decision and authorization time.
    """

    def __init__(self, database_path: str | Path):
        super().__init__(database_path)
        # Ensure version schema is initialized before taking write transactions.
        with ManuscriptVersionStore(self._path):
            pass
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_publication_review (
                request_id TEXT PRIMARY KEY CHECK(length(request_id)=32),
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                ending_episode INTEGER NOT NULL,
                episode_count INTEGER NOT NULL,
                manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
                challenge_sha256 TEXT NOT NULL CHECK(length(challenge_sha256)=64),
                status TEXT NOT NULL CHECK(status IN
                    ('PENDING','APPROVED','REJECTED','REVOKED','SUPERSEDED')),
                created_at TEXT NOT NULL, decided_at TEXT
            )''')
            self._db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS
                ix_publication_one_active ON bible_publication_review(project_id)
                WHERE status IN ('PENDING','APPROVED')''')
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_publication_review_events (
                event_id TEXT PRIMARY KEY CHECK(length(event_id)=32),
                request_id TEXT NOT NULL REFERENCES bible_publication_review(request_id)
                    ON DELETE CASCADE,
                action TEXT NOT NULL CHECK(action IN
                    ('REQUESTED','APPROVED','REJECTED','REVOKED','SUPERSEDED')),
                occurred_at TEXT NOT NULL
            )''')

    def _event(self, request_id: str, action: str) -> None:
        self._db.execute('''INSERT INTO bible_publication_review_events VALUES (?,?,?,?)''',
                         (uuid4().hex, request_id, action, _now()))

    def _snapshot(self, project_id: str, evidence: PublicationReviewEvidence) -> tuple[str, int, int]:
        """Validate *current* evidence, including all final candidate versions.

        Must run while caller holds a write transaction for atomic DB snapshot.
        External reference catalogs can still change: gate must recheck them.
        """
        if type(evidence) is not PublicationReviewEvidence:
            raise PublicationApprovalError('출판 전 검토 자료가 필요합니다.')
        if not all(type(v) is bool and v is True for v in (
                evidence.foreshadow_inventory_reviewed,
                evidence.conflict_inventory_reviewed,
                evidence.timeline_inventory_reviewed)):
            raise PublicationApprovalError('완결 검토 범위 확인이 필요합니다.')
        report = evidence.ending_report
        if type(report) is not EndingReport or report.project_id != project_id:
            raise PublicationApprovalError('완결 검토의 작품이 일치하지 않습니다.')
        try:
            current = self.require_current_review(report,
                foreshadow_inventory_reviewed=True,
                conflict_inventory_reviewed=True,
                timeline_inventory_reviewed=True)
        except Exception:
            raise PublicationApprovalError('최신 완결 검토가 통과되지 않았습니다.') from None
        if type(evidence.reference_catalog) is not ReferenceCatalog:
            raise PublicationApprovalError('참고작 등록 상태 확인이 필요합니다.')
        if type(evidence.no_references_confirmed) is not bool:
            raise PublicationApprovalError('참고작 검토 선언 형식이 올바르지 않습니다.')
        if type(evidence.references) is not tuple or type(evidence.annotations) is not tuple:
            raise PublicationApprovalError('참고작 검사 자료 형식이 올바르지 않습니다.')
        catalog = evidence.reference_catalog
        reference_count = catalog.count()
        if reference_count > 20:
            raise PublicationApprovalError('참고작 검사 범위를 확인할 수 없습니다.')
        refs = evidence.references
        if reference_count == 0:
            if not evidence.no_references_confirmed or refs or evidence.annotations:
                raise PublicationApprovalError('참고작 미등록 상태를 명시적으로 확인해야 합니다.')
        else:
            if (evidence.no_references_confirmed or len(refs) != reference_count or
                    type(evidence.similarity_store) is not ReferenceSimilarityReviewStore):
                raise PublicationApprovalError('등록 참고작의 유사성 검사 기록이 필요합니다.')
            catalog_ids = {r.reference_id for r in catalog.list(limit=reference_count)}
            if (len(catalog_ids) != reference_count or
                    {r.reference_id for r in refs} != catalog_ids or
                    any(catalog.get(r.reference_id).status != 'analyzed' for r in refs)):
                raise PublicationApprovalError('등록 참고작 목록이 검사 자료와 다릅니다.')
        try:
            with ManuscriptVersionStore(self._path) as versions:
                episodes = versions.list_episodes(project_id)
                by_number = {ep.episode: ep for ep in episodes}
                if (len(episodes) != current.ending_episode or
                        set(by_number) != set(range(1, current.ending_episode + 1))):
                    raise PublicationApprovalError('완결 범위의 모든 회차가 필요합니다.')
                annotations = {a.episode: a for a in evidence.annotations
                               if type(a) is EpisodeSimilarityInput}
                if reference_count and (len(annotations) != len(evidence.annotations)
                        or set(annotations) != set(by_number)):
                    raise PublicationApprovalError('회차별 참고작 검사가 누락되었습니다.')
                manifest_episodes = []
                for number in range(1, current.ending_episode + 1):
                    ep = by_number[number]
                    if not ep.final_text.strip():
                        raise PublicationApprovalError('최종 원고 후보가 누락되었습니다.')
                    history = versions.list_versions(project_id, number)
                    if (not history or history[-1].kind != 'FINAL' or
                            history[-1].episode_revision != ep.revision or
                            history[-1].final_text != ep.final_text or
                            history[-1].draft != ep.draft):
                        raise PublicationApprovalError('최신 FINAL 원고 버전이 필요합니다.')
                    manuscript_sha = sha256(ep.final_text.encode('utf-8')).hexdigest()
                    similarity = None
                    if reference_count:
                        ann = annotations[number]
                        if type(ann.scenes) is not tuple or type(ann.beats) is not tuple:
                            raise PublicationApprovalError('회차별 참고작 검사 형식이 올바르지 않습니다.')
                        try:
                            receipt = evidence.similarity_store.require_current_clear_review(
                                project_id, number, ep.final_text, references=refs,
                                draft_scenes=ann.scenes, draft_beats=ann.beats,
                                required_reference_ids=tuple(r.reference_id for r in refs),
                                catalog=catalog)
                        except Exception:
                            raise PublicationApprovalError('현재 원고의 참고작 유사성 검사 통과 기록이 필요합니다.') from None
                        similarity = (receipt.reference_set_sha256, receipt.status,
                                      receipt.draft_sha256)
                    manifest_episodes.append((number, ep.revision, manuscript_sha,
                                              history[-1].fingerprint, similarity))
        except PublicationApprovalError:
            raise
        except Exception:
            raise PublicationApprovalError('원고 버전 검토에 실패했습니다.') from None
        project_revision = self.get_project(project_id).revision
        if project_revision != current.project_revision:
            raise PublicationApprovalError('완결 검토 후 작품 설정이 변경되었습니다.')
        digest = _digest(dict(project_id=project_id, project_revision=project_revision,
                              ending_episode=current.ending_episode,
                              ending_digest=current.evidence_digest,
                              episodes=manifest_episodes,
                              reference_count=reference_count,
                              references=sorted((r.reference_id, r.source_sha256)
                                                for r in refs)))
        return digest, current.ending_episode, len(manifest_episodes)

    def _request(self, row) -> ApprovalRequest:
        if row is None:
            raise PublicationApprovalError('출판 검토 요청을 찾을 수 없습니다.')
        if (row['status'] not in ('PENDING','APPROVED','REJECTED','REVOKED','SUPERSEDED')
                or not _SHA.fullmatch(row['manifest_sha256'])):
            raise PublicationApprovalError('출판 검토 기록이 손상되었습니다.')
        return ApprovalRequest(row['project_id'], row['request_id'], row['ending_episode'],
                               row['episode_count'], row['manifest_sha256'], row['status'],
                               row['created_at'], row['decided_at'])

    def get_request(self, project_id: str, request_id: str) -> ApprovalRequest:
        project_id, request_id = _id(project_id), _id(request_id)
        row = self._db.execute('''SELECT * FROM bible_publication_review
            WHERE project_id=? AND request_id=?''', (project_id, request_id)).fetchone()
        return self._request(row)

    def list_requests(self, project_id: str) -> tuple[ApprovalRequest, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        return tuple(self._request(row) for row in self._db.execute('''
            SELECT * FROM bible_publication_review WHERE project_id=?
            ORDER BY created_at, request_id''', (project_id,)))

    def begin_review(self, project_id: str, evidence: PublicationReviewEvidence) -> ApprovalChallenge:
        project_id = _id(project_id)
        code = secrets.token_hex(12)
        request_id = uuid4().hex
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            manifest, ending_episode, count = self._snapshot(project_id, evidence)
            rows = self._db.execute('''SELECT request_id FROM bible_publication_review
                WHERE project_id=? AND status IN ('PENDING','APPROVED')''',
                (project_id,)).fetchall()
            for row in rows:
                self._db.execute('''UPDATE bible_publication_review
                    SET status='SUPERSEDED', decided_at=? WHERE request_id=?''',
                    (_now(), row['request_id']))
                self._event(row['request_id'], 'SUPERSEDED')
            challenge_hash = sha256(code.encode('ascii')).hexdigest()
            self._db.execute('''INSERT INTO bible_publication_review VALUES
                (?, ?, ?, ?, ?, ?, 'PENDING', ?, NULL)''',
                (request_id, project_id, ending_episode, count, manifest,
                 challenge_hash, _now()))
            self._event(request_id, 'REQUESTED')
        return ApprovalChallenge(self.get_request(project_id, request_id), code)

    def decide(self, project_id: str, request_id: str, evidence: PublicationReviewEvidence, *,
               decision: str, confirmation: str) -> ApprovalRequest:
        project_id, request_id = _id(project_id), _id(request_id)
        if type(decision) is not str or decision not in ('APPROVE','REJECT'):
            raise PublicationApprovalError('승인 또는 거절을 명시해야 합니다.')
        if type(confirmation) is not str or len(confirmation) > 128:
            raise PublicationApprovalError('명시적 확인 문구가 필요합니다.')
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            row = self._db.execute('''SELECT * FROM bible_publication_review
                WHERE project_id=? AND request_id=?''', (project_id, request_id)).fetchone()
            request = self._request(row)
            if request.status != 'PENDING':
                raise PublicationApprovalError('이미 처리된 출판 검토 요청입니다.')
            parts = confirmation.split(' ')
            if (len(parts) != 3 or parts[0] != decision or parts[1] != request_id
                    or not re.fullmatch(r'[0-9a-f]{24}', parts[2]) or
                    not hmac.compare_digest(sha256(parts[2].encode('ascii')).hexdigest(),
                                            row['challenge_sha256'])):
                raise PublicationApprovalError('명시적 확인 문구가 일치하지 않습니다.')
            if decision == 'APPROVE':
                manifest, ending_episode, count = self._snapshot(project_id, evidence)
                if (manifest != request.manifest_sha256 or ending_episode != request.ending_episode
                        or count != request.episode_count):
                    raise PublicationApprovalError('원고 또는 검토 근거가 변경되었습니다.')
            status = 'APPROVED' if decision == 'APPROVE' else 'REJECTED'
            self._db.execute('''UPDATE bible_publication_review SET status=?,
                decided_at=?, challenge_sha256=? WHERE request_id=?''',
                (status, _now(), '0'*64, request_id))
            self._event(request_id, status)
        return self.get_request(project_id, request_id)

    def revoke(self, project_id: str, request_id: str, *, confirmation: str) -> ApprovalRequest:
        project_id, request_id = _id(project_id), _id(request_id)
        if type(confirmation) is not str or confirmation != f'REVOKE {request_id}':
            raise PublicationApprovalError('승인 철회를 명시해야 합니다.')
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            request = self.get_request(project_id, request_id)
            if request.status != 'APPROVED':
                raise PublicationApprovalError('철회할 활성 승인이 없습니다.')
            self._db.execute('''UPDATE bible_publication_review
                SET status='REVOKED', decided_at=? WHERE request_id=?''',
                (_now(), request_id))
            self._event(request_id, 'REVOKED')
        return self.get_request(project_id, request_id)

    def require_current_publication_approval(self, project_id: str, request_id: str,
                                             evidence: PublicationReviewEvidence) -> PublicationGateReceipt:
        """Return local evidence of consent; DOES NOT publish or finalize anything."""
        project_id, request_id = _id(project_id), _id(request_id)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            request = self.get_request(project_id, request_id)
            if request.status != 'APPROVED':
                raise PublicationApprovalError('현재 유효한 출판 승인이 없습니다.')
            manifest, ending_episode, count = self._snapshot(project_id, evidence)
            if (manifest != request.manifest_sha256 or ending_episode != request.ending_episode
                    or count != request.episode_count):
                raise PublicationApprovalError('승인 이후 원고 또는 검사 근거가 변경되었습니다.')
        return PublicationGateReceipt(project_id, request_id, manifest)

    def list_events(self, project_id: str, request_id: str) -> tuple[str, ...]:
        self.get_request(project_id, request_id)
        return tuple(row[0] for row in self._db.execute('''
            SELECT action FROM bible_publication_review_events
            WHERE request_id=? ORDER BY rowid''', (request_id,)))
