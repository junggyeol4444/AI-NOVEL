"""Opt-in, local-only reference analysis and longform draft similarity review.

Only numerical statistics enter the local model context. The selected works'
original text is held transiently in process memory for local comparison; it is
never saved in the novel database, reference catalog, prompts, logs or uploads.
This is not human approval, copyright clearance, or permission to publish.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from statistics import mean

from .database.reference_catalog import ReferenceCatalog
from .database.reference_profiles import ReferenceProfileStore
from .reference_similarity_checker import (
    ReferenceMaterial, TextSpan, check_reference_similarity,
)
from .references.copy_protection import (
    MAX_RAW_REFERENCE_CHARS, MAX_REFERENCE_UNITS, _normalize,
)
from .references.episode_splitter import split_episodes
from .references.import_pipeline import _LIMITS, _open_bounded, _parse_bytes
from .references.reference_profile import build_reference_profile


class ReferenceBatchError(ValueError):
    """Sanitized error messages without private paths or manuscript excerpts."""


@dataclass(frozen=True)
class SelectedReference:
    path: Path = field(repr=False)
    reference_id: str
    source_sha256: str
    material: ReferenceMaterial = field(repr=False)


@dataclass(frozen=True)
class PreparedReferenceBatch:
    catalog_path: Path = field(repr=False)
    references: tuple[SelectedReference, ...] = field(repr=False)
    aggregate_context: str
    raw_text_persisted: bool = False
    model_receives_reference_prose: bool = False
    publication_approved: bool = False


@dataclass(frozen=True)
class ReferenceBatchReview:
    check_status: str
    detail: str
    blocked: bool
    fully_cleared: bool = False
    publication_approved: bool = False


def _selected_path(value: object) -> Path:
    if (type(value) is not str or not value
            or value.startswith(('\\\\', '//'))):
        raise ReferenceBatchError('참고작은 직접 선택한 로컬 절대 경로여야 합니다.')
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink()
            or path.suffix.lower() not in _LIMITS):
        raise ReferenceBatchError('선택한 참고작의 경로 또는 형식이 올바르지 않습니다.')
    return path


def prepare_reference_batch(
    selected_paths: tuple[str, ...], *, catalog_path: str | Path,
    manuscript_database_path: str | Path,
) -> PreparedReferenceBatch:
    """Preflight ALL explicitly selected formats before saving any metadata.

    This is invoked only from the author's approved batch-start action. The
    reference catalog is separate from the user's manuscript SQLite file.
    """
    if (type(selected_paths) is not tuple or not 1 <= len(selected_paths) <= 100
            or len(set(selected_paths)) != len(selected_paths)):
        raise ReferenceBatchError('참고작은 중복 없이 1~100개 직접 선택해야 합니다.')
    catalog_path = Path(catalog_path)
    manuscript_database_path = Path(manuscript_database_path)
    if (not catalog_path.is_absolute() or catalog_path.is_symlink()
            or catalog_path.resolve() == manuscript_database_path.resolve()):
        raise ReferenceBatchError('참고작 분석 DB는 원고 DB와 분리된 로컬 파일이어야 합니다.')
    total_bytes = total_chars = total_units = 0
    staged = []
    seen_hashes = set()
    for value in selected_paths:
        path = _selected_path(value)
        try:
            raw = _open_bounded(path, _LIMITS[path.suffix.lower()])
            total_bytes += len(raw)
            if total_bytes > 32 * 1024 * 1024:
                raise ReferenceBatchError('선택한 참고작 파일의 총 크기 제한을 초과했습니다.')
            digest = sha256(raw).hexdigest()
            if digest in seen_hashes:
                raise ReferenceBatchError('동일한 참고작 내용은 중복 등록할 수 없습니다.')
            seen_hashes.add(digest)
            parsed = _parse_bytes(raw, path.suffix.lower(), None)
            if getattr(parsed, 'image_only_pages', ()):
                raise ReferenceBatchError('이미지 전용 PDF 페이지는 전수 비교할 수 없습니다.')
            total_chars += len(parsed.text)
            total_units += len(_normalize(parsed.text))
            if total_chars > MAX_RAW_REFERENCE_CHARS or total_units > MAX_REFERENCE_UNITS:
                raise ReferenceBatchError(
                    '선택한 참고작 전체가 비교 한도를 초과했습니다. 부분 검사로 통과시키지 않습니다.')
            profile = build_reference_profile(parsed, split=split_episodes(parsed))
        except ReferenceBatchError:
            raise
        except (OSError, ValueError, TypeError, UnicodeError):
            raise ReferenceBatchError('선택한 참고작 전체를 분석하지 못했습니다.') from None
        staged.append((path, digest, len(raw), parsed.text, profile))
    try:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        references = []
        with ReferenceCatalog(catalog_path) as catalog:
            profiles = ReferenceProfileStore(catalog)
            for path, digest, byte_count, prose, profile in staged:
                record = catalog.register(
                    file_name=path.name, source_format=path.suffix.lower().lstrip('.'),
                    byte_count=byte_count, sha256=digest)
                if record.status in {'registered', 'failed'}:
                    record = catalog.change_status(record.reference_id, 'analyzing')
                profiles.save(record.reference_id, profile)
                if record.status == 'analyzing':
                    record = catalog.change_status(record.reference_id, 'analyzed')
                if record.status != 'analyzed':
                    raise ReferenceBatchError('참고작 분석 완료 상태가 아닙니다.')
                references.append(SelectedReference(
                    path, record.reference_id, digest,
                    ReferenceMaterial(record.reference_id, digest, prose)))
    except ReferenceBatchError:
        raise
    except (OSError, ValueError):
        raise ReferenceBatchError('참고작 분석 통계를 저장하지 못했습니다.') from None
    observed = [row[4] for row in staged]
    aggregate = (
        f'선택한 참고작 {len(observed)}종의 통계적 관찰(작가 Novel Bible/Style Bible 우선, '
        '원문 문장·고유명사·고유 설정 복제 금지): '
        f'대사 비율 평균 {mean(p.dialogue_ratio for p in observed):.3f}; '
        f'평균 문장 길이 {mean(p.average_sentence_characters for p in observed):.1f}자; '
        f'사건 단서 밀도 {mean(p.event_cue_density_per_1000 for p in observed):.2f}/천자; '
        f'후킹 후보 회차 비율 '
        f'{mean(p.cliffhanger_candidate_episodes / p.episode_count for p in observed):.3f}. '
        '참고 통계는 미검수이며 창작물 유사성 통과·출판 승인을 뜻하지 않음.'
    )
    return PreparedReferenceBatch(catalog_path, tuple(references), aggregate)


def verify_reference_batch(batch: PreparedReferenceBatch) -> None:
    """Recheck all file bytes and catalog identities after each slow model call."""
    if type(batch) is not PreparedReferenceBatch or not batch.references:
        raise ReferenceBatchError('참고작 선택 상태를 확인할 수 없습니다.')
    try:
        with ReferenceCatalog(batch.catalog_path) as catalog:
            for work in batch.references:
                _selected_path(str(work.path))
                raw = _open_bounded(work.path, _LIMITS[work.path.suffix.lower()])
                record = catalog.get(work.reference_id)
                if (sha256(raw).hexdigest() != work.source_sha256
                        or record.sha256 != work.source_sha256
                        or record.byte_count != len(raw)
                        or record.status != 'analyzed'):
                    raise ReferenceBatchError(
                        '참고작 또는 분석 기록이 변경되어 원고 저장을 중단했습니다.')
    except ReferenceBatchError:
        raise
    except (OSError, ValueError):
        raise ReferenceBatchError(
            '선택 참고작 전체를 다시 확인하지 못해 원고 저장을 중단했습니다.') from None


def review_batch_draft(
    batch: PreparedReferenceBatch, project_id: str, episode: int,
    manuscript: str, scene_texts: tuple[str, ...],
) -> ReferenceBatchReview:
    """Review all selected works in <=20-work groups; never auto-approve.

    Source scene/beat annotations are not invented. Their absence is recorded
    as unexamined, so a lexical-only check cannot be mistaken for full clearance.
    """
    if (type(batch) is not PreparedReferenceBatch or not batch.references
            or type(scene_texts) is not tuple or not scene_texts
            or '\n\n'.join(scene_texts) != manuscript):
        raise ReferenceBatchError('검사할 장면과 원고 본문이 일치하지 않습니다.')
    verify_reference_batch(batch)
    spans = []
    cursor = 0
    for scene in scene_texts:
        spans.append(TextSpan(cursor, cursor + len(scene)))
        cursor += len(scene) + 2
    reports = []
    try:
        with ReferenceCatalog(batch.catalog_path) as catalog:
            for start in range(0, len(batch.references), 20):
                group = batch.references[start:start + 20]
                reports.append(check_reference_similarity(
                    project_id, episode, manuscript,
                    references=tuple(work.material for work in group),
                    draft_scenes=tuple(spans), draft_beats=(),
                    required_reference_ids=tuple(work.reference_id for work in group),
                    catalog=catalog))
    except (OSError, ValueError):
        raise ReferenceBatchError(
            '선택 참고작 전체 유사성 검사가 실패하여 원고 저장을 중단했습니다.') from None
    if sum(len(report.reference_ids) for report in reports) != len(batch.references):
        raise ReferenceBatchError('참고작 검사 누락으로 원고 저장을 중단했습니다.')
    blocked = any(report.status == 'blocked' for report in reports)
    matches = sum(report.sentence_matches + report.scene_matches
                  + report.structure_matches for report in reports)
    unexamined = set().union(*(report.unexamined for report in reports))
    if len(reports) > 1:
        unexamined.add('cross_group_semantic_scope_unexamined')
    complete = (all(report.passed_checked_scope and report.registration_checked
                    for report in reports) and not unexamined and not blocked)
    detail = (
        f'selected={len(batch.references)};'
        f'compared={sum(len(report.reference_ids) for report in reports)};'
        f'groups={len(reports)};blocked={int(blocked)};'
        f'flagged={matches};unexamined={len(unexamined)};'
        'source_prose_persisted=false;human_review_required=true;publication_approved=false'
    )
    return ReferenceBatchReview('PASS' if complete else 'WARN', detail, blocked, complete)
