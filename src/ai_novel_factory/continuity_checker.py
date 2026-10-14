"""Stage 71 / ANF-REQ-051: offline, evidence-linked canon consistency checks.

Only explicitly identified manuscript claims are checked. No NLP claim extraction,
publication, automatic rewriting, persistence, or reference-novel ingestion.
Canon is loaded from existing Novel Bible, Character and World SQLite stores.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata

from .database.novel_bible import NovelBibleStore, _id
from .database.characters import CharacterStore
from .database.world_canon import WorldCanonStore

MAX_FACTS = 3000
MAX_CLAIMS = 500
MAX_MANUSCRIPT_CHARS = 1_000_000
_ALLOWED = {
    'novel_bible': frozenset({'value'}),
    'character': frozenset({'name', 'personality', 'goal', 'speech_style'}),
    'world': frozenset({'name', 'description'}),
}
_KEY = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
_ID = re.compile(r'[0-9a-f]{32}\Z')


class ContinuityError(ValueError):
    """Safe error containing no manuscript, secrets, or canon text."""


@dataclass(frozen=True)
class CanonFact:
    source: str
    entity_id: str  # bible rule key, character UUID, or world UUID
    field: str
    value: str  # user-authored canon only; never reference prose
    revision: int


@dataclass(frozen=True)
class ContinuityCanon:
    project_id: str
    project_revision: int
    facts: tuple[CanonFact, ...]


@dataclass(frozen=True)
class ManuscriptClaim:
    """A manually marked span whose exact text asserts a specific canon field."""
    source: str
    entity_id: str
    field: str
    start: int
    end: int
    asserted_value: str


@dataclass(frozen=True)
class ContinuityFinding:
    source: str
    entity_id: str
    field: str
    start: int
    end: int
    code: str  # CANON_CONFLICT (no draft/canon wording in records)
    canon_revision: int
    canon_sha256: str
    observed_sha256: str


@dataclass(frozen=True)
class ContinuityReport:
    project_id: str
    episode_number: int
    project_revision: int
    manuscript_sha256: str
    examined_claims: int
    findings: tuple[ContinuityFinding, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_declared_claims(self) -> bool:
        """True only for *the supplied claims*; never certifies the manuscript."""
        return not self.findings


def _plain(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 4000:
        raise ContinuityError('invalid fact value')
    if any(ord(c) == 0 or ord(c) == 127 or (ord(c) < 32 and c not in '\n\t') for c in value):
        raise ContinuityError('invalid fact value')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ContinuityError('invalid fact value') from None
    return value


def _identity(source: object, entity_id: object, field: object) -> tuple[str, str, str]:
    if type(source) is not str or source not in _ALLOWED or type(field) is not str or field not in _ALLOWED[source]:
        raise ContinuityError('unsupported canon field')
    if type(entity_id) is not str:
        raise ContinuityError('invalid canon identity')
    if source == 'novel_bible':
        if not _KEY.fullmatch(entity_id):
            raise ContinuityError('invalid canon identity')
    elif not _ID.fullmatch(entity_id):
        raise ContinuityError('invalid canon identity')
    return source, entity_id, field


def _revision(value: object, *, allow_zero: bool = False) -> int:
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= 2**31 - 1:
        raise ContinuityError('invalid canon revision')
    return value


def _fingerprint(value: str) -> str:
    return sha256(value.encode('utf-8')).hexdigest()


def _normalized(value: str) -> str:
    return unicodedata.normalize('NFC', value.strip())


def load_continuity_canon(
    project_id: str, *, bible: NovelBibleStore, characters: CharacterStore,
    world: WorldCanonStore,
) -> ContinuityCanon:
    """Snapshot only one project's existing canon; secrets deliberately excluded.

    All three store objects MUST be opened against the same SQLite database.
    This checks project revisions before/after reads, but cannot prove they
    share an underlying file; caller owns that configuration invariant.
    """
    try:
        project_id = _id(project_id)
        if not isinstance(bible, NovelBibleStore) or not isinstance(characters, CharacterStore) or not isinstance(world, WorldCanonStore):
            raise ContinuityError('invalid canon stores')
        start = (bible.get_project(project_id).revision,
                 characters.get_project(project_id).revision,
                 world.get_project(project_id).revision)
        if len(set(start)) != 1:
            raise ContinuityError('inconsistent canon snapshot')
        facts: list[CanonFact] = []
        for rule in bible.list_rules(project_id):
            facts.append(CanonFact('novel_bible', rule.key, 'value', rule.value, rule.revision))
        for item in characters.list_characters(project_id):
            for field in ('name', 'personality', 'goal', 'speech_style'):
                facts.append(CanonFact('character', item.character_id, field, getattr(item, field), item.revision))
        for item in world.list_entries(project_id):
            for field in ('name', 'description'):
                facts.append(CanonFact('world', item.entry_id, field, getattr(item, field), item.revision))
        end = (bible.get_project(project_id).revision,
               characters.get_project(project_id).revision,
               world.get_project(project_id).revision)
        if end != start:
            raise ContinuityError('canon changed during reading')
        if len(facts) > MAX_FACTS:
            raise ContinuityError('too many canon facts')
        return ContinuityCanon(project_id, _revision(start[0], allow_zero=True), tuple(facts))
    except ContinuityError:
        raise
    except (ValueError, TypeError, OverflowError):
        raise ContinuityError('failed to load canon') from None


def check_continuity(
    canon: ContinuityCanon, episode_number: int, manuscript: str,
    claims: tuple[ManuscriptClaim, ...], *, expected_project_revision: int | None = None,
) -> ContinuityReport:
    """Compare manually marked *literal claims* with Novel Bible/character/world.

    A claim's asserted_value must exactly equal manuscript[start:end], preventing
    substitution of an unrelated assertion. Missing canon and invalid evidence
    fail closed. No unmarked claim, synonym or narrative implication is parsed.
    """
    if type(canon) is not ContinuityCanon:
        raise ContinuityError('invalid canon snapshot')
    try:
        _id(canon.project_id)
    except ValueError:
        raise ContinuityError('invalid project identifier') from None
    _revision(canon.project_revision, allow_zero=True)
    if expected_project_revision is not None and (type(expected_project_revision) is not int or expected_project_revision != canon.project_revision):
        raise ContinuityError('stale canon snapshot')
    if type(episode_number) is not int or not 1 <= episode_number <= 1_000_000:
        raise ContinuityError('invalid episode number')
    if type(manuscript) is not str or not manuscript or len(manuscript) > MAX_MANUSCRIPT_CHARS:
        raise ContinuityError('invalid manuscript')
    try:
        manuscript.encode('utf-8')
    except UnicodeError:
        raise ContinuityError('invalid manuscript') from None
    if type(claims) is not tuple or len(claims) > MAX_CLAIMS:
        raise ContinuityError('invalid claims')
    if type(canon.facts) is not tuple or len(canon.facts) > MAX_FACTS:
        raise ContinuityError('invalid canon facts')
    facts: dict[tuple[str, str, str], CanonFact] = {}
    for fact in canon.facts:
        if type(fact) is not CanonFact:
            raise ContinuityError('invalid canon fact')
        key = _identity(fact.source, fact.entity_id, fact.field)
        _plain(fact.value)
        _revision(fact.revision)
        if key in facts:
            raise ContinuityError('duplicate canon fact')
        facts[key] = fact
    findings: list[ContinuityFinding] = []
    seen: set[tuple[str, str, str, int, int]] = set()
    for claim in claims:
        if type(claim) is not ManuscriptClaim:
            raise ContinuityError('invalid claim')
        key = _identity(claim.source, claim.entity_id, claim.field)
        if key not in facts:
            raise ContinuityError('claim refers to missing canon')
        if (type(claim.start) is not int or type(claim.end) is not int
                or not 0 <= claim.start < claim.end <= len(manuscript)):
            raise ContinuityError('invalid claim span')
        value = _plain(claim.asserted_value)
        if manuscript[claim.start:claim.end] != value:
            raise ContinuityError('claim does not match manuscript span')
        marker = (*key, claim.start, claim.end)
        if marker in seen:
            raise ContinuityError('duplicate claim')
        seen.add(marker)
        fact = facts[key]
        if _normalized(value) != _normalized(fact.value):
            findings.append(ContinuityFinding(*key, claim.start, claim.end,
                                              'CANON_CONFLICT', fact.revision,
                                              _fingerprint(fact.value), _fingerprint(value)))
    return ContinuityReport(canon.project_id, episode_number, canon.project_revision,
                            _fingerprint(manuscript), len(claims), tuple(findings))


def check_episode_draft(
    canon: ContinuityCanon, preview: 'EpisodeDraftPreview',
    claims: tuple[ManuscriptClaim, ...], *, expected_project_revision: int | None = None,
) -> ContinuityReport:
    """Stage 65/70 assembled episode preview adapter; validates immutable draft identity.

    The caller supplies explicit, human-identified claims. This does not
    replace the orchestration preliminary checker or later semantic QA.
    """
    from .episode_assembler import EpisodeDraftPreview

    if (type(preview) is not EpisodeDraftPreview
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False or preview.publication_approved is not False
            or preview.project_id != getattr(canon, 'project_id', None)
            or type(preview.draft) is not str
            or not preview.draft or len(preview.draft) > MAX_MANUSCRIPT_CHARS):
        raise ContinuityError('invalid or altered episode draft')
    try:
        digest = _fingerprint(preview.draft)
    except UnicodeError:
        raise ContinuityError('invalid or altered episode draft') from None
    if preview.draft_sha256 != digest:
        raise ContinuityError('invalid or altered episode draft')
    return check_continuity(canon, preview.episode_number, preview.draft, claims,
                            expected_project_revision=expected_project_revision)
