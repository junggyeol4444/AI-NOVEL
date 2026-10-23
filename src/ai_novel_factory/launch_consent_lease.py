"""Single-use, memory-only binding for an author-approved local batch launch.

The exact selected reference bytes, project, executable configuration and
chapter targets must remain unchanged between checking the consent box and
starting the worker. This does not approve publication or validate quality.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import json


class LaunchLeaseError(ValueError):
    """Errors are deliberately free of private local paths and source text."""


@dataclass(frozen=True)
class LaunchConsentLease:
    fingerprint: str = field(repr=False)
    reference_count: int
    project_id: str = field(repr=False)
    used: bool = False
    publication_approved: bool = False


def _file_fingerprint(value: str, *, max_bytes: int) -> str:
    if type(value) is not str or not value:
        raise LaunchLeaseError('선택한 파일을 확인할 수 없습니다.')
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LaunchLeaseError('선택한 로컬 파일을 확인할 수 없습니다.')
    digest = sha256()
    total = 0
    try:
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise LaunchLeaseError('선택한 참고작 파일의 크기 제한을 초과했습니다.')
                digest.update(chunk)
    except OSError:
        raise LaunchLeaseError('선택한 로컬 파일을 읽을 수 없습니다.') from None
    if total == 0:
        raise LaunchLeaseError('선택한 파일이 비어 있습니다.')
    return digest.hexdigest()


def _fingerprint(
    *, database_path: str, project_id: str, executable: str, arguments: str,
    through_episode: int, target_chars: int, scenes_per_episode: int,
    reference_paths: tuple[str, ...],
) -> str:
    if (not all(type(s) is str and s for s in
                (database_path, project_id, executable))
            or type(arguments) is not str
            or type(reference_paths) is not tuple
            or len(reference_paths) > 100
            or len(set(reference_paths)) != len(reference_paths)
            or type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(target_chars) is not int or not 50 <= target_chars <= 50000
            or type(scenes_per_episode) is not int or not 1 <= scenes_per_episode <= 20):
        raise LaunchLeaseError('집필 승인 대상 설정이 올바르지 않습니다.')
    if not Path(database_path).is_absolute() or Path(database_path).is_symlink():
        raise LaunchLeaseError('기존 로컬 작품 DB 경로를 확인할 수 없습니다.')
    refs = []
    combined_bytes = 0
    for path in reference_paths:
        suffix = Path(path).suffix.lower()
        if suffix not in {'.txt', '.md', '.epub', '.docx', '.pdf'}:
            raise LaunchLeaseError('참고작 형식을 확인할 수 없습니다.')
        try:
            combined_bytes += Path(path).stat().st_size
        except OSError:
            raise LaunchLeaseError('참고작 파일을 확인할 수 없습니다.') from None
        if combined_bytes > 32 * 1024 * 1024:
            raise LaunchLeaseError('선택한 참고작 전체 크기 제한을 초과했습니다.')
        refs.append((str(Path(path).resolve()), _file_fingerprint(path, max_bytes=32*1024*1024)))
    payload = (str(Path(database_path).resolve()), project_id,
               executable, arguments, through_episode, target_chars,
               scenes_per_episode, tuple(refs))
    return sha256(json.dumps(payload, ensure_ascii=False,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


def capture_launch_lease(**configuration) -> LaunchConsentLease:
    digest = _fingerprint(**configuration)
    return LaunchConsentLease(digest, len(configuration['reference_paths']),
                              configuration['project_id'])


def verify_launch_lease(lease: LaunchConsentLease, **configuration) -> None:
    if type(lease) is not LaunchConsentLease or lease.used:
        raise LaunchLeaseError('새 집필 실행 승인이 필요합니다.')
    if (_fingerprint(**configuration) != lease.fingerprint
            or lease.project_id != configuration['project_id']
            or lease.reference_count != len(configuration['reference_paths'])):
        raise LaunchLeaseError('승인 이후 작품·모델·참고작·분량 설정이 변경되었습니다.')
