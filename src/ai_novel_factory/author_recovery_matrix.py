"""작가 승인 전 장면 임시 기록·중단 배치·SQLite 회차의 합동 읽기 전용 범위.

임시 장면 개수는 무결성 인증이나 재개 권한이 아니다. 원고, 모델,
참고작, 출판 기록을 쓰지 않으며 이전 모델 실행 동의를 재사용하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .auto_resume_plan import preview_resume
from .batch_session_journal import list_project_sessions, preview_recovery
from .database.episodes import EpisodeStore
from .manual_review_gate import review_state
from .scene_checkpoint_store import (
    list_checkpoint_overviews, _identity as _checkpoint_identity,
)


class AuthorRecoveryMatrixError(ValueError):
    """개인 경로와 원고를 포함하지 않는 오류."""


@dataclass(frozen=True)
class RecoveryChapter:
    episode: int
    saved_state: str
    revision: int | None
    checkpoint_sets: int
    unverified_stage_files: int
    can_open_saved_editor: bool
    cached_text_approved: bool = False


@dataclass(frozen=True)
class AuthorRecoveryMatrix:
    project_id: str = field(repr=False)
    database_path: str = field(repr=False)
    through_episode: int = 0
    chapters: tuple[RecoveryChapter, ...] = ()
    journal_count: int = 0
    last_recorded_state: str = 'NO_JOURNAL'
    last_current_state: str = 'NO_JOURNAL'
    fingerprint: str = field(default='', repr=False)
    model_run_approved: bool = False
    publication_approved: bool = False

    @property
    def missing(self) -> int:
        return sum(row.saved_state == 'MISSING' for row in self.chapters)

    @property
    def draft_only(self) -> int:
        return sum(row.saved_state == 'DRAFT_ONLY' for row in self.chapters)

    @property
    def final_count(self) -> int:
        return sum(row.saved_state == 'FINAL_SAVED' for row in self.chapters)


def _checkpoint_stamp(root: Path, database_path: Path, project_id: str,
                      through_episode: int) -> tuple[tuple, ...]:
    """파일 내용은 읽거나 노출하지 않고 변경 감지용 메타데이터만 수집한다.

    이 지문은 임시 JSON 무결성 검증이 아니다. 실제 재개는 기존
    SceneCheckpointStore.load_stage의 별도 엄격 검사를 거쳐야 한다.
    """
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise AuthorRecoveryMatrixError('임시 장면 폴더를 신뢰할 수 없습니다.')
    prefix = _checkpoint_identity(database_path, project_id)[:20] + '_'
    rows = []
    try:
        for folder in root.glob(prefix + '*'):
            if folder.is_symlink() or not folder.is_dir():
                raise AuthorRecoveryMatrixError('임시 장면 경로를 신뢰할 수 없습니다.')
            parts = folder.name.split('_')
            if len(parts) != 3 or not parts[1].isdigit() or len(parts[1]) != 4:
                raise AuthorRecoveryMatrixError('임시 장면 기록 이름이 올바르지 않습니다.')
            if int(parts[1]) > through_episode:
                continue
            stat = folder.stat()
            rows.append((folder.name, '', 0, stat.st_mtime_ns, stat.st_ino))
            for file in folder.iterdir():
                if file.is_symlink() or not file.is_file() or file.suffix != '.json':
                    raise AuthorRecoveryMatrixError('임시 장면 기록을 신뢰할 수 없습니다.')
                meta = file.stat()
                rows.append((folder.name, file.name, meta.st_size,
                             meta.st_mtime_ns, meta.st_ino))
                if len(rows) > 25000:
                    raise AuthorRecoveryMatrixError('임시 장면 기록이 조회 한도를 초과했습니다.')
    except OSError:
        raise AuthorRecoveryMatrixError('임시 장면 기록을 읽지 못했습니다.') from None
    return tuple(sorted(rows))


def preview_author_recovery_matrix(
    store: EpisodeStore, database_path: str | Path, project_id: str, *,
    through_episode: int, checkpoint_root: str | Path,
    journal_root: str | Path,
) -> AuthorRecoveryMatrix:
    """작가가 클릭한 1~1000화 범위의 실제 저장/임시/중단 기록을 조회한다."""
    path = Path(database_path)
    if (not isinstance(store, EpisodeStore) or not isinstance(project_id, str)
            or not project_id or not path.is_absolute() or path.is_symlink()
            or type(through_episode) is not int or not 1 <= through_episode <= 1000):
        raise AuthorRecoveryMatrixError('현재 작품·SQLite·1~1000화 범위를 다시 선택하세요.')
    try:
        plan = preview_resume(store, project_id, through_episode=through_episode)
        saved = {ep.episode: ep for ep in store.list_episodes(project_id)
                 if ep.episode <= through_episode}
        overviews = {row.episode: row for row in list_checkpoint_overviews(
            checkpoint_root, database_path=path, project_id=project_id)
            if row.episode <= through_episode}
        receipts = list_project_sessions(journal_root, database_path=path,
                                         project_id=project_id)
        latest = (preview_recovery(store, path, project_id, receipts[0])
                  if receipts else None)
        rows = []
        stamps = []
        for number in range(1, through_episode + 1):
            episode = saved.get(number)
            overview = overviews.get(number)
            state = ('MISSING' if episode is None else
                     'FINAL_SAVED' if episode.final_text.strip() else
                     'DRAFT_ONLY' if episode.draft.strip() else 'EMPTY_SAVED')
            rows.append(RecoveryChapter(
                number, state, episode.revision if episode else None,
                overview.checkpoint_sets if overview else 0,
                overview.unverified_stage_files if overview else 0,
                episode is not None))
            if episode is None:
                stamps.append((number, state, None, None, None))
            else:
                # 검수·QC가 달라지면 과거 인계 범위를 즉시 무효화한다.
                review = review_state(store, project_id, number)
                stamps.append((
                    number, state, episode.revision,
                    sha256(repr((episode.plot, episode.draft,
                                 episode.final_text, episode.summary)).encode(
                                     'utf-8')).hexdigest(),
                    (review.status, review.snapshot_sha256,
                     tuple(review.incomplete_checks))))
        # 기존 작업 기록의 무결성 체인은 journal 모듈이 별도로 확인한다.
        journals = tuple((r.session_id, r.last_digest, r.state, r.events,
                          r.through_episode) for r in receipts)
        files = _checkpoint_stamp(Path(checkpoint_root), path, project_id,
                                  through_episode)
        fingerprint = sha256(repr((str(path.resolve()), project_id,
                                   through_episode, tuple(stamps), journals,
                                   files, plan.existing_episodes)).encode(
                                       'utf-8')).hexdigest()
        return AuthorRecoveryMatrix(
            project_id=project_id, database_path=str(path.resolve()),
            through_episode=through_episode, chapters=tuple(rows),
            journal_count=len(receipts),
            last_recorded_state=latest.recorded_state if latest else 'NO_JOURNAL',
            last_current_state=latest.current_state if latest else 'NO_JOURNAL',
            fingerprint=fingerprint)
    except AuthorRecoveryMatrixError:
        raise
    except (ValueError, OSError, TypeError, LookupError):
        raise AuthorRecoveryMatrixError('저장 원고·임시 장면·중단 기록을 안전하게 조회하지 못했습니다.') from None


def require_current_author_recovery_matrix(
    snapshot: AuthorRecoveryMatrix, store: EpisodeStore,
    database_path: str | Path, project_id: str, *,
    checkpoint_root: str | Path, journal_root: str | Path,
) -> None:
    """이동·범위 인계 직전 다시 조회. 어떤 모델 실행도 승인하지 않는다."""
    if (type(snapshot) is not AuthorRecoveryMatrix
            or snapshot.project_id != project_id
            or snapshot.database_path != str(Path(database_path).resolve())):
        raise AuthorRecoveryMatrixError('작품이 변경됐습니다. 다시 조회하세요.')
    current = preview_author_recovery_matrix(
        store, database_path, project_id,
        through_episode=snapshot.through_episode,
        checkpoint_root=checkpoint_root, journal_root=journal_root)
    if current.fingerprint != snapshot.fingerprint:
        raise AuthorRecoveryMatrixError('원고·장면 임시 기록·중단 기록이 변경됐습니다. 다시 조회하세요.')
