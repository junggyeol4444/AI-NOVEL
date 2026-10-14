"""Stage 72: compare explicitly marked character knowledge usage with episode history.

Offline, read-only, fail-closed structured check. No NLP, auto editing, approval,
network, reference-novel prose or publication action is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .database.character_knowledge import CharacterKnowledgeStore, KnowledgeError
from .database.novel_bible import NovelBibleError, _id

MAX_USES = 500
MAX_MANUSCRIPT_CHARS = 1_000_000


class KnowledgeCheckerError(ValueError):
    """Intentionally carries no content or personally identifying canon facts."""


@dataclass(frozen=True)
class KnowledgeUseClaim:
    """Human-labelled evidence that a character uses a fact at [start, end)."""
    character_id: str
    fact_id: str
    start: int
    end: int
    evidence: str


@dataclass(frozen=True)
class KnowledgeFinding:
    character_id: str
    fact_id: str
    start: int
    end: int
    code: str  # NOT_RECORDED, NOT_YET_LEARNED, NOT_KNOWN
    effective_episode: int | None
    evidence_sha256: str


@dataclass(frozen=True)
class KnowledgeReport:
    project_id: str
    episode_number: int
    project_revision: int
    manuscript_sha256: str
    examined_uses: int
    findings: tuple[KnowledgeFinding, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_declared_uses(self) -> bool:
        """Only claims supplied by a human were checked; no full-prose guarantee."""
        return not self.findings


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise KnowledgeCheckerError('invalid episode')
    return value


def _digest(value: str) -> str:
    try:
        return sha256(value.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise KnowledgeCheckerError('invalid manuscript or evidence') from None


def check_character_knowledge(
    store: CharacterKnowledgeStore, project_id: str, episode_number: int,
    manuscript: str, claims: tuple[KnowledgeUseClaim, ...],
    *, expected_project_revision: int | None = None,
) -> KnowledgeReport:
    """Check knowledge at the episode of a *human-annotated* manuscript span.

    A missing event never means a fact is available to a character. Rejects
    invalid, cross-project, stale, or corrupt inputs instead of masking them as
    findings. Revision comparisons catch canon updates during ordinary reads;
    this is not a DB-wide serializable snapshot under simultaneous writers.
    """
    if not isinstance(store, CharacterKnowledgeStore):
        raise KnowledgeCheckerError('invalid knowledge store')
    try:
        project_id = _id(project_id)
    except NovelBibleError:
        raise KnowledgeCheckerError('invalid project identifier') from None
    episode_number = _episode(episode_number)
    if (type(manuscript) is not str or not manuscript.strip()
            or len(manuscript) > MAX_MANUSCRIPT_CHARS):
        raise KnowledgeCheckerError('invalid manuscript')
    manuscript_digest = _digest(manuscript)
    if type(claims) is not tuple or len(claims) > MAX_USES:
        raise KnowledgeCheckerError('invalid knowledge claims')
    if (expected_project_revision is not None and
            (type(expected_project_revision) is not int or
             not 0 <= expected_project_revision <= 2**31 - 1)):
        raise KnowledgeCheckerError('invalid expected revision')
    try:
        revision = store.get_project(project_id).revision
        if expected_project_revision is not None and revision != expected_project_revision:
            raise KnowledgeCheckerError('stale knowledge snapshot')
        findings: list[KnowledgeFinding] = []
        checked: set[tuple[str, str, int, int]] = set()
        for claim in claims:
            if type(claim) is not KnowledgeUseClaim:
                raise KnowledgeCheckerError('invalid knowledge claim')
            try:
                character_id, fact_id = _id(claim.character_id), _id(claim.fact_id)
            except NovelBibleError:
                raise KnowledgeCheckerError('invalid knowledge claim identity') from None
            if (type(claim.start) is not int or type(claim.end) is not int or
                    not 0 <= claim.start < claim.end <= len(manuscript) or
                    type(claim.evidence) is not str or not claim.evidence.strip() or
                    len(claim.evidence) > 4000 or
                    manuscript[claim.start:claim.end] != claim.evidence):
                raise KnowledgeCheckerError('invalid manuscript evidence')
            evidence_digest = _digest(claim.evidence)
            marker = (character_id, fact_id, claim.start, claim.end)
            if marker in checked:
                raise KnowledgeCheckerError('duplicate knowledge claim')
            checked.add(marker)
            state = store.knowledge_at(project_id, character_id, fact_id, episode_number)
            if not state.knows:
                code = {
                    'not_recorded': 'NOT_RECORDED',
                    'not_yet_learned': 'NOT_YET_LEARNED',
                    'not_known': 'NOT_KNOWN',
                }.get(state.status)
                if code is None:
                    raise KnowledgeCheckerError('invalid knowledge state')
                findings.append(KnowledgeFinding(character_id, fact_id, claim.start,
                                                 claim.end, code, state.effective_episode,
                                                 evidence_digest))
        if store.get_project(project_id).revision != revision:
            raise KnowledgeCheckerError('knowledge changed during check')
        return KnowledgeReport(project_id, episode_number, revision, manuscript_digest,
                               len(claims), tuple(findings))
    except KnowledgeCheckerError:
        raise
    except (NovelBibleError, KnowledgeError, TypeError, OverflowError):
        raise KnowledgeCheckerError('knowledge lookup failed') from None


def check_episode_knowledge(
    store: CharacterKnowledgeStore, preview: object,
    claims: tuple[KnowledgeUseClaim, ...],
    *, expected_project_revision: int | None = None,
) -> KnowledgeReport:
    """Apply the same evidence check to a verified stage-65 episode draft."""
    from .episode_assembler import EpisodeDraftPreview

    if (type(preview) is not EpisodeDraftPreview
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False
            or preview.publication_approved is not False
            or type(preview.draft) is not str
            or not preview.draft.strip()
            or len(preview.draft) > MAX_MANUSCRIPT_CHARS
            or type(preview.draft_sha256) is not str
            or preview.draft_sha256 != _digest(preview.draft)):
        raise KnowledgeCheckerError('invalid or altered episode draft')
    return check_character_knowledge(
        store, preview.project_id, preview.episode_number, preview.draft, claims,
        expected_project_revision=expected_project_revision)
