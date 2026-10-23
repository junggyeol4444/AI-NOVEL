"""Author-owned offline EPUB3 chapter-title manifest, bound to saved finals.

The sidecar is a NEW local JSON file, never the user's manuscript SQLite,
EPUB or an existing metadata file. It does not authorize publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os

from .database.episodes import EpisodeStore
from .private_epub_workflow import plan_private_epub


class EpubTocError(ValueError):
    """Error messages omit private paths, manuscripts and author titles."""


@dataclass(frozen=True)
class EpubTocManifest:
    project_id: str
    through_episode: int
    source_sha256: str
    titles: tuple[str, ...]
    status: str = 'LOCAL_TOC_ONLY_NOT_PUBLISHED'
    publication_approved: bool = False


def _title(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value.strip()) <= 120
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise EpubTocError('회차 제목은 1~120자의 단일 행이어야 합니다.')
    return value


def plan_epub_toc(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    overrides: dict[int, str] | None = None,
) -> EpubTocManifest:
    """No manuscript writes; refuse missing final chapters and invalid titles."""
    plan = plan_private_epub(store, project_id, through_episode=through_episode)
    if plan.missing_final:
        raise EpubTocError('최종본 누락 회차가 있어 목차를 확정할 수 없습니다.')
    if overrides is None:
        overrides = {}
    if type(overrides) is not dict or any(
            type(k) is not int or not 1 <= k <= through_episode
            for k in overrides):
        raise EpubTocError('목차 제목의 회차 범위가 올바르지 않습니다.')
    titles = tuple(_title(overrides.get(n, f'{n}화'))
                   for n in range(1, through_episode + 1))
    if len(set(titles)) != len(titles):
        raise EpubTocError('EPUB 목차의 회차 제목이 중복되었습니다.')
    return EpubTocManifest(project_id, through_episode,
                           plan.source_sha256, titles)


def save_new_epub_toc_manifest(
    manifest: EpubTocManifest, file_path: str | Path, *,
    explicit_author_save: bool,
) -> Path:
    """Exclusive new-file create; no overwrite of any user-owned artifact."""
    if explicit_author_save is not True or type(manifest) is not EpubTocManifest:
        raise EpubTocError('이번 목차 파일 저장을 작가가 직접 승인해야 합니다.')
    path = Path(file_path)
    if (not path.is_absolute() or path.suffix.lower() != '.json'
            or path.is_symlink() or not path.parent.is_dir()
            or path.parent.is_symlink()):
        raise EpubTocError('기존 로컬 폴더에 새로운 JSON 파일을 선택하세요.')
    payload = json.dumps({
        'format': 'ai_novel_factory_epub3_toc_v1',
        'project_id': manifest.project_id,
        'through_episode': manifest.through_episode,
        'source_sha256': manifest.source_sha256,
        'titles': list(manifest.titles),
        'publication_approved': False,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(payload) > 256 * 1024:
        raise EpubTocError('EPUB 목차 파일 크기 제한을 초과했습니다.')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise EpubTocError('기존 파일은 덮어쓸 수 없습니다. 새 파일명을 선택하세요.') from None
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        # A partially written *new* file is never mistaken for a valid title
        # manifest; the reader validates the whole structure before use.
        raise EpubTocError('새 목차 파일 저장을 완료하지 못했습니다.') from None
    return path


def load_current_epub_toc_manifest(
    file_path: str | Path, store: EpisodeStore, project_id: str, *,
    through_episode: int,
) -> EpubTocManifest:
    """Reject stale author titles after any saved final/revision change."""
    path = Path(file_path)
    if (not path.is_absolute() or path.suffix.lower() != '.json'
            or path.is_symlink() or not path.is_file()):
        raise EpubTocError('로컬 EPUB 목차 JSON을 확인할 수 없습니다.')
    try:
        with path.open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise EpubTocError('EPUB 목차 JSON 크기 제한을 초과했습니다.')
        data = json.loads(raw.decode('utf-8'))
    except (OSError, ValueError, UnicodeError):
        raise EpubTocError('EPUB 목차 JSON을 읽을 수 없습니다.') from None
    if (type(data) is not dict
            or data.get('format') != 'ai_novel_factory_epub3_toc_v1'
            or data.get('project_id') != project_id
            or type(data.get('through_episode')) is not int
            or data['through_episode'] != through_episode
            or data.get('publication_approved') is not False
            or type(data.get('titles')) is not list
            or len(data['titles']) != through_episode):
        raise EpubTocError('다른 작품·범위 또는 승인 상태의 목차 파일입니다.')
    overrides = {n: _title(t) for n, t in enumerate(data['titles'], 1)}
    current = plan_epub_toc(store, project_id, through_episode=through_episode,
                            overrides=overrides)
    if data.get('source_sha256') != current.source_sha256:
        raise EpubTocError('저장 최종본이 변경되어 기존 목차 파일이 무효화되었습니다.')
    return current
