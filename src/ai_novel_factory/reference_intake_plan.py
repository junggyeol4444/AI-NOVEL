"""Explicit reference selection preflight; no model run or manuscript writes.

This is a read-only identity plan for the five supported user-selected formats.
It is NOT a similarity result, an analysis result, or a publishing permission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import json

from .references.import_pipeline import _LIMITS, _open_bounded


class ReferenceIntakeError(ValueError):
    """Errors intentionally contain neither original text nor filesystem paths."""


@dataclass(frozen=True)
class ReferenceIdentity:
    source_path: Path = field(repr=False)
    suffix: str
    byte_count: int
    source_sha256: str = field(repr=False)


@dataclass(frozen=True)
class ReferenceIntakePlan:
    entries: tuple[ReferenceIdentity, ...] = field(repr=False)
    fingerprint: str = field(repr=False)
    total_bytes: int
    formats: tuple[tuple[str, int], ...]
    status: str = 'PREFLIGHT_ONLY_NOT_ANALYZED'
    manuscript_changed: bool = False
    publication_approved: bool = False


def _read_identity(raw_path: str) -> ReferenceIdentity:
    if type(raw_path) is not str or not raw_path or raw_path.startswith(('\\\\', '//')):
        raise ReferenceIntakeError('참고작은 로컬 파일을 직접 선택해야 합니다.')
    path = Path(raw_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ReferenceIntakeError('선택한 참고작 파일을 확인할 수 없습니다.')
    suffix = path.suffix.lower()
    if suffix not in _LIMITS:
        raise ReferenceIntakeError('TXT/MD/EPUB/DOCX/PDF 파일만 지원합니다.')
    limit = min(int(_LIMITS[suffix]), 32 * 1024 * 1024)
    try:
        raw = _open_bounded(path, limit)
    except (OSError, ValueError):
        raise ReferenceIntakeError('선택한 참고작 파일을 읽을 수 없습니다.') from None
    size = len(raw)
    digest = sha256(raw)
    if size == 0:
        raise ReferenceIntakeError('비어 있는 참고작은 등록할 수 없습니다.')
    return ReferenceIdentity(path, suffix, size, digest.hexdigest())


def plan_reference_intake(paths: tuple[str, ...]) -> ReferenceIntakePlan:
    """Read selected file identities, without parsing, storing or transmitting text."""
    if type(paths) is not tuple or not 1 <= len(paths) <= 100:
        raise ReferenceIntakeError('참고작 1~100개를 직접 선택해야 합니다.')
    if len(set(paths)) != len(paths):
        raise ReferenceIntakeError('동일한 참고작 경로가 중복 선택되었습니다.')
    entries: list[ReferenceIdentity] = []
    total = 0
    seen: set[str] = set()
    formats: dict[str, int] = {}
    for path in paths:
        item = _read_identity(path)
        if item.source_sha256 in seen:
            raise ReferenceIntakeError('동일한 참고작 내용이 중복 선택되었습니다.')
        seen.add(item.source_sha256)
        total += item.byte_count
        if total > 32 * 1024 * 1024:
            raise ReferenceIntakeError('선택 참고작의 총 파일 크기 제한을 초과했습니다.')
        formats[item.suffix[1:]] = formats.get(item.suffix[1:], 0) + 1
        entries.append(item)
    # File names and paths must not be copied to the fingerprint or logs.
    fingerprint = sha256(json.dumps(
        [(x.source_sha256, x.byte_count, x.suffix) for x in entries],
        ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()
    return ReferenceIntakePlan(tuple(entries), fingerprint, total,
                               tuple(sorted(formats.items())))


def require_current_intake(plan: ReferenceIntakePlan, paths: tuple[str, ...]) -> None:
    """Fail closed when a selected file, file order, or its contents changed."""
    if type(plan) is not ReferenceIntakePlan:
        raise ReferenceIntakeError('참고작 선택을 새로 확인해야 합니다.')
    now = plan_reference_intake(paths)
    if now.fingerprint != plan.fingerprint:
        raise ReferenceIntakeError('참고작 선택 또는 내용이 변경되었습니다. 다시 확인하세요.')
