"""Stage 86 / ANF-REQ-059: isolated, deterministic 30-episode integration trial.

This is a TEST HARNESS, not an unattended serial-novel author. Every draft is
created by the existing offline mock provider. No approval, FINAL version,
Memory Delta application, reference text, network service or publication occurs.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from .episode_context import ContextFact, select_episode_context
from .episode_integration import run_one_episode
from .episode_planner import plan_episodes
from .local_models import MockSceneProvider
from .local_task_queue import LocalTaskQueue
from .manuscript_versions import ManuscriptVersionStore
from .orchestrator import OfflineLiteralChecker
from .scene_planner import ScenePlan
from .story_arcs import StoryArc, StoryArcPlan, validate_arc_coverage


TRIAL_EPISODES = 30
TRIAL_SCENES_PER_EPISODE = 2


class ThirtyEpisodeTrialError(ValueError):
    """Sanitized test-harness validation error."""


def run_30_episode_trial(*, blocked_episode: int | None = None) -> dict:
    """Exercise 30 contiguous *mock draft* episodes through existing local APIs.

    `blocked_episode` injects a preliminary-check rejection for testing the
    report's error accounting and fail-closed draft persistence. This does not
    pretend to run the full stage-71..80 QC, stage-84 confirmation handoff,
    stage-81/82 memory pipeline, or an actual local LLM.

    Return a JSON-serializable report containing only safe metadata/digests.
    All manuscript data and temporary SQLite files are destroyed on return.
    """
    if blocked_episode is not None and (type(blocked_episode) is not int
                                        or not 1 <= blocked_episode <= TRIAL_EPISODES):
        raise ThirtyEpisodeTrialError('invalid simulated rejection episode')
    arc = StoryArcPlan(TRIAL_EPISODES, (
        StoryArc(1, 1, 10, 'ARC 1', '테스트 계획'),
        StoryArc(2, 11, 20, 'ARC 2', '테스트 계획'),
        StoryArc(3, 21, 30, 'ARC 3', '테스트 계획'),
    ))
    if not validate_arc_coverage(arc):
        raise ThirtyEpisodeTrialError('invalid 30-episode arc fixture')
    plans = plan_episodes(arc)
    entries = []
    with TemporaryDirectory(prefix='anf86_mock_') as directory:
        base = Path(directory)
        store = ManuscriptVersionStore(base / 'bible.sqlite')
        queue = LocalTaskQueue(base / 'tasks.sqlite')
        try:
            project_id = store.create_project('30화 오프라인 모의 집필 시험').project_id
            facts = (
                ContextFact(project_id, 'novel_bible', 'canon-1', '이 테스트는 원본 참고작을 사용하지 않는다.'),
                ContextFact(project_id, 'style_bible', 'style-1', '모의 초고이며 문학적 품질을 보증하지 않는다.'),
            )
            provider = MockSceneProvider()
            for number, template in enumerate(plans, 1):
                plan = replace(template, goal='장면 초고의 순서·무결성 검증',
                               required_events=('검증',), characters=('fixture-hero',))
                scenes = (
                    ScenePlan(number, 1, '테스트 장소', ('fixture-hero',),
                              f'{number}화 첫 장면 검증', '시험 충돌', '시험 긴장'),
                    ScenePlan(number, 2, '테스트 장소', ('fixture-hero',),
                              f'{number}화 두 번째 장면 검증', '시험 해결', '시험 완화'),
                )
                context = select_episode_context(project_id, plan, facts)
                store.create_episode(project_id, number)
                task_id = f'anf86-episode-{number:02d}'
                queue.enqueue(project_id, number, task_id=task_id)
                forbidden = (f'{number}화 1장면:',) if number == blocked_episode else ()
                run = run_one_episode(queue, task_id, project_id, plan, scenes,
                                      context, provider, OfflineLiteralChecker(forbidden))
                entry = {'episode': number, 'status': 'FAILED', 'error_code': None,
                         'task_status': None, 'scene_count': 0,
                         'draft_sha256': None, 'saved': False,
                         'approval_authenticated': False, 'published': False}
                if run is None:
                    entry['error_code'] = 'TASK_NOT_CLAIMED'
                else:
                    entry['task_status'] = run.task.status
                    if run.task.status != 'COMPLETED' or run.workflow is None:
                        entry['error_code'] = run.task.error_code or 'WORKFLOW_FAILED'
                    elif (run.status != 'AWAITING_HUMAN_REVIEW'
                          or run.workflow.preliminary_check is None
                          or not run.workflow.preliminary_check.passed):
                        entry['status'] = 'BLOCKED_PRELIMINARY'
                        entry['error_code'] = 'PRELIMINARY_REVIEW_REQUIRED'
                    else:
                        preview = run.workflow.preview
                        if (preview is None or preview.episode_number != number
                                or preview.project_id != project_id
                                or preview.provider != 'offline-mock-v1'
                                or len(preview.scenes) != TRIAL_SCENES_PER_EPISODE
                                or sha256(preview.draft.encode('utf-8')).hexdigest()
                                   != preview.draft_sha256):
                            entry['error_code'] = 'PREVIEW_INTEGRITY_FAILED'
                        else:
                            version = store.save_version(project_id, number, preview.draft,
                                                         kind='DRAFT', expected_revision=1)
                            stored = store.get_episode(project_id, number)
                            if (stored.draft != preview.draft or stored.final_text
                                    or version.kind != 'DRAFT'
                                    or queue.get(task_id).attempts != 1):
                                entry['error_code'] = 'DRAFT_PERSISTENCE_MISMATCH'
                            else:
                                entry.update(status='DRAFT_REQUIRES_USER_APPROVAL',
                                             scene_count=len(preview.scenes),
                                             draft_sha256=preview.draft_sha256, saved=True)
                entries.append(entry)
            # Verify the full contiguous set and that no FINAL was written.
            stored_episodes = store.list_episodes(project_id)
            contiguous = ([e.episode for e in stored_episodes] == list(range(1, 31)))
            final_count = sum(bool(e.final_text) for e in stored_episodes)
            draft_count = sum(bool(e.draft) for e in stored_episodes)
            version_count = sum(len(store.list_versions(project_id, n)) for n in range(1, 31))
            queue_count = sum(queue.get(f'anf86-episode-{n:02d}') is not None
                              for n in range(1, 31))
        finally:
            store.close()
    errors = sum(e['error_code'] is not None for e in entries)
    saved = sum(e['saved'] for e in entries)
    scenes = sum(e['scene_count'] for e in entries)
    return {
        'stage': 86, 'requirement_id': 'ANF-REQ-059',
        'kind': 'DETERMINISTIC_OFFLINE_MOCK_INTEGRATION_NOT_REAL_AI',
        'expected_episodes': TRIAL_EPISODES, 'attempted_episodes': len(entries),
        'episode_numbers_contiguous': contiguous,
        'queued_task_count': queue_count, 'saved_draft_count': draft_count,
        'version_count': version_count, 'successful_drafts': saved,
        'scenes_in_successful_drafts': scenes, 'error_count': errors,
        'preliminary_blocked_count': sum(e['status'] == 'BLOCKED_PRELIMINARY' for e in entries),
        'final_version_count': final_count,
        'publication_approved': False, 'human_approval_authenticated': False,
        'reference_text_used': False, 'memory_delta_applied': False,
        'passed': (len(entries) == TRIAL_EPISODES and contiguous
                   and queue_count == TRIAL_EPISODES and errors == 0
                   and saved == TRIAL_EPISODES and scenes == TRIAL_EPISODES * TRIAL_SCENES_PER_EPISODE
                   and version_count == TRIAL_EPISODES and final_count == 0),
        'episodes': entries,
        'limitations': [
            'MockSceneProvider only; no actual local LLM or literary-quality claim',
            'Only stage-70 literal preliminary checker; full stage-71..80 QC not integrated',
            'No stage-84 finalization/confirmation handoff or stage-85 OS scheduler',
            'No automatic memory extraction/application or independent approval verification',
            'No publication, platform upload, network service or Windows EXE test',
        ],
    }
