# 71/100 — Continuity Checker: 설정·인물 일관성 검사

## 요구사항 / 실제 구현

- 원본 로드맵: **71단계, 설정·인물 일관성 검사**.
- `docs/requirements.md`: **ANF-REQ-051**, 이름·나이·직업·능력·장소 등 설정 연속성, 충돌하는 원고에 경고.
- 새 코드 `src/ai_novel_factory/continuity_checker.py`는 기존 로컬 SQLite Novel Bible, Character, World Canon Store에 **사용자가 직접 저장한 설정만** 읽어 작품별 스냅샷으로 구성합니다. 인물의 `secret` 값은 스냅샷에 넣지 않습니다.
- Novel Bible의 임의 규칙 키(`protagonist_age`, `protagonist_job` 등)·Character의 name/personality/goal/speech_style·World의 name/description을 지원합니다. 능력·장소를 포함한 사용자 작성 정형 설정은 대응하는 Bible 규칙 또는 World 항목을 통해 검사할 수 있습니다.
- `ManuscriptClaim`은 검토자가 원고에서 특정 값이 주장됐다고 **명시적으로 표시**한 문자열 범위(start:end, Python 문자 인덱스)와 필드·엔터티 식별자를 담습니다. 검사기는 원고 해당 범위와 주장값이 실제 일치하는지 먼저 확인합니다. Novel Bible/Character/World 값과 불일치하면 `CANON_CONFLICT`, 출처 식별자, 범위, 버전, 양쪽 값의 SHA-256 지문을 출력합니다. 보고서에는 문장·비밀 원문을 직접 넣지 않습니다.
- 다른 작품의 데이터 격리, 인물 비밀 배제, 존재하지 않는 canon 차단, 중복 사실·주장 거부, 스냅샷 버전 검사, 텍스트·작업량 상한, 읽기 전용 평가를 테스트합니다. 프로젝트 버전이 읽는 동안 바뀌거나 세 DB 핸들의 프로젝트 버전이 다르면 스냅샷을 거부합니다.
- `check_episode_draft`는 Stage 65/70의 **미승인 회차 초고**와 연결할 수 있으며 작품 ID·상태·원고 SHA-256을 검증합니다. 보고서의 `passed_declared_claims=True`는 **제출된 주장들 사이에 충돌이 없다는 뜻만** 의미합니다.

## 예시 / 실행

```python
from ai_novel_factory.continuity_checker import (
    ManuscriptClaim, load_continuity_canon, check_continuity
)

# bible, characters, world는 같은 로컬 SQLite 파일을 가리키도록 각각 엽니다.
canon = load_continuity_canon(project_id, bible=bible, characters=characters, world=world)
text = '주인공 나이는 29세다.'
start = text.index('29')
claim = ManuscriptClaim('novel_bible', 'protagonist_age', 'value', start, start + 2, '29')
report = check_continuity(canon, 1, text, (claim,), expected_project_revision=canon.project_revision)
# canon의 protagonist_age가 34일 경우 CANON_CONFLICT 근거 범위를 반환합니다.
```

테스트: `PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage71*.py' -q`.
전체 회귀: `PYTHONPATH=src python -m unittest discover -s tests -q`.

## 미구현 / 위험 고지

1. **자동 NLP 정보 추출은 미구현**입니다. 이름·직업·나이·능력·장소가 자유 서술, 은유, 부정문 또는 대사에 등장했을 때 자동으로 의미를 파악하지 않습니다. 검토자가 위치·주장값을 제공해야 하므로, 표시되지 않은 모순은 발견하지 못합니다. 이 결과만으로 원고가 완전히 일관적이라고 보증하지 않습니다.
2. **세 저장소 핸들은 같은 SQLite 파일을 가리켜야 합니다**. 프로젝트 ID 및 리비전 일치는 검사하지만 물리적 파일 동일성을 강제하지 않습니다. 검사 중 DB 저장·자동 수정·자동 확정·출판하지 않습니다.
3. 인물 지식 시점, 사건 시간선, 복선 상태, 논리/문체/유사성, 독자 평가 등은 후속 단계 범위입니다. Reference Novel 원문은 입력받지 않고 Novel Bible canon만 근거로 사용합니다.
4. 실제 Windows GUI/EXE, 실제 AI 모델 호출, Redis/Celery 실연동은 검증하지 않았습니다. 오프라인 Linux Python 실행에 한정합니다.
