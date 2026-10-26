"""Offline writer-controlled recovery of unfinished plot-only GGUF prose.

Never writes the author's SQLite, calls a model, or changes final/publishing status.
The author explicitly chooses a new local JSON and separately restores it.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import os

from .database.episodes import EpisodeStore, MAX_FIELD_BYTES
from .local_plot_only_draft import (
    PlotOnlyLease, PlotOnlyDraftError, require_current_plot_only_lease,
)


class PlotOnlyRecoveryError(ValueError):
    """No private text or local path in errors."""


def _digest(text: str) -> str:
    return sha256(text.encode('utf-8')).hexdigest()


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _candidate(value: str) -> None:
    if (type(value) is not str or not value.strip() or '\x00' in value or
            any((ord(ch) < 32 and ch not in '\n\r\t') or ord(ch) == 127
                for ch in value) or
            len(value.encode('utf-8')) > MAX_FIELD_BYTES['draft']):
        raise PlotOnlyRecoveryError('미검수 원고 내용이 올바르지 않습니다.')


def _lease(store: EpisodeStore, lease: PlotOnlyLease) -> None:
    if not isinstance(store, EpisodeStore) or type(lease) is not PlotOnlyLease:
        raise PlotOnlyRecoveryError('현재 플롯 회차를 다시 선택하세요.')
    try:
        require_current_plot_only_lease(store, lease)
    except (PlotOnlyDraftError, OSError, ValueError):
        raise PlotOnlyRecoveryError(
            '원본 플롯·원고·최종본 또는 회차 수정 버전이 달라 후보를 사용할 수 없습니다.'
        ) from None


def export_unsaved_plot(
    store: EpisodeStore, lease: PlotOnlyLease, prose: str,
    destination: str | Path, *, explicit_author_export: bool,
) -> Path:
    """Exclusively create a new UTF-8 JSON with the unsaved prose; never overwrite."""
    if explicit_author_export is not True:
        raise PlotOnlyRecoveryError('새 복구 파일 저장을 이번 한 번 승인해야 합니다.')
    _lease(store, lease)
    _candidate(prose)
    path = Path(destination)
    if (not path.is_absolute() or path.suffix.lower() != '.json'
            or not path.parent.is_dir() or path.parent.is_symlink()):
        raise PlotOnlyRecoveryError('새 로컬 JSON 경로를 선택하세요.')
    record = {
        'schema': 'anf-plot-only-candidate-v1',
        'lease': asdict(lease),
        'prose': prose,
        'prose_sha256': _digest(prose),
        'unreviewed': True,
        'sqlite_saved': False,
        'publication_approved': False,
    }
    record['checksum_sha256'] = _digest(_canonical(record).decode('utf-8'))
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(_canonical(record) + b'\n')
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise PlotOnlyRecoveryError('기존 파일은 덮어쓰지 않습니다. 새 이름을 선택하세요.') from None
    except OSError:
        raise PlotOnlyRecoveryError('새 복구 파일을 저장하지 못했습니다.') from None
    return path


def import_unsaved_plot(
    store: EpisodeStore, lease: PlotOnlyLease, source: str | Path, *,
    explicit_author_import: bool,
) -> str:
    """Restore text to caller memory only when saved chapter identity matches."""
    if explicit_author_import is not True:
        raise PlotOnlyRecoveryError('복구 파일 불러오기를 직접 승인해야 합니다.')
    _lease(store, lease)
    path = Path(source)
    if (not path.is_absolute() or path.suffix.lower() != '.json'
            or path.is_symlink() or not path.is_file()):
        raise PlotOnlyRecoveryError('기존 로컬 JSON 복구 파일을 직접 선택하세요.')
    try:
        if path.stat().st_size > MAX_FIELD_BYTES['draft'] + 8192:
            raise PlotOnlyRecoveryError('복구 파일 크기가 허용 범위를 넘습니다.')
        record = json.loads(path.read_text(encoding='utf-8'))
    except PlotOnlyRecoveryError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise PlotOnlyRecoveryError('복구 JSON을 읽을 수 없습니다.') from None
    fields = {'schema', 'lease', 'prose', 'prose_sha256', 'checksum_sha256',
              'unreviewed', 'sqlite_saved', 'publication_approved'}
    if (type(record) is not dict or set(record) != fields
            or record['schema'] != 'anf-plot-only-candidate-v1'
            or record['lease'] != asdict(lease)
            or record['unreviewed'] is not True
            or record['sqlite_saved'] is not False
            or record['publication_approved'] is not False):
        raise PlotOnlyRecoveryError('현재 저장된 작품/플롯과 복구 기록이 일치하지 않습니다.')
    prose = record['prose']
    _candidate(prose)
    checksum = record.pop('checksum_sha256')
    if (record['prose_sha256'] != _digest(prose)
            or checksum != _digest(_canonical(record).decode('utf-8'))):
        raise PlotOnlyRecoveryError('복구 원고의 무결성이 일치하지 않습니다.')
    _lease(store, lease)
    return prose
