# 75/100단계 — Logic Checker: 사건과 행동의 논리 검사

- 공식 로드맵: **75. Logic Checker 사건과 행동의 논리 검사**
- 요구사항: **ANF-REQ-052** (`docs/requirements.md`): 인물 동기·우연·능력 사용·사건 해결 논리 검사, 모순을 원고 근거 구간과 함께 보고
- 구현: `src/ai_novel_factory/logic_checker.py`
- 테스트: `tests/test_stage75_logic_checker.py`

## 지원 범위

외부 서비스에 접속하지 않고, 검토자가 미리 표시한 원고 근거 및 이야기 속 시간순서(`story_step`)를 기반으로 다음 **명시적 의존성**을 검사합니다.

1. `MOTIVE`: 행동을 정당화하기 위해 선언한 인물의 동기 전제.
2. `ABILITY`: 능력 사용을 뒷받침하는 선행 전제.
3. `CAUSE`: 사건의 원인으로 선언한 선행 전제.
4. `RESOLUTION`: 해결에 필요한 조건으로 선언한 선행 전제.
5. `coincidence=True`: 우연이라고 **검토자가 표시한** 행동에 대해 `COINCIDENCE_REVIEW` 참고 경고. 우연의 부적절함을 객관 판정하거나 횟수만으로 문학적 품질을 보증하지 않습니다.

`LogicPremise`는 작품 ID, 사실 키, 유형, 사실이 성립/부정된 이야기 순서, 장면 번호, 원고 내 정확한 근거 구간을 포함합니다. `LogicAction`은 동일 작품 ID, 유형, 실행 시점, 근거 구간과 필요한 전제 키를 포함합니다. 근거 문자열이 실제 원고 범위와 정확하게 일치해야 합니다. 한 사실의 전제 이력이 시간에 따라 바뀌면 해당 행동 이전의 가장 최근 값을 적용합니다. 같은 시점에 상충한 기록이 있거나 전제와 행동이 같은 시점이면 모순으로 확정하지 않고 검토 대상으로 반환합니다.

결과 코드:

| 코드 | 뜻 |
|---|---|
| `NO_DECLARED_JUSTIFICATION` | 필요한 전제가 입력되지 않음 |
| `NOT_ESTABLISHED` | 선언된 전제의 성립 근거가 없음 |
| `NOT_YET_ESTABLISHED` | 전제가 행동 이후에만 등장함 |
| `SAME_STEP_UNVERIFIABLE` | 같은 이야기 시점 내 순서를 판별할 수 없음 |
| `CONTRADICTED_PREMISE` | 행동 전에 마지막으로 기록된 전제가 부정됨 |
| `AMBIGUOUS_PREMISE` | 가장 최근 시점의 전제 기록이 서로 충돌함 |
| `COINCIDENCE_REVIEW` | 검토자가 지정한 우연 장치, 수동 검토 필요 |

보고서는 민감한 원고 문구 대신 작품/회차, 행동 ID, 유형, 전제 키, 근거 위치와 SHA-256 지문을 제공합니다. `check_episode_logic`은 65단계 `EpisodeDraftPreview`의 미확정/미저장 상태, 전체·장면별 원고 지문, 장면별 근거 위치를 확인합니다. 원고 변경·출판 승인·DB 저장을 수행하지 않습니다.

## 예시

```python
from ai_novel_factory.logic_checker import LogicPremise, LogicAction, check_logic

text = '동료를 믿었다. 봉인을 해제했다.'
premise = LogicPremise('work-1', 'trust', 'MOTIVE', 1, 1, 0, 7, '동료를 믿었다')
action = LogicAction('work-1', 'unlock', 'MOTIVE', 2, 1, 9, 17, '봉인을 해제했다', ('trust',))
report = check_logic('work-1', 1, text, (premise,), (action,))
# 위 예시는 실제 텍스트의 인덱스에 맞춰 start/end를 지정해야 합니다.
```

## 한계와 안전 원칙

- **사람이 표시한 구조화된 사실·행동만 검사**합니다. 자연어로 모든 행동 동기/우연/능력/해결 방식을 자동 추출하거나 문학적 개연성을 판단하는 모델이 아닙니다.
- `story_step`은 원고에 등장하는 순서와 독립된 **사용자 입력 사건 시간순서**입니다. 동일 스텝 내 인과관계는 판정하지 않습니다. 다른 회차의 사건·설정을 자동 검색하거나 Novel Bible DB 내용을 수집하지 않습니다.
- 잘못된 입력·다른 작품의 근거·원고 해시 변경은 검사 자체를 거부합니다. 보고서가 비어 있어도 **전체 원고 QC 통과를 의미하지 않습니다**.
- 참고작 원문 사용·복제 없음. Novel Bible을 변경·무시하지 않음. 사용자 승인 없는 원고 저장/확정/출판 없음.
- 실 Windows GUI·EXE/실제 로컬 LLM/Redis·Celery 서버 통합 테스트 미수행.

## 실행

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage75*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```
