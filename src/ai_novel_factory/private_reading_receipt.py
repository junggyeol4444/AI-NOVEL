"""비공개 EPUB3 여러 권의 현재 열람 위치를 사용자가 직접 새 JSON으로 보관·재개.

원고·EPUB 본문·로컬 파일 경로를 JSON에 저장하지 않는다. 사용자 선택
원본 권 순서와 SHA가 모두 일치해야만 새로 선택한 파일에서 이어 읽는다.
사용자 직접 클릭·별도 1회 동의 외에는 디스크에 기록하지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os

from .private_volume_reader import (
    PrivateVolumeCatalog, _digest_file, _selected_file,
)
from .private_volume_navigation import (
    PrivateReadingPosition, PrivateVolumeNavigationError,
    open_private_reading_position, require_current_reading_position,
    _catalog_fingerprint,
)


class PrivateReadingReceiptError(ValueError):
    """사용자 로컬 경로·원문을 출력하지 않는 열람 위치 오류."""


def _unchanged_volumes(catalog: PrivateVolumeCatalog) -> None:
    _catalog_fingerprint(catalog)
    for entry in catalog.volumes:
        try:
            if _digest_file(_selected_file(entry.file_path)) != entry.file_sha256:
                raise PrivateReadingReceiptError(
                    '선택한 EPUB3 권 원본이 변경되어 위치 기록을 사용할 수 없습니다.')
        except (ValueError, OSError):
            raise PrivateReadingReceiptError(
                '선택한 EPUB3 원본을 다시 확인해야 합니다.') from None


def _file(value: str | Path, *, must_exist: bool) -> Path:
    if not isinstance(value, (str, Path)):
        raise PrivateReadingReceiptError('로컬 JSON 파일을 직접 선택하세요.')
    path = Path(value)
    if (not path.is_absolute() or path.suffix.lower() != '.json'
            or path.is_symlink() or not path.parent.is_dir()
            or path.parent.is_symlink()):
        raise PrivateReadingReceiptError('기존 로컬 폴더의 JSON 파일만 허용합니다.')
    if must_exist:
        if not path.is_file():
            raise PrivateReadingReceiptError('열람 위치 JSON 파일이 없습니다.')
    elif path.exists():
        raise PrivateReadingReceiptError('기존 JSON 파일은 덮어쓸 수 없습니다.')
    return path


def save_private_reading_receipt(
    catalog: PrivateVolumeCatalog, position: PrivateReadingPosition,
    destination: str | Path, *, explicit_author_save: bool,
) -> Path:
    """기존 파일에 손대지 않고 사용자가 선택한 새 JSON 파일 하나만 생성."""
    if explicit_author_save is not True:
        raise PrivateReadingReceiptError('이번 열람 위치 보관에 별도 동의가 필요합니다.')
    _unchanged_volumes(catalog)
    try:
        require_current_reading_position(catalog, position)
    except (PrivateVolumeNavigationError, ValueError, OSError):
        raise PrivateReadingReceiptError('현재 EPUB3 열람 위치를 다시 확인하세요.') from None
    path = _file(destination, must_exist=False)
    data = {
        'kind': 'anf_private_reading_receipt',
        'version': 1,
        'saved_at_utc': datetime.now(timezone.utc).isoformat(),
        'volume_index': position.volume_index,
        'chapter_index': position.chapter_index,
        'display_episode': position.display_episode,
        'total_chapters': position.total_chapters,
        'catalog_sha256': position.catalog_sha256,
        'file_sha256': position.file_sha256,
        'chapter_sha256': position.chapter_sha256,
        'status': 'PRIVATE_READING_ONLY_NOT_QC',
    }
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    if len(blob) > 4096:
        raise PrivateReadingReceiptError('열람 위치 기록의 크기가 올바르지 않습니다.')
    _unchanged_volumes(catalog)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise PrivateReadingReceiptError('새 JSON 파일을 생성할 수 없습니다.') from None
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        # A failed write is never reported as a valid saved position.
        # Do not delete a file that another process might have replaced.
        raise PrivateReadingReceiptError('열람 위치 기록을 완료하지 못했습니다.') from None
    return path


def load_private_reading_receipt(
    catalog: PrivateVolumeCatalog, source: str | Path,
) -> tuple[PrivateReadingPosition, str, str]:
    """새로 직접 선택한 동일 EPUB 권에서만 기존 위치 기록을 읽는다."""
    _unchanged_volumes(catalog)
    path = _file(source, must_exist=True)
    try:
        if not 1 <= path.stat().st_size <= 4096:
            raise PrivateReadingReceiptError('열람 위치 JSON 크기가 올바르지 않습니다.')
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        raise PrivateReadingReceiptError('열람 위치 JSON을 읽을 수 없습니다.') from None
    if (type(data) is not dict
            or data.get('kind') != 'anf_private_reading_receipt'
            or type(data.get('version')) is not int
            or data['version'] != 1
            or data.get('status') != 'PRIVATE_READING_ONLY_NOT_QC'):
        raise PrivateReadingReceiptError('이 프로그램의 비공개 열람 위치 기록이 아닙니다.')
    fields = ('volume_index', 'chapter_index', 'display_episode', 'total_chapters')
    if any(type(data.get(key)) is not int for key in fields):
        raise PrivateReadingReceiptError('열람 위치 회차 정보가 올바르지 않습니다.')
    digests = ('catalog_sha256', 'file_sha256', 'chapter_sha256')
    if any(type(data.get(key)) is not str or len(data[key]) != 64
           or any(c not in '0123456789abcdef' for c in data[key])
           for key in digests):
        raise PrivateReadingReceiptError('열람 위치 지문이 올바르지 않습니다.')
    position = PrivateReadingPosition(
        data['volume_index'], data['chapter_index'], data['display_episode'],
        data['total_chapters'], data['catalog_sha256'],
        data['file_sha256'], data['chapter_sha256'])
    if position.catalog_sha256 != _catalog_fingerprint(catalog):
        raise PrivateReadingReceiptError(
            '기록된 EPUB3 권의 내용이나 순서가 현재 선택과 다릅니다.')
    try:
        require_current_reading_position(catalog, position)
        current, title, prose = open_private_reading_position(
            catalog, volume_index=position.volume_index,
            chapter_index=position.chapter_index)
    except (PrivateVolumeNavigationError, OSError, ValueError):
        raise PrivateReadingReceiptError('열람 위치의 EPUB3 원문이 변경되었습니다.') from None
    _unchanged_volumes(catalog)
    if current != position:
        raise PrivateReadingReceiptError('현재 EPUB3 열람 위치가 기록과 다릅니다.')
    return current, title, prose
