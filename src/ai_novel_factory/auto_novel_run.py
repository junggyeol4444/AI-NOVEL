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
from .database.style_bible import StyleBibleStore
from .style_checker import StyleCheckerError, check_style
from .continuity_memory_window import (
    extend_scene_context, retrieve_relevant_saved_events, build_real_scene_chain,
)
from .scene_resume_binding import SceneResumeScope, require_explicit_scene_resume
from .author_scene_checkpoint_integrity import SceneStageChoice
from .scene_checkpoint_store import SceneCheckpointError
from .author_context_envelope import (
    AuthorContextSources, compose_author_context, require_unchanged_author_sources,
)
from .database.characters import CharacterStore, BibleCharacter
from .author_canon_context import read_saved_author_context
from .reference_batch_context import (
    prepare_reference_batch, verify_reference_batch, review_batch_draft,
)
from .local_models import LocalExecutableProvider, SceneDraftRequest, draft_scene
from .planning import PlanningInput, draft_premise
from .story_arcs import plan_story_arcs, validate_arc_coverage
from .episode_planner import plan_episodes, validate_episode_plans
from .scene_planner import plan_scenes, validate_scene_plans
from .repetition_checker import check_repetition
from .korean_draft_quality import screen_korean_draft, has_foreign_script_corruption
from .episode_crosscheck import screen_cross_episode_reuse
from .author_ai_novel_guidance import (
    AuthorAiNovelGuidance, AuthorAiNovelGuidanceError,
    require_current_author_ai_novel_guidance,
)


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
    style_scope_checked_episodes: int = 0
    continuation_model_calls: int = 0
    publisher_called: bool = False
    quality_certified: bool = False


def _continuity_context(canon: str, existing: dict[int, object],
                        next_episode: int) -> str:
    """Preserve real stored first/last chapter events without promoting drafts.

    This read-only history is sent to the already-approved local model.
    Actual human-reviewed final text wins over unreviewed drafts; an AI
    summary is a labeled fallback only if no saved prose exists. The first
    chapter and recent 25-chapter checkpoints remain visible at chapter 250.
    """
    if next_episode <= 1:
        return canon[:20000]
    checkpoints = []
    recent = []
    for index in sorted(existing):
        if index >= next_episode:
            continue
        episode = existing[index]
        if (index == 1 or index % 25 == 0) and index < next_episode - 3:
            final = getattr(episode, 'final_text', '') or ''
            draft = getattr(episode, 'draft', '') or ''
            summary = getattr(episode, 'summary', '') or ''
            if final.strip() or draft.strip():
                passage = final if final.strip() else draft
                state = '검수본' if final.strip() else '미검수 초고'
                checkpoints.append(f'{index}화 {state} 저장 본문 마지막 사건: '
                                   + passage[-140:])
            elif summary.strip():
                checkpoints.append(f'{index}화 미확정 AI 요약(저장 본문 없음): '
                                   + summary[:140])
    for index in range(max(1, next_episode - 3), next_episode):
        episode = existing.get(index)
        if episode is None:
            continue
        final = getattr(episode, 'final_text', '') or ''
        draft = getattr(episode, 'draft', '') or ''
        summary = getattr(episode, 'summary', '') or ''
        if final.strip() or draft.strip():
            passage = final if final.strip() else draft
            state = '검수본' if final.strip() else '미검수 초고'
            recent.append(f'{index}화 {state} 실제 저장 본문 마지막 사건: '
                          + passage[-500:])
        elif summary.strip():
            recent.append(f'{index}화 미확정 AI 요약(저장 본문 없음): '
                          + summary[:320])
    if len(checkpoints) > 5:
        omitted = len(checkpoints) - 5
        checkpoints = [checkpoints[0],
                       f'중간 장기 사건 체크포인트 {omitted}개 생략(미검증)',
                       *checkpoints[-4:]]
    reminders = '\n'.join(checkpoints)[-1200:]
    immediate = '\n'.join(recent)[-2600:]
    return (
        '최근 회차의 저장 집필 기록 (미검수 초고·AI 요약은 미확정, 사용자 Novel Bible 우선):\n'
        + reminders + '\n' + immediate
        + '\n사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\n' + canon
    )[:20000]


def _character_bible_context(characters: tuple[BibleCharacter, ...]) -> str:
    """Carry SAVED author-owned character facts to the same approved local model.

    A name-only character list omitted personality, motivation, voice and
    secrets even when the author had explicitly saved all those fields.
    Keep this within the native 12k prompt window; never mutate the Bible,
    claim continuity approval, or include any external reference passages.
    """
    if not characters:
        return ''
    details = []
    for character in characters[:8]:
        details.append(
            f'인물 {character.name[:100]} | 성격: {character.personality[:200]} | '
            f'목표: {character.goal[:200]} | 말투: {character.speech_style[:180]}'
            + (f' | 비밀 설정: {character.secret[:160]}'
               if character.secret.strip() else '')
        )
    header = '사용자가 직접 저장한 인물 Novel Bible (미검수 AI 제안과 구분):\n'
    full = header + '\n'.join(details)
    if len(full) <= 6500:
        return full
    # The former [:6500] truncated the LAST character's speech and secrets.
    # Budget each saved character fairly; keep every name and field marker.
    selected = characters[:8]
    per_character = (6500 - len(header) - len(selected) + 1) // len(selected)
    balanced = []
    for character in selected:
        head = '인물 ' + character.name[:100]
        fields = [(' | 성격: ', character.personality[:200]),
                  (' | 목표: ', character.goal[:200]),
                  (' | 말투: ', character.speech_style[:180])]
        if character.secret.strip():
            fields.append((' | 비밀 설정: ', character.secret[:160]))
        capacity = max(0, per_character - len(head) -
                       sum(len(label) for label, _ in fields))
        sizes = [0] * len(fields)
        # Equal round-robin allocation prevents late fields from disappearing.
        while capacity > 0:
            changed = False
            for pos, (_, value) in enumerate(fields):
                if sizes[pos] < len(value) and capacity:
                    sizes[pos] += 1
                    capacity -= 1
                    changed = True
            if not changed:
                break
        balanced.append(head + ''.join(label + value[:sizes[i]]
                                       for i, (label, value) in enumerate(fields)))
    return (header + '\n'.join(balanced))[:6500]


