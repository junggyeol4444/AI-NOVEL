"""Read-only causal memory of ACTUALLY generated earlier scenes in a chapter.

This is factual *prose provenance* (accepted model output), not a story-fact
extractor, author approval, literary certification, or model-generated summary.
Only scenes already in this chapter's draft list enter the prompt; later
scene plans and future chapters cannot enter through this component.
"""
from __future__ import annotations

from dataclasses import dataclass


class IntraChapterHandoffError(ValueError):
    """Errors contain no source manuscript."""


@dataclass(frozen=True)
class IntraChapterHandoff:
    target_scene: int
    prior_scene_count: int
    context: str
    omitted_scenes: int
    source_kind: str = 'PREVIOUS_SCENES_UNREVIEWED_AI_PROSE'
    quality_certified: bool = False
    publication_approved: bool = False


def build_intra_chapter_handoff(
    accepted_scenes: tuple[str, ...], target_scene: int,
    *, max_chars: int = 1600,
) -> IntraChapterHandoff:
    """Compress earlier ACTUAL accepted prose, not future outline events.

    Keep every previous scene's chronology where possible. The recent two
    scenes' endings receive more space. A skipped scene is explicitly marked
    so the local model cannot treat the displayed subset as the whole work.
    This function does not read SQLite, write a checkpoint or call a model.
    """
    if (type(accepted_scenes) is not tuple
            or type(target_scene) is not int
            or not 1 <= target_scene <= 20
            or len(accepted_scenes) != target_scene - 1
            or any(type(s) is not str or not s.strip()
                   or len(s) > 100_000 for s in accepted_scenes)
            or type(max_chars) is not int
            or not 600 <= max_chars <= 2500):
        raise IntraChapterHandoffError('앞선 장면 기억의 번호 또는 분량이 올바르지 않습니다.')
    if not accepted_scenes:
        return IntraChapterHandoff(target_scene, 0, '', 0)
    title = (
        f'[이번 회차 {target_scene}번째 장면 작성 전의 실제 저장·복원된 '
        f'{len(accepted_scenes)}개 미검수 AI 장면 기억]\n'
        '아래 순서는 실제 생성된 장면의 시간순이며, 발췌한 문장 외의 '
        '중간 사건은 확인되지 않음. 앞선 장면을 재서술하지 말고 '
        '새 인과·행동을 진행. 출판·작가 검수 완료 사실 아님.\n'
    )
    footer = '\n[각 장면 원문 일부만 표시. 표시되지 않은 원고의 사실은 추측 금지]'
    budget = max_chars - len(title) - len(footer)
    # Fixed bounded summaries give every earlier scene a chance to survive
    # even when the source is a 20-scene, 50k-character novel chapter.
    shares = []
    count = len(accepted_scenes)
    for i in range(count):
        weight = 3 if i == count - 1 else 2 if i == count - 2 else 1
        shares.append(weight)
    weights = sum(shares)
    records = []
    skipped = 0
    remaining = budget
    for i, (prose, weight) in enumerate(zip(accepted_scenes, shares), 1):
        remaining_weight = sum(shares[i - 1:])
        limit = max(0, min(remaining, remaining * weight // remaining_weight))
        label = f'{i}장면 실제 초고 '
        tail_min = 36
        if limit < len(label) + tail_min:
            skipped += 1
            continue
        head_size = min(65, max(0, (limit - len(label)) // 4))
        tail_size = max(tail_min, limit - len(label) - head_size - 4)
        if len(prose) <= head_size + tail_size:
            excerpt = prose
        else:
            excerpt = (prose[:head_size] + ' … ' + prose[-tail_size:])
        line = label + excerpt.replace('\x00', '') + '\n'
        if len(line) > remaining:
            skipped += 1
            continue
        records.append(line)
        remaining -= len(line)
    if not records:
        raise IntraChapterHandoffError('앞선 장면 원문을 담을 문맥 공간이 없습니다.')
    if skipped:
        footer += f'\n[앞선 장면 {skipped}개 표시 생략: 내용 미확인]'
    result = title + ''.join(records) + footer
    if len(result) > max_chars:
        raise IntraChapterHandoffError('장면 연결 문맥의 길이가 초과되었습니다.')
    return IntraChapterHandoff(target_scene, count, result, skipped)
