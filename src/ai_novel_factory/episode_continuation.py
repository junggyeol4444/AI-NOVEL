"""Stage 84 / ANF-REQ-049: bounded offline next-episode handoff.

A caller's confirmation assertion is NOT independently authenticated user approval.
The only automatic action is durable preparation of the next *draft* queue job.
No provider is invoked; no manuscript is finalized, published, or uploaded.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import sqlite3

from .database.episodes import MAX_EPISODES, _number
from .database.novel_bible import _id, _now, _revision
from .episode_planner import EpisodePlan
from .local_task_queue import LocalTaskQueue
from .manuscript_versions import ManuscriptVersionStore
from .story_arcs import StoryArcPlan, validate_arc_coverage


class ContinuationError(ValueError):
    """No manuscript text, prompts, paths, or secrets in error messages."""


@dataclass(frozen=True)
class ContinuationResult:
    project_id: str
    source_episode: int
    end_episode: int
    next_episode: int | None
    task_id: str | None
    status: str  # QUEUED_DRAFT or STOPPED_AT_END
    approval_authenticated: bool = False
    publication_approved: bool = False
    draft_generated: bool = False


class EpisodeContinuationStore(ManuscriptVersionStore):
    """Immutable continuation intents with retryable, idempotent queue delivery.

    Novel Bible DB and queue DB are separate transaction domains. The intent
    is committed before enqueue; retrying after a crash reuses the same task ID.
    """

    def __init__(self, database_path=':memory:'):
        super().__init__(database_path)
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_continuation_settings (
                project_id TEXT PRIMARY KEY REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                end_episode INTEGER NOT NULL CHECK(end_episode BETWEEN 1 AND 1000)
            )''')
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_episode_continuations (
                project_id TEXT NOT NULL,
                source_episode INTEGER NOT NULL,
                source_revision INTEGER NOT NULL,
                source_version_id TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                end_episode INTEGER NOT NULL,
                next_episode INTEGER,
                task_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('PENDING_QUEUE','QUEUED_DRAFT','STOPPED_AT_END')),
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, source_episode),
                FOREIGN KEY(project_id, source_episode)
                    REFERENCES bible_episodes(project_id, episode) ON DELETE CASCADE,
                CHECK ((status='STOPPED_AT_END' AND next_episode IS NULL AND task_id IS NULL)
                   OR (status!='STOPPED_AT_END' AND next_episode=source_episode+1 AND task_id IS NOT NULL))
            )''')

    def get_continuation(self, project_id: str, source_episode: int) -> ContinuationResult | None:
        project_id, source_episode = _id(project_id), _number(source_episode, maximum=MAX_EPISODES)
        row = self._db.execute('''SELECT end_episode,next_episode,task_id,status
            FROM bible_episode_continuations WHERE project_id=? AND source_episode=?''',
            (project_id, source_episode)).fetchone()
        if row is None:
            return None
        if row['status'] not in ('PENDING_QUEUE', 'QUEUED_DRAFT', 'STOPPED_AT_END'):
            raise ContinuationError('연속 집필 기록이 손상되었습니다.')
        return ContinuationResult(project_id, source_episode, row['end_episode'],
                                  row['next_episode'], row['task_id'], row['status'])

    def advance_after_confirmation(
        self, project_id: str, source_episode: int, *, end_episode: int,
        expected_revision: int, expected_version_id: str,
        confirmation_asserted: bool, arc_plan: StoryArcPlan,
        next_plan: EpisodePlan | None, queue: LocalTaskQueue,
    ) -> ContinuationResult:
        """Prepare next episode only after caller explicitly asserts confirmation.

        The asserted confirmation is NOT a verified user identity/approval token;
        stage 89 must provide an authenticated approval workflow. The next job
        remains QUEUED until a separately authorized local worker handles it.
        """
        try:
            project_id = _id(project_id)
            source_episode = _number(source_episode, maximum=MAX_EPISODES)
            end_episode = _number(end_episode, maximum=MAX_EPISODES)
            expected_revision = _revision(expected_revision)
            expected_version_id = _id(expected_version_id)
        except ValueError:
            raise ContinuationError('연속 집필 식별자 또는 버전이 올바르지 않습니다.') from None
        if (type(confirmation_asserted) is not bool or not confirmation_asserted
                or type(queue) is not LocalTaskQueue
                or source_episode > end_episode
                or type(arc_plan) is not StoryArcPlan
                or not validate_arc_coverage(arc_plan)
                or arc_plan.episode_count != end_episode):
            raise ContinuationError('확정 확인 또는 종료 회차/기획 설정이 올바르지 않습니다.')
        if source_episode == end_episode:
            if next_plan is not None:
                raise ContinuationError('종료 회차 이후에는 새 회차를 시작할 수 없습니다.')
        else:
            target_arc = next((a for a in arc_plan.arcs
                               if a.start_episode <= source_episode + 1 <= a.end_episode), None)
            if (type(next_plan) is not EpisodePlan or target_arc is None
                    or next_plan.episode_number != source_episode + 1
                    or next_plan.arc_number != target_arc.number
                    or next_plan.status != 'DRAFT_REQUIRES_USER_APPROVAL'):
                raise ContinuationError('다음 회차 기획이 누락되었거나 범위를 벗어났습니다.')

        task_id = None if source_episode == end_episode else sha256(
            f'ANF84|{project_id}|{source_episode}|{expected_version_id}'.encode('ascii')
        ).hexdigest()[:32]
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                current = self.get_episode(project_id, source_episode)
                versions = self._history(project_id, source_episode)
            except ValueError:
                raise ContinuationError('확정 회차 또는 원고 버전을 확인할 수 없습니다.') from None
            if (current.revision != expected_revision or not versions
                    or versions[-1].kind != 'FINAL'
                    or versions[-1].version_id != expected_version_id
                    or versions[-1].episode_revision != expected_revision
                    or not current.final_text.strip()
                    or versions[-1].final_text != current.final_text
                    or versions[-1].draft != current.draft):
                raise ContinuationError('현재 회차의 최신 최종본 후보와 버전이 일치하지 않습니다.')
            setting = self._db.execute('''SELECT end_episode FROM bible_continuation_settings
                WHERE project_id=?''', (project_id,)).fetchone()
            if setting is not None and setting[0] != end_episode:
                raise ContinuationError('기존 종료 회차 설정과 다릅니다.')
            row = self._db.execute('''SELECT * FROM bible_episode_continuations
                WHERE project_id=? AND source_episode=?''',
                (project_id, source_episode)).fetchone()
            if row is not None:
                if (row['source_revision'] != expected_revision
                        or row['source_version_id'] != expected_version_id
                        or row['source_fingerprint'] != versions[-1].fingerprint
                        or row['end_episode'] != end_episode
                        or row['task_id'] != task_id
                        or row['next_episode'] != (source_episode + 1 if task_id else None)):
                    raise ContinuationError('기존 연속 집필 기록과 입력이 충돌합니다.')
            else:
                if setting is None:
                    self._db.execute('''INSERT INTO bible_continuation_settings
                        (project_id,end_episode) VALUES (?,?)''', (project_id, end_episode))
                if task_id is not None:
                    exists = self._db.execute('''SELECT 1 FROM bible_episodes
                        WHERE project_id=? AND episode=?''',
                        (project_id, source_episode + 1)).fetchone()
                    if exists:
                        raise ContinuationError('다음 회차가 이미 존재하여 자동 덮어쓰기를 중단합니다.')
                    count = self._db.execute('''SELECT COUNT(*) FROM bible_episodes
                        WHERE project_id=?''', (project_id,)).fetchone()[0]
                    if count >= MAX_EPISODES:
                        raise ContinuationError('작품별 최대 회차 개수를 초과합니다.')
                    stamp = _now()
                    self._db.execute('''INSERT INTO bible_episodes
                        (project_id,episode,plot,revision,created_at,updated_at)
                        VALUES (?,?,?,1,?,?)''',
                        (project_id, source_episode + 1, '', stamp, stamp))
                    self._bump_project(project_id)
                self._db.execute('''INSERT INTO bible_episode_continuations
                    (project_id,source_episode,source_revision,source_version_id,
                     source_fingerprint,end_episode,next_episode,task_id,status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (project_id, source_episode, expected_revision, expected_version_id,
                     versions[-1].fingerprint, end_episode,
                     source_episode + 1 if task_id else None, task_id,
                     'PENDING_QUEUE' if task_id else 'STOPPED_AT_END', _now()))
        if task_id is None:
            return self.get_continuation(project_id, source_episode)
        # Separate queue transaction: deterministic task_id makes a retry safe
        # after interruption between enqueue and recording QUEUED_DRAFT.
        try:
            task = queue.enqueue(project_id, source_episode + 1, task_id=task_id)
        except Exception:
            raise ContinuationError('로컬 작업 대기열 등록에 실패했습니다. 재시도할 수 있습니다.') from None
        if task.status not in ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED'):
            raise ContinuationError('로컬 작업 대기열 상태가 올바르지 않습니다.')
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute('''UPDATE bible_episode_continuations SET status='QUEUED_DRAFT'
                WHERE project_id=? AND source_episode=? AND status IN ('PENDING_QUEUE','QUEUED_DRAFT')''',
                (project_id, source_episode))
        return self.get_continuation(project_id, source_episode)


@dataclass(frozen=True)
class ContinuationExecution:
    handoff: ContinuationResult
    run: object | None  # OneEpisodeRun; None when at end or already claimed
    status: str
    publication_approved: bool = False


def continue_episode(
    store: EpisodeContinuationStore, project_id: str, source_episode: int,
    *, end_episode: int, expected_revision: int, expected_version_id: str,
    confirmation_asserted: bool, arc_plan: StoryArcPlan,
    next_plan: EpisodePlan | None, queue: LocalTaskQueue,
    next_scenes=None, next_context=None, provider=None, checker=None,
    local_execution_approved: bool = False,
) -> ContinuationExecution:
    """Optionally start the next *draft* using stage-70's guarded local runner.

    All drafting inputs must be supplied by the caller; the method does not
    invent story facts or automatically dispatch a local executable. No output
    is stored or published, and stage-70's preliminary checker is NOT full QC.
    """
    from .episode_context import EpisodeContext
    from .episode_integration import run_one_episode
    from .local_models import LocalExecutableProvider, MockSceneProvider
    from .orchestrator import OfflineLiteralChecker
    from .scene_planner import ScenePlan, validate_scene_plans

    if type(store) is not EpisodeContinuationStore or type(local_execution_approved) is not bool:
        raise ContinuationError('연속 집필 실행 설정이 올바르지 않습니다.')
    if type(source_episode) is not int or type(end_episode) is not int:
        raise ContinuationError('회차 번호가 올바르지 않습니다.')
    if source_episode < end_episode:
        if (type(next_plan) is not EpisodePlan
                or type(next_scenes) is not tuple
                or not 1 <= len(next_scenes) <= 100
                or any(type(s) is not ScenePlan for s in next_scenes)
                or not validate_scene_plans(next_plan, next_scenes, require_details=True)
                or type(next_context) is not EpisodeContext
                or next_context.project_id != project_id
                or next_context.episode_number != source_episode + 1
                or next_context.status != 'DRAFT_REQUIRES_USER_APPROVAL'
                or type(provider) not in (MockSceneProvider, LocalExecutableProvider)
                or type(checker) is not OfflineLiteralChecker
                or (type(provider) is LocalExecutableProvider and not local_execution_approved)):
            raise ContinuationError('다음 회차 집필 입력이 누락되거나 승인되지 않았습니다.')
    handoff = store.advance_after_confirmation(
        project_id, source_episode, end_episode=end_episode,
        expected_revision=expected_revision, expected_version_id=expected_version_id,
        confirmation_asserted=confirmation_asserted, arc_plan=arc_plan,
        next_plan=next_plan, queue=queue)
    if handoff.status == 'STOPPED_AT_END':
        return ContinuationExecution(handoff, None, 'STOPPED_AT_END')
    run = run_one_episode(queue, handoff.task_id, project_id, next_plan,
                          next_scenes, next_context, provider, checker,
                          local_execution_approved=local_execution_approved)
    return ContinuationExecution(handoff, run,
                                 run.status if run is not None else 'ALREADY_DISPATCHED')