def _scene_char_targets(episode_target: int, scene_count: int) -> tuple[int, ...]:
    """Distribute the REAL requested characters without losing the remainder.

    A native scene target below 50 is unsupported; reject the configuration
    instead of silently overshooting the manuscript length by up to 20x.
    The targets are instructions for the same actual GGUF, not model output.
    """
    if (type(episode_target) is not int or type(scene_count) is not int
            or not 1 <= scene_count <= 20
            or not 50 <= episode_target <= 50000
            or episode_target < 50 * scene_count):
        raise AutoNovelRunError('장면마다 최소 50자 이상이 되도록 회차 분량·장면 수를 설정하세요.')
    # The native bridge can process at most 10,000 characters in one scene
    # and now fails closed on an unsupported target. Reject incompatible
    # chapter/scene settings BEFORE making any model calls or SQLite writes,
    # rather than silently saving a 50,000-character chapter as a short draft.
    if episode_target > 10_000 * scene_count:
        raise AutoNovelRunError(
            '장면 하나의 목표는 최대 10,000자입니다. '
            '회차 총 분량은 유지하고 장면 수를 늘려 주세요.')
    base, remainder = divmod(episode_target, scene_count)
    return tuple(base + (index < remainder)
                 for index in range(scene_count))



def _plot_endpoints(plot: str, limit: int) -> str:
    """Keep the start and ending of a long *unapproved* plot for model context.

    This is only a temporary model excerpt. The full generated plot and any
    author-written plot remain unchanged in SQLite and on disk.
    """
    marker = '\n[중간 미확정 플롯 생략]\n'
    if type(plot) is not str or type(limit) is not int or limit <= len(marker) + 2:
        raise AutoNovelRunError('플롯 문맥의 형식 또는 길이가 올바르지 않습니다.')
    if len(plot) <= limit:
        return plot
    remaining = limit - len(marker)
    front = remaining // 2
    back = remaining - front
    return plot[:front] + marker + plot[-back:]


def _native_scene_revision_goal(target: int) -> str:
    """Keep the real allocated scene target FIRST on the native retry path."""
    if type(target) is not int or not 1 <= target <= 10_000:
        raise AutoNovelRunError('장면 재작성 목표 분량이 올바르지 않습니다.')
    return (f'목표 분량 {target}자 내외의 독창적 소설 본문을 작성. '
            '위 장면을 설정에 맞추어 더 길고 구체적인 새로운 소설 문장으로 다시 써줘.')


def _native_scene_generation_goal(episode: int, scene: int, total_scenes: int,
                                  outline: str, target: int) -> str:
    """Put the allocated target before untrusted model-authored plot text.

    The native bridge reads the FIRST 'NNNN자' expression from the goal.
    A prior outline can itself mention "5000자" or "10000자" and override
    a 1667-character allocation unless this prefix is anchored first.
    All bytes from the outline remain author-visible context; no generated
    prose is fabricated, shortened for quality claims, or persisted here.
    """
    if (type(target) is not int or not 50 <= target <= 10_000
            or type(outline) is not str):
        raise AutoNovelRunError('장면 분량 또는 회차 플롯이 올바르지 않습니다.')
    # The real local model needs a DISTINCT narrative job for each scene.
    # Without a stage-specific instruction, every 5000-character chapter scene
    # receives essentially the same plot and can rewrite its opening repeatedly.
    # These are directions, NOT fabricated manuscript passages or canon.
    if total_scenes == 1:
        movement = (
            '한 장면 안에서 직전 회차의 결과→발단→사건 전개→선택의 대가→'
            '다음 회차의 궁금증까지 하나의 완결된 회차로 서술. '
            '회차 플롯의 사건을 원인·행동·결과로 실제 소설 문장화.')
    elif scene == 1:
        movement = (
            '첫 장면 전용: 직전 회차의 실제 결과에서 출발하여 인물의 현재 목표, '
            '새 사건의 원인과 첫 행동을 서술. '
            '중반 반전·최종 해결을 미리 전부 보여주지 말 것.')
    elif scene == total_scenes:
        movement = (
            '마지막 장면 전용: 직전 장면에서 이미 진행된 사건을 되풀이하지 말고 '
            '그 직접적 결과·선택의 대가·감정 변화를 실제 행동으로 전개. '
            '회차 갈등의 이번 화 범위와 다음 화로 이어질 미해결 질문을 명확히.')
    elif scene * 2 <= total_scenes:
        movement = (
            '중반 전개 전용: 직전 장면과 다른 새로운 행동·장애·정보를 도입, '
            '기존 선택의 부작용과 인물 간 충돌을 구체적으로 전개. '
            '회차 발단을 재서술하거나 결말을 먼저 끝내지 말 것.')
    else:
        movement = (
            '후반 전환 전용: 새 사실이나 인물 선택으로 진행 방향을 바꾸고 '
            '다음 장면의 결과로 이어지는 인과를 제시. '
            '이전 장면의 대사를 다시 설명하지 말 것.')
    return (
        f'목표 분량 {target}자 내외의 독창적 소설 본문을 작성. '
        f'{episode}화 {scene}/{total_scenes}장면. '
        + movement + ' '
        f'회차 플롯: {_plot_endpoints(outline, 1500)}. '
        '기존 참고작의 문장·고유명사 복제 금지.'
    )


