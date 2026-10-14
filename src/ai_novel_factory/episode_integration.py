"""Stage 70: one-episode offline integration of planner, writer, preliminary checker and queue.

An integration entry point, NOT full automatic publishing, memory updates or
full QC. Model output is transient, the queue stores metadata only, and a
COMPLETED task means only that its *drafting attempt* finished.
"""
from __future__ import annotations

from dataclasses import dataclass

from .episode_context import EpisodeContext
from .episode_planner import EpisodePlan
from .local_models import LocalExecutableProvider, MockSceneProvider
from .local_task_queue import LocalTaskQueue, TaskQueueError, TaskRecord, _identifier
from .orchestrator import OfflineLiteralChecker, OrchestrationRun, orchestrate_episode
from .scene_planner import ScenePlan, validate_scene_plans
from .task_monitor import TaskCancelled, TaskMonitor


class EpisodeIntegrationError(ValueError):
    """Invalid integration input (never contains draft content)."""


@dataclass(frozen=True)
class OneEpisodeRun:
    task: TaskRecord
    workflow: OrchestrationRun | None
    status: str
    approved: bool = False
    manuscript_saved: bool = False
    published: bool = False
    memory_updated: bool = False
    origin: str = 'OFFLINE_ONE_EPISODE_INTEGRATION_NOT_FULL_QC'


def run_one_episode(
    queue: LocalTaskQueue,
    task_id: str,
    project_id: str,
    episode: EpisodePlan,
    scenes: tuple[ScenePlan, ...],
    context: EpisodeContext,
    provider: MockSceneProvider | LocalExecutableProvider,
    checker: OfflineLiteralChecker,
    *,
    local_execution_approved: bool = False,
) -> OneEpisodeRun | None:
    """Claim an existing local job, run a whole episode, stop at human review.

    The caller must explicitly enqueue a task before invoking this method.
    None means the task cannot be claimed (wrong ID, already processed, paused).
    No automatic retries or persistence of draft text occur. Pause/cancel is
    cooperative at the boundaries before and after the monolithic orchestrator;
    an in-flight model process is *not* forcibly terminated.
    """
    if (type(queue) is not LocalTaskQueue or not _identifier(task_id)
            or not _identifier(project_id) or type(episode) is not EpisodePlan
            or type(context) is not EpisodeContext or context.project_id != project_id
            or context.episode_number != episode.episode_number
            or context.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or episode.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or type(scenes) is not tuple or not 1 <= len(scenes) <= 100
            or any(type(scene) is not ScenePlan or scene.status != 'DRAFT_REQUIRES_USER_APPROVAL'
                   for scene in scenes)
            or not validate_scene_plans(episode, scenes, require_details=True)
            or type(provider) not in (MockSceneProvider, LocalExecutableProvider)
            or type(checker) is not OfflineLiteralChecker
            or type(local_execution_approved) is not bool
            or (type(provider) is LocalExecutableProvider and not local_execution_approved)):
        raise EpisodeIntegrationError('invalid offline single-episode inputs')

    task = queue.claim_identified(task_id, project_id, episode.episode_number)
    if task is None:
        return None
    monitor = TaskMonitor(queue)
    workflow: OrchestrationRun | None = None
    try:
        monitor.checkpoint(task_id, 0, 'PLANNING')
        monitor.checkpoint(task_id, 25, 'WRITING')
        workflow = orchestrate_episode(project_id, episode, scenes, context,
                                       provider, checker,
                                       local_execution_approved=local_execution_approved)
        # A cancellation requested during generation is honored before the
        # completed draft could be exposed as a successful queue result.
        monitor.checkpoint(task_id, 90, 'CHECKING')
        if workflow.status == 'FAILED':
            task = queue.finish(task_id, succeeded=False,
                                error_code=workflow.error_code or 'EPISODE_FAILED')
            return OneEpisodeRun(task, None, 'FAILED')
        if workflow.status not in ('AWAITING_HUMAN_REVIEW', 'REWRITE_REQUIRED_NOT_IMPLEMENTED'):
            task = queue.finish(task_id, succeeded=False, error_code='UNSUPPORTED_WORKFLOW_STATE')
            return OneEpisodeRun(task, None, 'FAILED')
        task = queue.finish(task_id, succeeded=True)
        if task.status != 'COMPLETED':
            return OneEpisodeRun(task, None, 'INTERRUPTED')
        return OneEpisodeRun(task, workflow, workflow.status)
    except TaskCancelled:
        try:
            task = queue.finish(task_id, succeeded=False, error_code='TASK_CANCELLED')
        except TaskQueueError:
            task = queue.get(task_id)
        return OneEpisodeRun(task, None, 'INTERRUPTED')
    except Exception:
        # Never leak provider exception text or a partially generated manuscript.
        try:
            task = queue.finish(task_id, succeeded=False,
                                error_code='EPISODE_INTEGRATION_FAILED')
        except TaskQueueError:
            task = queue.get(task_id)
        return OneEpisodeRun(task, None, 'FAILED')
