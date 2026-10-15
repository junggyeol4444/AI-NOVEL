"""Bounded actual-local-model multi-episode writing with explicit review gates.

This is a genuine connected drafting path, NOT an approved 250-episode novel.
Existing episodes are never overwritten. Every completed episode is stored with
per-episode QC evidence; failed/cancelled work can resume from the next uncreated
episode. Only a caller-approved LocalExecutableProvider may generate prose.
No service, account, background schedule, publication or reference source is read.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .database.episodes import EpisodeStore
from .database.characters import CharacterStore
from .local_models import LocalExecutableProvider, SceneDraftRequest, draft_scene
from .planning import PlanningInput, draft_premise
from .story_arcs import plan_story_arcs, validate_arc_coverage
from .episode_planner import plan_episodes, validate_episode_plans
from .scene_planner import plan_scenes, validate_scene_plans
from .repetition_checker import check_repetition


class AutoNovelRunError(ValueError):
    """Sanitized failures: never include private manuscript, model stderr or paths."""


@dataclass(frozen=True)
class AutoNovelRunReport:
    requested_episodes: int
    created_episodes: tuple[int, ...]
    skipped_existing: tuple[int, ...]
    review_required_episodes: tuple[int, ...]
    stopped: bool
    local_model_invocations: int
    publisher_called: bool = False
    quality_certified: bool = False


def run_auto_novel(
    database_path: str | Path, project_id: str, provider: LocalExecutableProvider, *,
    through_episode: int, target_chars: int, scenes_per_episode: int = 2,
    progress: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AutoNovelRunReport:
    """Generate *unapproved drafts* on a dedicated existing SQLite project.

    Uses actual local model calls for both episode plots and each scene, with
    a bounded one-shot scene retry when the length/repetition gate flags output.
    The deterministic stage-51/52/53/54 planner supplies arc coverage and
    slots. No generated text is marked canon/final/approved or published.
    """
    if type(provider) is not LocalExecutableProvider:
        raise AutoNovelRunError('명시적으로 승인한 실제 로컬 AI 실행 파일이 필요합니다.')
    if (type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(target_chars) is not int or not 50 <= target_chars <= 50000
            or type(scenes_per_episode) is not int or not 1 <= scenes_per_episode <= 20):
        raise AutoNovelRunError('회차·글자 수·장면 수가 허용 범위 밖입니다.')
    if progress is not None and not callable(progress):
        raise AutoNovelRunError('진행 알림 형식이 올바르지 않습니다.')
    if should_stop is not None and not callable(should_stop):
        raise AutoNovelRunError('중단 신호 형식이 올바르지 않습니다.')

    created, skipped, review = [], [], []
    calls, stopped = 0, False
    with EpisodeStore(database_path) as db:
        project = db.get_project(project_id)
        rules = {r.key: r.value for r in db.list_rules(project_id)}
        genre, subject, mood = (rules.get(k, '').strip() for k in
                                ('genre', 'subject', 'mood'))
        if not genre or not subject or not mood:
            raise AutoNovelRunError('작품에서 장르·소재·분위기를 먼저 저장하세요.')
        total = int(rules.get('target_episodes', '0') or '0')
        if not 1 <= total <= 1000 or through_episode > total:
            raise AutoNovelRunError('목표 회차를 먼저 지정하고 그 범위에서 실행하세요.')
        spec = PlanningInput(genre, subject, total, mood)
        premise = draft_premise(spec)
        arcs = plan_story_arcs(premise)
        episodes = plan_episodes(arcs, maximum=1000)
        if not validate_arc_coverage(arcs) or not validate_episode_plans(arcs, episodes):
            raise AutoNovelRunError('전체 Arc와 회차 계획 연속성이 깨졌습니다.')
        plans = {e.episode_number: e for e in episodes}
        by_arc = {arc.number: arc for arc in arcs.arcs}
        existing = {e.episode: e for e in db.list_episodes(project_id)}
        first = max(1, min((n for n in range(1, through_episode + 1)
                            if n not in existing), default=through_episode + 1))
        # User-written project canon has higher priority than AI suggestions.
        canon_rules = ['%s: %s' % (k, v) for k, v in rules.items()
                       if k not in {'author'} and v.strip()]
        canon = '\n'.join(canon_rules)[:14000]
        if not canon.strip():
            raise AutoNovelRunError('Novel Bible 입력이 비어 있습니다.')
        with CharacterStore(database_path) as chars:
            character_names = tuple(c.name for c in chars.list_characters(project_id)[:8])
        if not character_names:
            character_names = ('주인공',)

        def emit(number: int, stage: str) -> None:
            if progress is not None:
                progress(number, stage)

        def model(episode_num: int, scene_num: int, context: str,
                  goal: str, conflict: str, place: str) -> str:
            nonlocal calls
            if should_stop is not None and should_stop():
                raise InterruptedError()
            request = SceneDraftRequest(
                project_id, episode_num, scene_num, context[:22000],
                goal[:2000], conflict[:2000], place[:1000], character_names)
            draft = draft_scene(request, provider).draft
            calls += 1
            if not draft.strip():
                raise AutoNovelRunError('로컬 AI 모델이 빈 초고를 반환했습니다.')
            return draft

        for n in range(1, through_episode + 1):
            if n in existing:
                skipped.append(n)
                continue
            if should_stop is not None and should_stop():
                stopped = True
                break
            plan = plans[n]
            arc = by_arc[plan.arc_number]
            slots = plan_scenes(plan, scenes_per_episode)
            if not validate_scene_plans(plan, slots):
                raise AutoNovelRunError('장면 계획 연속성이 깨졌습니다.')
            # Only previously saved *draft summaries*, explicitly marked as
            # unapproved, are used as context; they never overwrite canon.
            history = '\n'.join(
                ('%d화 임시 초고 요약(확정 아님): %s' % (p, existing[p].summary[:900]))
                for p in range(max(1, n - 3), n)
                if p in existing and existing[p].summary.strip())
            context = (canon + '\n' + history)[:20000]
            emit(n, '회차 플롯 로컬 AI 생성')
            try:
                outline = model(
                    n, 1, context,
                    f'{project.title}: {subject}. {n}/{total}화의 구체적인 독창적 사건과 갈등을 설계. '
                    f'현재 ARC {arc.number} ({arc.start_episode}~{arc.end_episode}화). '
                    'Novel Bible을 지키고 전 회차의 결과를 이어 새로운 회차 플롯을 작성.',
                    f'{mood} 분위기의 갈등과 연속성 유지',
                    f'작품 세계관 ({genre})')
                drafts = []
                per_scene = max(50, target_chars // scenes_per_episode)
                for slot in slots:
                    emit(n, f'장면 {slot.scene_number}/{scenes_per_episode} 로컬 AI 집필')
                    scene_goal = (
                        f'{n}화 {slot.scene_number}/{scenes_per_episode}장면. '
                        f'회차 플롯: {outline[:1500]}. '
                        f'목표 분량 {per_scene}자 내외의 독창적 소설 본문을 작성. '
                        '기존 참고작의 문장·고유명사 복제 금지.')
                    scene_context = (context + '\n회차 플롯(검토 전): ' + outline
                                     + '\n앞 장면(검토 전): ' +
                                     (drafts[-1][-1000:] if drafts else ''))[:22000]
                    scene = model(n, slot.scene_number, scene_context,
                                  scene_goal, '새로운 갈등과 해결의 인과관계', f'{genre} 작품의 장면')
                    # A bounded rewrite for insufficient/obvious repetition.
                    if (len(scene.strip()) < min(per_scene, 120)
                            or (len(scene) > 100 and
                                check_repetition(project_id, n, scene).findings)):
                        emit(n, f'장면 {slot.scene_number} 재작성')
                        revised = model(
                            n, slot.scene_number, (scene_context + '\n수정 전 초고: ' +
                                                   scene[:2500])[:22000],
                            '위 장면을 설정에 맞추어 더 길고 구체적인 새로운 소설 문장으로 다시 써줘.',
                            '반복 표현을 줄이고 사건·동기·행동을 구체화', f'{genre} 작품의 장면')
                        scene = revised if len(revised.strip()) >= len(scene.strip()) else scene
                    drafts.append(scene)
            except InterruptedError:
                stopped = True
                break
            full_draft = '\n\n'.join(drafts)
            repetition = check_repetition(project_id, n, full_draft)
            enough = len(full_draft.strip()) >= target_chars
            # No source novel's raw passages are stored. The reference-similarity
            # gate cannot claim PASS without full, reloaded source coverage.
            # Continuity/logic/reader checks likewise need fresh evidence.
            requires_review = (not enough or bool(repetition.findings)
                               or bool(repetition.unexamined) or True)
            # Never clobber an episode created by another session while model ran.
            with EpisodeStore(database_path) as safe:
                if any(e.episode == n for e in safe.list_episodes(project_id)):
                    raise AutoNovelRunError('다른 창에서 같은 회차가 생성되었습니다. 덮어쓰지 않습니다.')
                saved = safe.create_episode(project_id, n, plot=outline)
                for index, slot in enumerate(slots, 1):
                    safe.add_scene(project_id, n, slot.scene_number,
                                   f'{outline[:600]}\n장면 목표: {n}화 {index}장면',
                                   expected_revision=safe.get_episode(project_id, n).revision)
                summary = ('미확정 AI 플롯 요약: ' + outline[:1600])
                safe.update_episode(project_id, n,
                                    expected_revision=safe.get_episode(project_id, n).revision,
                                    draft=full_draft, summary=summary)
                current = safe.get_episode(project_id, n)
                safe.add_check(project_id, n, 'length',
                               'PASS' if enough else 'WARN',
                               f'actual_chars={len(full_draft)};target_chars={target_chars}',
                               expected_revision=current.revision)
                safe.add_check(project_id, n, 'repetition',
                               'PASS' if repetition.passed_checked_scope else 'WARN',
                               f'finding_count={len(repetition.findings)};'
                               f'unexamined_count={len(repetition.unexamined)}',
                               expected_revision=current.revision)
                for category in ('reference_similarity', 'continuity', 'logic',
                                 'timeline', 'foreshadowing', 'reader_simulation'):
                    safe.add_check(project_id, n, category, 'NOT_RUN',
                                   '전체 증거가 없어 자동 승인하지 않음',
                                   expected_revision=current.revision)
            created.append(n)
            existing[n] = saved
            if requires_review:
                review.append(n)
            emit(n, '미승인 초고 저장 및 수동 검수 대기')
    return AutoNovelRunReport(through_episode, tuple(created), tuple(skipped),
                              tuple(review), stopped, calls)
