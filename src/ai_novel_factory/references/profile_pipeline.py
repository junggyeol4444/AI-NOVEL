"""Stage 30: one-pass local file read -> profile analysis -> SQLite save.

The file itself and transient parsed paragraphs are never serialized to SQLite.
The analysis happens fully before registration, preventing a broken document
from creating metadata or an incomplete profile.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from ai_novel_factory.database import ReferenceCatalog, ReferenceRecord
from ai_novel_factory.database.reference_profiles import ReferenceProfileStore
from .episode_splitter import split_episodes
from .import_pipeline import _LIMITS, _open_bounded, _parse_bytes
from .plaintext_parser import ReferenceParseError
from .reference_profile import ReferenceProfile, build_reference_profile


@dataclass(frozen=True)
class ProfileImportResult:
    reference: ReferenceRecord
    profile: ReferenceProfile


def import_reference_profile(
    path: str | Path, *, catalog: ReferenceCatalog,
    encoding: str | None = None, max_bytes: int | None = None,
) -> ProfileImportResult:
    """Build and persist metrics without accessing any external services."""
    if not isinstance(path, (str, Path)) or not str(path):
        raise ReferenceParseError("참고작 파일 경로가 올바르지 않습니다.")
    if not isinstance(catalog, ReferenceCatalog):
        raise ReferenceParseError("로컬 참고작 목록 저장소가 필요합니다.")
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in _LIMITS:
        if suffix == ".epub":
            raise ReferenceParseError("EPUB 파서가 아직 연결되지 않아 가져올 수 없습니다.")
        raise ReferenceParseError("지원하지 않는 참고작 파일 형식입니다.")
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 1):
        raise ReferenceParseError("파일 크기 제한이 올바르지 않습니다.")
    limit = min(_LIMITS[suffix], max_bytes) if max_bytes is not None else _LIMITS[suffix]
    raw = _open_bounded(source, limit)
    parsed = _parse_bytes(raw, suffix, encoding)
    profile = build_reference_profile(parsed, split=split_episodes(parsed))
    # No catalog operation before every analysis is validated.
    checksum = hashlib.sha256(raw).hexdigest()
    record = catalog.register(
        file_name=source.name, source_format=suffix.lstrip("."),
        byte_count=len(raw), sha256=checksum,
    )
    storage = ReferenceProfileStore(catalog)
    if record.status in {"registered", "failed"}:
        record = catalog.change_status(record.reference_id, "analyzing")
    storage.save(record.reference_id, profile)
    if record.status == "analyzing":
        record = catalog.change_status(record.reference_id, "analyzed")
    return ProfileImportResult(record, profile)
