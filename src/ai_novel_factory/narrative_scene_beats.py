"""실제 로컬 GGUF가 작성한 회차 플롯의 장면별 사건 배정.

새로운 사건이나 원고를 만들어 넣지 않는다. 동일한 전체 플롯을
모든 장면에 되풀이 전달하지 않도록 원래 모델이 쓴 사건을 시간순으로
각 장면의 별도 입력으로 분배한다. 작가 원본과 저장 DB는 읽거나 쓰지 않는다.
플롯의 문학적 적합성·회차 품질·출판 승인 판정이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ModelPlotSceneBeat:
    scene_number: int
    assigned_plot: str
    preceding_plot: str
    distinct_assignment: bool
    quality_certified: bool = False


def _bounded_source_excerpt(text: str, limit: int) -> str:
    """중간을 잘라내더라도 실제 모델 플롯의 앞과 뒤를 모두 표시."""
    if len(text) <= limit:
        return text
    marker = '\n[이 장면에 배정된 플롯 일부 생략]\n'
    before = (limit - len(marker)) // 2
    after = limit - len(marker) - before
    return text[:before] + marker + text[-after:]


def allocate_model_plot_beats(
    actual_model_plot: str, scene_count: int, *,
    excerpt_limit: int = 1050,
) -> tuple[ModelPlotSceneBeat, ...]:
    """실제 모델 생성 플롯을 시간순 비중에 따라 1~20장면으로 나눈다.

    1. 문장/줄 단위로 나누되 장면보다 문장이 적으면 단어로 재분할한다.
    2. 문장/단어조차 부족하면 원문 글자 단위로만 나눈다.
    3. 극단적으로 짧은 플롯은 거짓 사건을 추가하지 않고 원문 반복
       상태를 distinct_assignment=False로 명시한다.
    4. 각 장면은 다른 장면의 '미래 사건' 대신 자기 사건과 직전
       장면에 배정된 실제 원문 말미만 모델에 제공할 수 있다.
    """
    if (type(actual_model_plot) is not str or not actual_model_plot.strip()
            or len(actual_model_plot) > 300_000
            or type(scene_count) is not int or not 1 <= scene_count <= 20
            or type(excerpt_limit) is not int
            or not 200 <= excerpt_limit <= 3000):
        raise ValueError('실제 회차 플롯의 장면별 배정 조건이 올바르지 않습니다.')
    source = actual_model_plot.strip()
    sentence_units = [
        piece.strip() for piece in re.split(
            r'(?<=[.!?。！？])\s+|\n+', source)
        if piece.strip()
    ]
    if len(sentence_units) >= scene_count:
        units, separator = sentence_units, ' '
    else:
        words = re.findall(r'\S+\s*', source)
        if len(words) >= scene_count:
            units, separator = words, ''
        elif len(source) >= scene_count:
            units, separator = list(source), ''
        else:
            return tuple(ModelPlotSceneBeat(
                scene + 1, source, source[-220:] if scene else '', False)
                for scene in range(scene_count))
    result = []
    cursor = 0
    for scene in range(scene_count):
        remaining = scene_count - scene
        if remaining == 1:
            stop = len(units)
        else:
            max_stop = len(units) - remaining + 1
            remaining_length = sum(len(unit) for unit in units[cursor:])
            target = remaining_length / remaining
            stop = cursor + 1
            length = len(units[cursor])
            while stop < max_stop and length < target:
                length += len(units[stop])
                stop += 1
        raw = separator.join(units[cursor:stop]).strip()
        if not raw:
            raise ValueError('실제 플롯 장면 분할에 빈 배정이 있습니다.')
        preceding = result[-1].assigned_plot[-220:] if result else ''
        result.append(ModelPlotSceneBeat(
            scene + 1, _bounded_source_excerpt(raw, excerpt_limit),
            preceding, True))
        cursor = stop
    return tuple(result)
