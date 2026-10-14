"""Reproducible offline single-episode smoke test, no source text in stdout.

Run from the ZIP root: PYTHONPATH=src python scripts/stage70_one_episode_smoke.py
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.episode_integration import run_one_episode
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.orchestrator import OfflineLiteralChecker
from ai_novel_factory.scene_planner import ScenePlan


def main() -> None:
    project = 'stage70-demo'
    episode = EpisodePlan(1, 1, '첫 단서를 발견한다', ('단서',), ('hero',), '호기심', (), '새로운 의문')
    scenes = (
        ScenePlan(1, 1, '작업실', ('hero',), '지도 조사', '기록 부족', '긴장'),
        ScenePlan(1, 2, '복도', ('hero',), '새 단서 확인', '낯선 소리', '놀람'),
    )
    facts = (ContextFact(project, 'novel_bible', 'canon-a', '원작과 다른 독자적 배경을 따른다'),)
    context = select_episode_context(project, episode, facts)
    with tempfile.TemporaryDirectory() as temp:
        queue = LocalTaskQueue(Path(temp) / 'local-queue.sqlite3')
        queue.enqueue(project, 1, task_id='stage70-run')
        result = run_one_episode(queue, 'stage70-run', project, episode, scenes,
                                 context, MockSceneProvider(), OfflineLiteralChecker())
        if result is None or result.workflow is None or result.status != 'AWAITING_HUMAN_REVIEW':
            raise SystemExit('offline integration smoke failed')
        print(json.dumps({
            'stage': 70,
            'provider': result.workflow.preview.provider,
            'task_status': result.task.status,
            'workflow_status': result.status,
            'scene_count': len(result.workflow.preview.scenes),
            'preliminary_checker_scope': result.workflow.preliminary_check.scope,
            'approved': result.approved,
            'manuscript_saved': result.manuscript_saved,
            'published': result.published,
            'memory_updated': result.memory_updated,
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