def _cross_episode_sources(existing: dict[int, object], episode: int
                           ) -> tuple[tuple[str, ...], int, int]:
    """Check the actual saved final or draft of up to 250 earlier episodes.

    Previously a human-reviewed final was ignored whenever a legacy episode
    lacked a draft. The resulting missing-prior count could conceal prose.
    Comparison is exact-sentence evidence only, never literary certification.
    """
    if type(episode) is not int or not 1 <= episode <= 1000:
        raise AutoNovelRunError('비교할 회차 번호가 올바르지 않습니다.')
    first_checked = max(1, episode - 250)
    prior_drafts = []
    missing_prior = 0
    for number in range(first_checked, episode):
        item = existing.get(number)
        final = (getattr(item, 'final_text', '') or '') if item else ''
        draft = (getattr(item, 'draft', '') or '') if item else ''
        if final.strip() or draft.strip():
            prior_drafts.append(final if final.strip() else draft)
        else:
            missing_prior += 1
    older_unexamined = first_checked - 1
    return tuple(prior_drafts), missing_prior, older_unexamined


def _scene_generation_context(context: str, outline: str,
                              preceding_scene: str) -> str:
    """Preserve immediate model-written scene, current plot and author canon.

    The native bridge reads only the first 12,000 characters of this field.
    Previously a 20k context hid the immediately preceding scene after
    truncation. Only rearrange original local text; never create prose.
    """
    if not all(type(value) is str
               for value in (context, outline, preceding_scene)):
        raise AutoNovelRunError('장면 연결 문맥 형식이 올바르지 않습니다.')
    lead = '이번 회차의 미확정 플롯:\n' + _plot_endpoints(outline, 1200) + '\n'
    if preceding_scene.strip():
        lead += ('바로 앞 장면의 실제 초고(미검수):\n'
                 + preceding_scene[-1200:] + '\n')
    bible_label = '사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\n'
    history, separator, bible = context.partition(bible_label)
    if not separator:
        return (lead + context)[:12000]
    recent = history[-2500:]
    prefix = lead + recent + bible_label
    return prefix + bible[:max(0, 12000 - len(prefix))]


def _scene_revision_context(scene_context: str, rejected_scene: str) -> str:
    """Place rejected model text before the 12k native context truncation.

    Preserve the previous real scene, current episode plan and author Bible
    from scene_context; never alter stored manuscript or quality thresholds.
    """
    if type(scene_context) is not str or type(rejected_scene) is not str:
        raise AutoNovelRunError('장면 재작성 문맥 형식이 올바르지 않습니다.')
    return ('재작성할 미검수 초고:\n' + rejected_scene[-1800:] + '\n'
            + scene_context)[:12000]


def _existing_episode_needs_review(episode: object, *,
                                   scenes: tuple[object, ...],
                                   checks: tuple[object, ...]) -> bool:
    """Treat a saved human-reviewed final as prose even if its draft is empty.

    Presence of evidence is not a claim that any quality gate has passed.
    Existing records are never changed or automatically approved.
    """
    draft = getattr(episode, 'draft', '') or ''
    final = getattr(episode, 'final_text', '') or ''
    return not (draft.strip() or final.strip()) or not scenes or not checks


def _auto_author_source_stamp(store, database_path, project_id, before_episode):
    """Read-only check for author edits across a long local-model call.

    Rules and character facts include revisions; saved earlier episode
    revisions include scene/final edits. The snapshot is local, never logged,
    sent to an external API, stored, or promoted to literary approval.
    """
    rule_state = tuple(sorted(
        (item.key, item.value, item.revision)
        for item in store.list_rules(project_id)))
    with CharacterStore(database_path) as book:
        character_state = tuple(
            (item.character_id, item.revision, item.name, item.personality,
             item.goal, item.speech_style, item.secret)
            for item in book.list_characters(project_id))
    previous_state = tuple(sorted(
        (item.episode, item.revision)
        for item in store.list_episodes(project_id)
        if item.episode < before_episode))
    # Project title changes do not necessarily appear in Bible rule revisions.
    # Never include project.revision here: legitimate chapter saves bump it.
    project_title = store.get_project(project_id).title
    # Include all saved author canon, not only characters and basic rules.
    # Use the same full-project stamp for every chapter of this batch.
    saved_stamp = read_saved_author_context(
        database_path, project_id, 1_000_000).source_stamp
    return (project_title, rule_state), character_state, previous_state, saved_stamp


