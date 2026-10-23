"""작가가 직접 선택한 참고작 5종의 로컬 파일 지문 임대.

TXT/MD/EPUB/DOCX/PDF의 바이트만 직접 클릭 시 읽어 SHA256을 계산한다.
원문, 제목, 실제 경로는 GUI·로그·별도 파일에 기록하지 않는다.
참고작 유사성 검사·저작권 승인·모델 실행은 수행하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

_ALLOWED = frozenset(('.txt', '.md', '.epub', '.docx', '.pdf'))


class ReferenceLeaseError(ValueError):
    """실제 사용자 경로/참고작 본문을 포함하지 않는 오류."""


@dataclass(frozen=True)
class ReferenceSelectionLease:
    count: int
    file_types: tuple[tuple[str, int], ...]
    fingerprint: str = field(repr=False)
    status: str = 'LOCAL_REFERENCE_FINGERPRINT_ONLY'


def _sha_file(path: Path) -> str:
    before = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ReferenceLeaseError('링크가 아닌 기존 로컬 참고작 파일만 선택하세요.')
    digest = sha256()
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    after = path.stat()
    if ((before.st_size, before.st_mtime_ns, before.st_ino) !=
            (after.st_size, after.st_mtime_ns, after.st_ino)):
        raise ReferenceLeaseError('참고작 파일이 조회 도중 변경됐습니다. 다시 선택하세요.')
    return digest.hexdigest()


def preview_reference_selection(selected_paths) -> ReferenceSelectionLease:
    """선택 파일 최대 100개를 읽기 전용으로 지문화; 원문은 반환하지 않는다."""
    if not isinstance(selected_paths, (tuple, list)) or len(selected_paths) > 100:
        raise ReferenceLeaseError('작가가 직접 선택한 참고작 최대 100개를 확인하세요.')
    counts = {extension: 0 for extension in sorted(_ALLOWED)}
    seen = set()
    digest = sha256(b'AI-NOVEL-REFERENCE-LEASE-V1\0')
    try:
        for raw in selected_paths:
            if not isinstance(raw, (str, Path)) or not str(raw).strip():
                raise ReferenceLeaseError('참고작 파일 선택이 올바르지 않습니다.')
            path = Path(raw)
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                raise ReferenceLeaseError('기존 로컬 일반 파일만 참고작으로 선택하세요.')
            suffix = path.suffix.casefold()
            if suffix not in _ALLOWED:
                raise ReferenceLeaseError('TXT·MD·EPUB·DOCX·PDF 참고작만 선택하세요.')
            canonical = str(path.resolve(strict=True))
            if canonical in seen:
                raise ReferenceLeaseError('같은 참고작 파일이 중복 선택됐습니다.')
            seen.add(canonical)
            counts[suffix] += 1
            # 순서·실제 경로·내용 지문을 하나의 임대 SHA에만 반영한다.
            digest.update(canonical.encode('utf-8'))
            digest.update(b'\0')
            digest.update(bytes.fromhex(_sha_file(path)))
            digest.update(b'\0')
    except ReferenceLeaseError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise ReferenceLeaseError('선택한 로컬 참고작을 확인할 수 없습니다.') from None
    return ReferenceSelectionLease(
        len(seen), tuple((suffix, counts[suffix]) for suffix in sorted(_ALLOWED)),
        digest.hexdigest())


def require_current_reference_selection(lease: ReferenceSelectionLease,
                                        selected_paths) -> None:
    """범위 인계 직전에 모든 참고작 바이트를 재확인. 실행 승인 아님."""
    if type(lease) is not ReferenceSelectionLease:
        raise ReferenceLeaseError('참고작 선택을 직접 다시 확인하세요.')
    current = preview_reference_selection(selected_paths)
    if current.fingerprint != lease.fingerprint or current.count != lease.count:
        raise ReferenceLeaseError('참고작 파일 또는 선택 순서가 변경됐습니다. 다시 조회하세요.')
