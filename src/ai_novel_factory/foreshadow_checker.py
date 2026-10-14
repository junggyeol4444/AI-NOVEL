"""Stage 74: offline, evidence-linked foreshadowing continuity checker.

A reviewer explicitly labels a foreshadowing thread's action or state in a
manuscript span. Only the locally stored Novel Bible's ForeshadowStore is used.
This does NOT extract claims from prose, modify canon, approve, or publish.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .database.foreshadow import ACTIONS, STATUSES, ForeshadowError, ForeshadowStore
from .database.novel_bible import NovelBibleError, _id

MAX_MANUSCRIPT_CHARS = 1_000_000
MAX_CLAIMS = 500
MAX_EVIDENCE_CHARS = 4000


class ForeshadowCheckerError(ValueError):
    """Content-free validation error."""


@dataclass(frozen=True)
class ForeshadowClaim:
    """Reviewer-marked manuscript span; exactly one of action or status.

    Actions INSTALL, REVISIT, RESOLVE, ABANDON refer to a record *in this
    episode*. Status OPEN, DEVELOPING, RESOLVED, ABANDONED refers to the
    canonical state *at the end of this episode* (same-episode sequence matters).
    """
    thread_id: str
    start: int
    end: int
    evidence: str
    claimed_action: str | None = None
    claimed_status: str | None = None


@dataclass(frozen=True)
class ForeshadowFinding:
    thread_id: str
    start: int
    end: int
    code: str  # ACTION_NOT_RECORDED, ACTION_CONFLICT, STATUS_CONFLICT, NOT_INSTALLED
    evidence_sha256: str
    actual_status: str


@dataclass(frozen=True)
class ForeshadowReport:
    project_id: str
    episode_number: int
    project_revision: int
    manuscript_sha256: str
    examined_claims: int
    findings: tuple[ForeshadowFinding, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_declared_claims(self) -> bool:
        """Only reviewer-labelled assertions have been compared with canon."""
        return not self.findings


def _digest(value: str) -> str:
    try:
        return sha256(value.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise ForeshadowCheckerError('invalid manuscript or evidence') from None


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise ForeshadowCheckerError('invalid episode')
    return value


def check_foreshadowing(
    store: ForeshadowStore, project_id: str, episode_number: int,
    manuscript: str, claims: tuple[ForeshadowClaim, ...],
    *, expected_project_revision: int | None = None,
) -> ForeshadowReport:
    """Compare labelled evidence against one project's chronology, read-only.

    No attempt to infer what the author *intended* or whether an unwritten
    payoff will occur. A missing action is reported, never silently inserted.
    Optimistic revision checks detect ordinary concurrent edits, but do not
    provide a serializable DB snapshot across multiple writers.
    """
    if not isinstance(store, ForeshadowStore):
        raise ForeshadowCheckerError('invalid foreshadowing store')
    try:
        project_id = _id(project_id)
    except NovelBibleError:
        raise ForeshadowCheckerError('invalid project id') from None
    episode_number = _episode(episode_number)
    if (type(manuscript) is not str or not manuscript.strip()
            or len(manuscript) > MAX_MANUSCRIPT_CHARS):
        raise ForeshadowCheckerError('invalid manuscript')
    manuscript_sha = _digest(manuscript)
    if type(claims) is not tuple or len(claims) > MAX_CLAIMS:
        raise ForeshadowCheckerError('invalid claims')
    if (expected_project_revision is not None and
            (type(expected_project_revision) is not int or
             not 0 <= expected_project_revision <= 2**31 - 1)):
        raise ForeshadowCheckerError('invalid revision')

    try:
        revision = store.get_project(project_id).revision
        if expected_project_revision is not None and revision != expected_project_revision:
            raise ForeshadowCheckerError('stale foreshadow snapshot')
        store.audit(project_id)  # fail closed on corrupt/out-of-order state transitions
        findings: list[ForeshadowFinding] = []
        seen: set[tuple[str, int, int, str, str]] = set()
        for claim in claims:
            if type(claim) is not ForeshadowClaim:
                raise ForeshadowCheckerError('invalid claim')
            try:
                thread_id = _id(claim.thread_id)
            except NovelBibleError:
                raise ForeshadowCheckerError('invalid thread id') from None
            if (type(claim.start) is not int or type(claim.end) is not int
                    or not 0 <= claim.start < claim.end <= len(manuscript)
                    or type(claim.evidence) is not str or not claim.evidence.strip()
                    or len(claim.evidence) > MAX_EVIDENCE_CHARS
                    or manuscript[claim.start:claim.end] != claim.evidence):
                raise ForeshadowCheckerError('invalid evidence')
            action, status = claim.claimed_action, claim.claimed_status
            if ((action is None) == (status is None) or
                    (action is not None and (type(action) is not str or action not in ACTIONS)) or
                    (status is not None and (type(status) is not str or status not in STATUSES))):
                raise ForeshadowCheckerError('invalid foreshadow assertion')
            marker = (thread_id, claim.start, claim.end, action or '', status or '')
            if marker in seen:
                raise ForeshadowCheckerError('duplicate foreshadow claim')
            seen.add(marker)
            # get_thread/get_at cannot read an item belonging to another project.
            history = store.history(project_id, thread_id)
            current = store.get_at(project_id, thread_id, episode_number)
            code = None
            if status is not None:
                if current.status == 'NOT_INSTALLED':
                    code = 'NOT_INSTALLED'
                elif status != current.status:
                    code = 'STATUS_CONFLICT'
            else:
                on_episode = tuple(event.action for event in history
                                   if event.episode == episode_number)
                if action in on_episode:
                    pass
                elif on_episode:
                    code = 'ACTION_CONFLICT'
                else:
                    code = 'ACTION_NOT_RECORDED'
            if code is not None:
                findings.append(ForeshadowFinding(thread_id, claim.start, claim.end,
                    code, _digest(claim.evidence), current.status))
        if store.get_project(project_id).revision != revision:
            raise ForeshadowCheckerError('foreshadowing changed during check')
        return ForeshadowReport(project_id, episode_number, revision,
                                manuscript_sha, len(claims), tuple(findings))
    except ForeshadowCheckerError:
        raise
    except (ForeshadowError, NovelBibleError, TypeError, OverflowError, ValueError):
        raise ForeshadowCheckerError('foreshadow lookup failed') from None


def check_episode_foreshadowing(
    store: ForeshadowStore, preview: object, claims: tuple[ForeshadowClaim, ...],
    *, expected_project_revision: int | None = None,
) -> ForeshadowReport:
    """Validate an unapproved stage-65 episode preview before looking up canon."""
    from .episode_assembler import EpisodeDraftPreview

    if (type(preview) is not EpisodeDraftPreview
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False
            or preview.publication_approved is not False
            or type(preview.draft) is not str or not preview.draft.strip()
            or len(preview.draft) > MAX_MANUSCRIPT_CHARS
            or type(preview.draft_sha256) is not str
            or preview.draft_sha256 != _digest(preview.draft)):
        raise ForeshadowCheckerError('invalid or altered episode draft')
    return check_foreshadowing(store, preview.project_id, preview.episode_number,
        preview.draft, claims, expected_project_revision=expected_project_revision)