def run_auto_novel(
    database_path: str | Path, project_id: str, provider: LocalExecutableProvider, *,
    through_episode: int, target_chars: int, scenes_per_episode: int = 2,
    progress: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    reference_paths: tuple[str, ...] = (),
    reference_metric_keys: tuple[str, ...] | None = None,
    reference_catalog_path: str | Path | None = None,
    scene_checkpoint_root: str | Path | None = None,
    scene_checkpoint_lease: str | None = None,
    context_sources: AuthorContextSources | None = None,
    explicit_resume_choice: SceneStageChoice | None = None,
    episode_writing_guidance: AuthorAiNovelGuidance | None = None,
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
    scene_targets = _scene_char_targets(target_chars, scenes_per_episode)
    if progress is not None and not callable(progress):
        raise AutoNovelRunError('진행 알림 형식이 올바르지 않습니다.')
    if should_stop is not None and not callable(should_stop):
        raise AutoNovelRunError('중단 신호 형식이 올바르지 않습니다.')
    if (scene_checkpoint_root is None) != (scene_checkpoint_lease is None):
        raise AutoNovelRunError('장면별 임시 저장/재개는 별도 사용 동의가 필요합니다.')
    if scene_checkpoint_lease is not None and (
            type(scene_checkpoint_lease) is not str or len(scene_checkpoint_lease) != 64):
        raise AutoNovelRunError('장면별 임시 기록에 사용할 승인 지문이 올바르지 않습니다.')
    if explicit_resume_choice is not None and (
            type(explicit_resume_choice) is not SceneStageChoice
            or scene_checkpoint_root is None
            or explicit_resume_choice.episode > through_episode
            or explicit_resume_choice.stage > scenes_per_episode):
        raise AutoNovelRunError('직접 선택한 장면과 현재 집필 승인 범위를 다시 확인하세요.')
    if type(reference_paths) is not tuple:
        raise AutoNovelRunError('참고작 선택 자료 형식이 올바르지 않습니다.')
    reference_batch = None
    if reference_paths:
        if reference_catalog_path is None:
            raise AutoNovelRunError('참고작 분석용 별도 로컬 DB가 필요합니다.')
        # The user explicitly selects all reference paths for THIS batch.
        # Metadata/profile persistence is separate from manuscript SQLite.
        reference_batch = prepare_reference_batch(
            reference_paths, catalog_path=reference_catalog_path,
            manuscript_database_path=database_path,
            selected_metric_keys=reference_metric_keys)

    created, skipped, review = [], [], []
    style_scope_count = 0
    continuation_calls = 0
    calls, stopped = 0, False
    with EpisodeStore(database_path) as db:
        project = db.get_project(project_id)
        if context_sources is not None:
            require_unchanged_author_sources(db, project_id, context_sources)
        rules = {r.key: r.value for r in db.list_rules(project_id)}
        genre, subject, mood = (rules.get(k, '').strip() for k in
                                ('genre', 'subject', 'mood'))
        if not genre or not subject or not mood:
            raise AutoNovelRunError('작품에서 장르·소재·분위기를 먼저 저장하세요.')
        total_setting = rules.get('target_episodes', '').strip()
        # Do not leak private saved Novel Bible content via the exception
        # generated by int('corrupt author input').
        if not total_setting.isdecimal() or not 1 <= int(total_setting) <= 1000:
            raise AutoNovelRunError('목표 회차 설정이 올바르지 않습니다.')
        total = int(total_setting)
        if through_episode > total:
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
        # Connect author-selected, model-generated 1~N episode outlines to
        # the ACTUAL GGUF prose writer, not merely the planning-only GUI.
        # One explicitly selected set is frozen for the full batch and is
        # checked BEFORE any synopsis call or SQLite plot/draft persistence.
        episode_guide = {}
        if episode_writing_guidance is not None:
            require_current_author_ai_novel_guidance(
                episode_writing_guidance, db, database_path,
                project_id, through_episode)
            episode_guide = {
                number: body
                for number, body in episode_writing_guidance.plans.episode_drafts
                if number <= through_episode
            }
        # A single author-approved source selection applies to the entire
        # requested batch, not only the last chapter shown in the GUI.
        # Resolve every missing chapter BEFORE any AI synopsis/scene call.
        # Saved chapters are read only and are never overwritten.
        if context_sources is not None:
            from .author_context_scope import plan_author_context_scope
            context_plan = plan_author_context_scope(
                db, project_id, through_episode=through_episode,
                scenes_per_episode=scenes_per_episode, sources=context_sources)
            if context_plan.blocked:
                first = ', '.join(
                    str(row.episode) for row in context_plan.episodes
                    if row.status == 'CONTEXT_BLOCKED')[:90]
                raise AutoNovelRunError(
                    f'선택한 작가 통합 문맥 {context_plan.blocked}화 준비 미완료 '
                    f'(회차: {first}). AI 실행 전 기록·장면 수를 다시 확인하세요.')
        if explicit_resume_choice is not None:
            if (explicit_resume_choice.episode in existing
                    or any(n not in existing for n in range(1, explicit_resume_choice.episode))):
                raise AutoNovelRunError(
                    '선택 장면의 회차가 다음 신규 회차가 아닙니다. 기존 원고를 덮어쓰지 않습니다.')
        # Author-owned character facts must be visible inside the FIRST
        # 12k native-context characters, rather than only the names list.
        with CharacterStore(database_path) as chars:
            characters = chars.list_characters(project_id)[:8]
        character_names = tuple(c.name for c in characters) or ('주인공',)
        character_bible = _character_bible_context(characters)
        # The preview is explicitly UNAPPROVED and will be appended once
        # below. Do not accidentally duplicate it as a saved canon rule.
        canon_rules = ['%s: %s' % (k, v) for k, v in rules.items()
                       if k not in {'author', 'ai_story_outline_preview'} and v.strip()]
        canon_base = (character_bible[:6500] + '\n' +
                      '\n'.join(canon_rules)[:1000]).strip()
        # The local writer sees numerical patterns only, NEVER reference prose.
        reference_statistics = (reference_batch.aggregate_context
                                if reference_batch is not None else '')
        saved_context = read_saved_author_context(database_path, project_id, 1)
        canon = (canon_base + '\n' + saved_context.memory + '\n' +
                 reference_statistics).strip()[:14000]
        # Separate native author-notes field retains time-scoped facts even
        # when the 12k Novel Bible field is shortened for a long scene.
        active_style_bible = (saved_context.style + '\n' + saved_context.memory)[:5000]
        if not canon:
            raise AutoNovelRunError('Novel Bible 입력이 비어 있습니다.')

        def emit(number: int, stage: str) -> None:
            if progress is not None:
                progress(number, stage)

        def model(episode_num: int, scene_num: int, context: str,
                  goal: str, conflict: str, place: str, *,
                  allocated_scene_chars: int | None = None) -> str:
            nonlocal calls
            if should_stop is not None and should_stop():
                raise InterruptedError()
            if context_sources is not None:
                require_unchanged_author_sources(db, project_id, context_sources)
            request = SceneDraftRequest(
                project_id, episode_num, scene_num, context[:22000],
                goal[:2000], conflict[:2000], place[:1000], character_names,
                style_bible=active_style_bible,
                target_chars=allocated_scene_chars)
            calls += 1
            draft = draft_scene(request, provider).draft
            if not draft.strip():
                raise AutoNovelRunError('로컬 AI 모델이 빈 초고를 반환했습니다.')
            return draft

        # Generate a genuine model-written *unapproved whole-story synopsis*
        # once before the first missing episode. It is visible in Novel Bible
        # under a clearly preview-only key; it is NOT canon or approved facts.
        missing = any(n not in existing for n in range(1, through_episode + 1))
        story_preview = rules.get('ai_story_outline_preview', '')
        if explicit_resume_choice is not None and not story_preview.strip():
            raise AutoNovelRunError('장면 재개 전에 저장된 전체 스토리 초안이 필요합니다. 자동 생성하지 않습니다.')
        if missing and not story_preview.strip():
            # The whole-story draft takes a long model call. Capture the
            # author's original Bible and ALL previously saved chapters
            # before generation; never persist a preview based on stale facts.
            with EpisodeStore(database_path) as preview_source:
                preview_source_state = _auto_author_source_stamp(
                    preview_source, database_path, project_id, total + 1)
            emit(0, '전체 스토리 기획 초안 로컬 AI 생성')
            try:
                story_preview = model(
                    1, 1, canon,
                    f'{project.title}: {genre} 장편소설 {total}화의 독창적인 전체 줄거리 '
                    f'({subject}), 주인공 목표와 결말, 주요 Arc 전환점, 세계관을 '
                    '일관되게 기획. 문장·고유명사 복제 금지. 검토 전 초안.',
                    f'{mood} 분위기와 인물 동기를 고려한 전체 갈등',
                    f'가상의 {genre} 세계')
            except InterruptedError:
                return AutoNovelRunReport(
                    through_episode, (), (), (), True, calls)
            # Stop requested while the blocking model was generating:
            # even an *unapproved* synopsis must not be saved after stop.
            if should_stop is not None and should_stop():
                return AutoNovelRunReport(
                    through_episode, (), (), (), True, calls)
            if reference_batch is not None:
                verify_reference_batch(reference_batch)
            with EpisodeStore(database_path) as safe:
                if (_auto_author_source_stamp(
                        safe, database_path, project_id, total + 1)
                        != preview_source_state):
                    raise AutoNovelRunError(
                        '전체 줄거리 생성 중 작가 설정이나 저장 회차가 변경되어 '
                        '오래된 초안을 저장하지 않았습니다.')
                if any(rule.key == 'ai_story_outline_preview'
                       for rule in safe.list_rules(project_id)):
                    raise AutoNovelRunError('다른 창에서 전체 스토리 초안을 저장했습니다. 재확인하세요.')
                if reference_batch is not None:
                    verify_reference_batch(reference_batch)
                safe.save_rule(project_id, 'ai_story_outline_preview',
                               story_preview[:3500])
        if story_preview.strip():
            canon = (canon + '\n전체 스토리 AI 계획 초안(미확정·검수 전): '
                     + story_preview[:3500])[:19000]

        expected_author_state = None
        for n in range(1, through_episode + 1):
            if context_sources is not None:
                require_unchanged_author_sources(db, project_id, context_sources)
            if n in existing:
                # Never overwrite user-owned episodes or earlier batch data.
                # A legacy interrupted write may have left plot-only records:
                # make them visible as requiring review instead of treating
                # the chapter as a completed long-form generation.
                skipped.append(n)
                if _existing_episode_needs_review(
                        existing[n], scenes=db.list_scenes(project_id, n),
                        checks=db.list_checks(project_id, n)):
                    review.append(n)
                    emit(n, '기존 미완료 회차: 사용자 검토 필요, 덮어쓰기 없음')
                continue
            if should_stop is not None and should_stop():
                stopped = True
                break
            # The author can edit the Bible or an earlier chapter while a
            # long-running model is active. Never silently continue against
            # the old snapshot into another episode.
            with EpisodeStore(database_path) as current_source:
                started_source_state = _auto_author_source_stamp(
                    current_source, database_path, project_id, n)
            current_author_lease = (started_source_state[0],
                                    started_source_state[1],
                                    started_source_state[3])
            if expected_author_state is None:
                expected_author_state = current_author_lease
            elif current_author_lease != expected_author_state:
                raise AutoNovelRunError(
                    '작가가 저장한 설정/인물/세계관/문체/사건이 변경되어 자동 집필을 중단했습니다.')
            plan = plans[n]
            arc = by_arc[plan.arc_number]
            slots = plan_scenes(plan, scenes_per_episode)
            if not validate_scene_plans(plan, slots):
                raise AutoNovelRunError('장면 계획 연속성이 깨졌습니다.')
            # Explicitly opted-in stage cache; not a final text or validation.
            checkpoint = None
            if scene_checkpoint_root is not None:
                checkpoint = SceneResumeScope(
                    Path(database_path), project_id, n, Path(scene_checkpoint_root),
                    scene_checkpoint_lease, started_source_state,
                    (plan, slots, scene_targets), scenes_per_episode).open_store()
            if (explicit_resume_choice is not None
                    and n == explicit_resume_choice.episode):
                require_explicit_scene_resume(
                    checkpoint, explicit_resume_choice,
                    scenes_per_episode=scenes_per_episode)

            def record_unapproved_stage(stage: int, body: str) -> None:
                if checkpoint is None:
                    return
                with EpisodeStore(database_path) as snapshot:
                    if _auto_author_source_stamp(
                            snapshot, database_path, project_id, n) != started_source_state:
                        raise AutoNovelRunError(
                            '집필 중 작가 원본이 변경되어 임시 장면 저장을 보류했습니다.')
                if reference_batch is not None:
                    verify_reference_batch(reference_batch)
                checkpoint.save_stage(stage, body)
            # Only previously saved *draft summaries*, explicitly marked as
            # unapproved, are used as context; they never overwrite canon.
            # Only saved facts effective at this chapter enter its local
            # model context. Future relationship/knowledge changes stay hidden.
            saved_context = read_saved_author_context(database_path, project_id, n)
            active_style_bible = (saved_context.style + '\n' + saved_context.memory)[:5000]
            chapter_canon = (canon_base + '\n' + saved_context.memory + '\n' +
                             reference_statistics).strip()
            chosen_episode_outline = episode_guide.get(n, '')
            if story_preview.strip():
                chapter_canon += ('\n전체 스토리 AI 계획 초안(미확정·검수 전): '
                                  + story_preview[:1500])
            # Only saved earlier chapter records may extend the existing
            # Novel Bible/canon context; never invent absent chapters.
            context = extend_scene_context(
                _continuity_context(chapter_canon[:14000], existing, n),
                existing, n)
            # Four author-selected local ledgers form ONE optional envelope.
            # Do not auto-load unselected sources or trim author-written facts.
            approved_context = None
            if context_sources is not None:
                approved_context = compose_author_context(
                    db, project_id, episode=n,
                    scene_count=scenes_per_episode, sources=context_sources)
                merged = approved_context.outline + '\n' + context
                if len(merged) > 22000:
                    raise AutoNovelRunError(
                        '통합 작가 문맥이 실제 모델 입력 길이를 초과했습니다. 임의 축약하지 않습니다.')
                context = merged
            emit(n, '회차 플롯 로컬 AI 생성')
            try:
                outline = checkpoint.load_stage(0) if checkpoint is not None else None
                if outline is None:
                    # Put selected AI guidance FIRST in the bounded local
                    # model goal. It remains a non-canon candidate until the
                    # author separately reviews it; the actual plot is still
                    # written by the user's approved native GGUF model.
                    plot_goal = (
                        f'{project.title}: {subject}. {n}/{total}화의 구체적인 '
                        '독창적 사건과 갈등을 설계. '
                        f'현재 ARC {arc.number} ({arc.start_episode}~{arc.end_episode}화). '
                        'Novel Bible을 지키고 전 회차의 결과를 이어 새로운 회차 플롯을 작성.')
                    if chosen_episode_outline:
                        plot_goal = (
                            '이번 실행에 작가가 별도 선택한 AI 회차 기획 후보 '
                            '(미검수, Novel Bible보다 우선 금지; 일부 발췌): '
                            + _plot_endpoints(chosen_episode_outline, 1050)
                            + '\n' + plot_goal)
                    past_event_evidence = retrieve_relevant_saved_events(
                        existing, n, chosen_episode_outline or subject,
                        max_chars=1050)
                    outline = model(
                        n, 1, context,
                        plot_goal,
                        (past_event_evidence + '\n' + f'{mood} 분위기의 갈등과 연속성 유지')[:2000],
                        f'작품 세계관 ({genre})')
                    record_unapproved_stage(0, outline)
                else:
                    emit(n, '동일한 이번 실행 승인과 일치한 미검수 플롯 임시 기록 재사용')
                drafts = []
                for scene_index, slot in enumerate(slots):
                    cached = checkpoint.load_stage(slot.scene_number) if checkpoint else None
                    if cached is not None:
                        drafts.append(cached)
                        emit(n, f'장면 {slot.scene_number} 미검수 임시 기록 재사용')
                        continue
                    per_scene = scene_targets[scene_index]
                    emit(n, f'장면 {slot.scene_number}/{scenes_per_episode} 로컬 AI 집필')
                    scene_goal = _native_scene_generation_goal(
                        n, slot.scene_number, scenes_per_episode,
                        outline, per_scene)
                    scene_context = _scene_generation_context(
                        context, outline, drafts[-1] if drafts else '')
                    if chosen_episode_outline:
                        # The native bridge reads the first 12k characters.
                        # Give the selected AI episode candidate a bounded,
                        # explicitly noncanonical place where it is actually
                        # visible during every REAL scene-generation call.
                        scene_context = (
                            '이번 화에 작가가 선택한 미검수 AI 기획 후보 '
                            '(중간 생략 표시, 확정 원고/사실 아님):\n'
                            + _plot_endpoints(chosen_episode_outline, 1150)
                            + '\n' + scene_context)[:12000]
                    if approved_context is not None:
                        extra_scene = approved_context.scenes[scene_index]
                        scene_context = (extra_scene + '\n' + scene_context
                                         if extra_scene else scene_context)
                        if len(scene_context) > 22000:
                            raise AutoNovelRunError(
                                '승인된 작가 장면 지시가 모델 문맥 한도를 초과했습니다.')
                    scene_evidence = build_real_scene_chain(
                        existing, n, slot.scene_number, tuple(drafts),
                        chosen_episode_outline or outline,
                        next_plan=episode_guide.get(n + 1, ''))
                    scene = model(n, slot.scene_number, scene_context,
                                  scene_goal, scene_evidence,
                                  f'{genre} 작품의 장면',
                                  allocated_scene_chars=per_scene)
                    scene_screen = screen_korean_draft(
                        scene, target_chars=per_scene)
                    original_repeat = check_repetition(project_id, n, scene)
                    # The previous <120-character test let a 300-char scene
                    # pass a 1600-char target. Evaluate the actual scene
                    # target, Korean script, repeated prose and formatting,
                    # and allow just one REAL model revision per scene.
                    if (not scene_screen.format_gate_pass
                            or original_repeat.findings):
                        emit(n, f'장면 {slot.scene_number} 재작성')
                        revised = model(
                            n, slot.scene_number,
                            _scene_revision_context(scene_context, scene),
                            _native_scene_revision_goal(per_scene),
                            (scene_evidence + '\n반복 표현을 줄이고 사건·동기·행동을 구체화')[:2000],
                            f'{genre} 작품의 장면',
                            allocated_scene_chars=per_scene)
                        revised_screen = screen_korean_draft(
                            revised, target_chars=per_scene)
                        revised_repeat = check_repetition(project_id, n, revised)
                        better_format = (revised_screen.format_gate_pass
                                         and not scene_screen.format_gate_pass
                                         and not revised_repeat.findings)
                        better_partial = (
                            revised_screen.nonspace_chars > scene_screen.nonspace_chars
                            and revised_screen.hangul_share >= scene_screen.hangul_share
                            and revised_screen.repeated_sentence_share <=
                                scene_screen.repeated_sentence_share
                            and revised_screen.repeated_chunk_share <=
                                scene_screen.repeated_chunk_share
                            and revised_screen.non_prose_markers == 0
                            and not has_foreign_script_corruption(revised)
                            and not revised_repeat.findings)
                        if better_format or better_partial:
                            scene = revised
                    # A single native generation can be shorter than the
                    # author's per-scene target. Request bounded, REAL
                    # continuations from the same approved local model.
                    # Never pad with templates, lower the target, or mark
                    # a short scene as quality-approved.
                    for continuation_index in range(4):
                        current_screen = screen_korean_draft(
                            scene, target_chars=per_scene)
                        remaining = per_scene - current_screen.nonspace_chars
                        if remaining <= 0:
                            break
                        if should_stop is not None and should_stop():
                            raise InterruptedError()
                        emit(n, f'장면 {slot.scene_number} 실제 AI 이어쓰기 '
                             f'{continuation_index + 1}/4')
                        continuation = model(
                            n, slot.scene_number,
                            ('이전 실제 장면 마지막 부분(중복 없이 다음 문장부터 이어 쓰기):\n'
                             + scene[-1800:] + '\n' + scene_context)[:12000],
                            f'목표 분량 {min(10000, max(50, remaining))}자 내외의 '
                            '독창적인 새 소설 문장만 이어서 작성. 앞 문장 재출력 금지. '
                            '작가 Novel Bible 및 이전 사건의 인과관계를 유지.',
                            (scene_evidence + '\n앞 장면에 이어지는 실제 사건·행동·감정')[:2000],
                            f'{genre} 작품의 이어지는 장면',
                            allocated_scene_chars=min(10000, max(50, remaining)))
                        continuation_calls += 1
                        if (not continuation.strip()
                                or has_foreign_script_corruption(continuation)):
                            break
                        # Keep the original model's prose byte-for-byte;
                        # concatenate only model-generated continuation text.
                        candidate = scene.rstrip() + '\n\n' + continuation.strip()
                        if len(candidate.encode('utf-8')) > 80000:
                            break
                        candidate_screen = screen_korean_draft(
                            candidate, target_chars=per_scene)
                        if (candidate_screen.nonspace_chars <= current_screen.nonspace_chars
                                or candidate_screen.hangul_syllables <=
                                    current_screen.hangul_syllables
                                or check_repetition(project_id, n, candidate).findings):
                            break
                        scene = candidate
                    record_unapproved_stage(slot.scene_number, scene)
                    drafts.append(scene)

                # The author requested ~5000 REAL Korean prose characters per
                # episode, not a collection of undersized scene summaries.
                # Per-scene native calls and four continuations may still
                # underfill an actual episode. Continue the FINAL real scene,
                # bounded to six EXTRA calls per episode, before persisting.
                # No template filler, quality-PASS, new source novel, or
                # alteration of the author's saved prior manuscript is allowed.
                # A persistently short output remains WARN and human-review.
                for chapter_tail_pass in range(6):
                    actual = '\n\n'.join(drafts)
                    actual_screen = screen_korean_draft(
                        actual, target_chars=target_chars)
                    deficit = target_chars - actual_screen.nonspace_chars
                    if deficit <= 0:
                        break
                    if should_stop is not None and should_stop():
                        raise InterruptedError()
                    requested = min(10_000, max(50, deficit))
                    emit(n, f'회차 {n}화 실제 AI 본문 분량 이어쓰기 '
                         f'{chapter_tail_pass + 1}/6 '
                         f'(현재 {actual_screen.nonspace_chars}/{target_chars}자)')
                    ending_context = (
                        '이미 집필한 해당 회차 마지막 장면(미검수, 되풀이 금지):\n'
                        + drafts[-1][-1900:] + '\n'
                        + ('이번 화 미검수 AI 기획 후보(확정 아님):\n'
                           + _plot_endpoints(chosen_episode_outline, 900) + '\n'
                           if chosen_episode_outline else '')
                        + _scene_generation_context(context, outline, drafts[-1])
                    )[:12000]
                    tail = model(
                        n, slots[-1].scene_number, ending_context,
                        f'목표 분량 {requested}자 내외의 독창적인 한국어 '
                        '소설 후속 본문만 작성. 앞선 문단·대사 재출력 금지. '
                        '마지막 장면에서 벌어진 선택의 직접적 결과와 '
                        '앞서 쌓은 복선에 따른 새 행동을 이어 서술.',
                        build_real_scene_chain(
                             existing, n, slots[-1].scene_number,
                             tuple(drafts), chosen_episode_outline or outline,
                             next_plan=episode_guide.get(n + 1, '')),
                        f'{genre} 작품 세계관의 마지막 장면',
                        allocated_scene_chars=requested)
                    continuation_calls += 1
                    if not tail.strip() or has_foreign_script_corruption(tail):
                        break
                    last_scene = drafts[-1].rstrip() + '\n\n' + tail.strip()
                    candidate = '\n\n'.join((*drafts[:-1], last_scene))
                    improved = screen_korean_draft(
                        candidate, target_chars=target_chars)
                    if (improved.nonspace_chars <= actual_screen.nonspace_chars
                            or improved.hangul_syllables <= actual_screen.hangul_syllables
                            or len(last_scene.encode('utf-8')) > 80000
                            or check_repetition(project_id, n, candidate).findings):
                        # Never fake the requested length by concatenating
                        # duplicated, foreign-script, or empty model output.
                        break
                    drafts[-1] = last_scene
            except InterruptedError:
                stopped = True
                break
            full_draft = '\n\n'.join(drafts)
            reference_review = None
            if reference_batch is not None:
                reference_review = review_batch_draft(
                    reference_batch, project_id, n, full_draft, tuple(drafts))
                if reference_review.blocked:
                    raise AutoNovelRunError(
                        '선택 참고작과 직접 중복 위험이 있어 이 회차 초고를 저장하지 않았습니다.')
            repetition = check_repetition(project_id, n, full_draft)
            # Empty spaces and formatting do not count toward the agreed
            # manuscript quota. Use the original model text unchanged.
            # Full literary screening remains independent and stricter.
            # No source novel's raw passages are stored. The reference-similarity
            # gate cannot claim PASS without full, reloaded source coverage.
            # Continuity/logic/reader checks likewise need fresh evidence.
            # Scope-limited tests cannot establish comprehensive quality or
            # clearance against registered reference novels.
            requires_review = True
            # Screen actual, unaltered model prose separately from the old
            # length/repetition checks; this is NOT literary certification.
            screen = screen_korean_draft(full_draft, target_chars=target_chars)
            enough = screen.nonspace_chars >= target_chars
            # Examine ALL actual saved earlier drafts, up to the planned
            # 250-chapter scope; do not silently certify only the last three.
            # Missing/empty earlier chapters remain explicit unexamined gaps.
            # This screen is exact-sentence-only, never literary certification.
            prior_drafts, missing_prior, older_unexamined = (
                _cross_episode_sources(existing, n))
            cross = screen_cross_episode_reuse(full_draft, prior_drafts)
            checks = [
                ('length', 'PASS' if enough else 'WARN',
                 f'actual_chars={len(full_draft)};'
                 f'actual_nonspace={screen.nonspace_chars};'
                 f'target_chars={target_chars}'),
                ('repetition', 'PASS' if repetition.passed_checked_scope else 'WARN',
                 f'finding_count={len(repetition.findings)};'
                 f'unexamined_count={len(repetition.unexamined)}'),
                ('korean_format', 'PASS' if screen.format_gate_pass else 'WARN',
                 f'hangul={screen.hangul_syllables};nonspace={screen.nonspace_chars};'
                 f'foreign={screen.han_script_chars};'
                 f'repeated_sentence_share={screen.repeated_sentence_share};'
                 f'non_prose_markers={screen.non_prose_markers}'),
                ('cross_episode_sentence_reuse',
                 'WARN' if cross.exact_sentence_reuses or missing_prior
                           or older_unexamined
                 else 'PASS' if cross.prior_episodes_examined else 'NOT_RUN',
                 f'prior_episodes_examined={cross.prior_episodes_examined};'
                 f'missing_prior_episodes={missing_prior};'
                 f'older_prior_unexamined={older_unexamined};'
                 f'exact_sentences={cross.exact_sentence_reuses};'
                 f'affected_chapters={cross.affected_prior_episodes};'
                 'scope_only=true;literary_approved=false'),
            ]
            if reference_review is None:
                checks.append(('reference_similarity', 'NOT_RUN',
                               '참고작 미선택·원문 전수 검사 NOT_RUN'))
            else:
                checks.append(('reference_similarity', reference_review.check_status,
                               reference_review.detail))
            # Real, local, deterministic Style Bible rules are checked against
            # the actual generated prose. This is scoped evidence only:
            # no viewpoint inference, literary certification, PASS, or publication.
            # The full author-source stamp is checked again before persistence.
            style_scoped = False
            try:
                with StyleBibleStore(database_path) as style_store:
                    style_report = check_style(
                        style_store, project_id, n, full_draft)
                if style_report.applied_rules:
                    style_scoped = True
                    style_result = 'FAIL' if style_report.findings else 'WARN'
                    style_note = (
                        f'checked_rule_count={len(style_report.applied_rules)};'
                        f'unexamined_rule_count={len(style_report.unexamined_rules)};'
                        f'finding_count={len(style_report.findings)};'
                        f'manuscript_sha256={style_report.manuscript_sha256};'
                        'scope_only=true;viewpoint_unlabelled=true;'
                        'human_review_required=true;publication_approved=false')
                else:
                    style_result = 'NOT_RUN'
                    style_note = (
                        '실행 가능한 문체 규칙 없음;'
                        'human_review_required=true;publication_approved=false')
            except (StyleCheckerError, OSError, ValueError):
                style_result = 'NOT_RUN'
                style_note = (
                    '문체 규칙 또는 현재 SQLite 상태를 확인할 수 없어 자동 합격 처리 안 함;'
                    'human_review_required=true;publication_approved=false')
            checks.append(('style_scope', style_result, style_note))
            checks.extend((category, 'NOT_RUN',
                           '전체 증거가 없어 자동 승인하지 않음')
                          for category in ('continuity', 'logic', 'timeline',
                                           'foreshadowing', 'reader_simulation'))
            # Existing staged writes could strand an empty chapter when the
            # app stopped between create_episode and add_check. One SQLite
            # transaction now inserts the draft, scenes and all QC records.
            # The database uniqueness constraint protects concurrent editors.
            # Recheck cancellation AFTER slow generation and QC. An explicit
            # stop before persistence must not create one more chapter.
            if should_stop is not None and should_stop():
                stopped = True
                break
            with EpisodeStore(database_path) as safe:
                if (_auto_author_source_stamp(
                        safe, database_path, project_id, n)
                        != started_source_state):
                    raise AutoNovelRunError(
                        '집필 중 Novel Bible 또는 이전 저장 회차가 변경되어 '
                        '오래된 AI 결과를 저장하지 않았습니다.')
                if reference_batch is not None:
                    verify_reference_batch(reference_batch)
                if context_sources is not None:
                    require_unchanged_author_sources(safe, project_id, context_sources)
                current = safe.create_unapproved_batch_episode(
                    project_id, n, plot=outline,
                    draft=full_draft,
                    summary='미확정 AI 플롯 요약: ' + outline[:1600],
                    # Persist the actual native model-written scene text.
                    # The previous version stored manufactured outline/goal
                    # placeholders in bible_episode_scenes while full_draft
                    # held different prose, corrupting source provenance and
                    # subsequent GUI scene reading. No model text is invented.
                    scenes=tuple((slot.scene_number, scene_text)
                                 for slot, scene_text in zip(slots, drafts)),
                    checks=tuple(checks))
            created.append(n)
            if style_scoped:
                style_scope_count += 1
            existing[n] = current
            if requires_review:
                review.append(n)
            emit(n, '미승인 초고 저장 및 수동 검수 대기')
    return AutoNovelRunReport(through_episode, tuple(created), tuple(skipped),
                              tuple(review), stopped, calls,
                              style_scope_checked_episodes=style_scope_count,
                              continuation_model_calls=continuation_calls)
