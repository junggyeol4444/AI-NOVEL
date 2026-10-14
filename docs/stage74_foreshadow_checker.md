# 74/100 — 복선 설치·진행·회수 상태 검사

## 근거 및 범위

- 사용자가 제공한 100단계 공식 로드맵 **74단계: 복선 설치·진행·회수 상태 검사**.
- `docs/requirements.md`에는 74단계에 직접 매핑되는 ANF-REQ ID가 없음. 기존 47단계 **ANF-REQ-037** `ForeshadowStore`의 이력/상태 전이를 읽기 전용 원고 대조 검사로 연결.
- 기준 ZIP: `AI_Novel_Factory_stage73_local.zip`(428개 파일). 먼저 `docs/requirements.md`, `docs/stage73_test_results.json`, `docs/stage73_verification_log.txt`를 확인함.

## 구현

`src/ai_novel_factory/foreshadow_checker.py`

- `ForeshadowClaim`: 검토자가 표시한 **복선 thread_id, 원고 시작/끝 위치, 실제 인용 구간**, 그리고 해당 회차에 수행했다는 `claimed_action` 혹은 회차 말 현재 `claimed_status` 중 정확히 하나.
- `check_foreshadowing(store, project_id, episode_number, manuscript, claims, expected_project_revision=None)`:
  - `INSTALL`, `REVISIT`, `RESOLVE`, `ABANDON` 행동은 **지정된 회차에 기록된 사건**과 일치하는지 확인. 다른 회차에 같은 행동이 기록되어 있어도 해당 회차의 행동으로 인정하지 않음.
  - `OPEN`, `DEVELOPING`, `RESOLVED`, `ABANDONED` 상태는 해당 회차가 끝난 시점의 상태와 대조. 같은 회차에 설치·재언급·회수가 연속 기록되면 저장된 `sequence`에 따라 **최종 상태**로 비교.
  - 설치 전 상태는 별도 `NOT_INSTALLED`로 판정하고, 저장 이력이 손상됐으면 검사 중단.
  - 보고서 코드 `ACTION_NOT_RECORDED`, `ACTION_CONFLICT`, `STATUS_CONFLICT`, `NOT_INSTALLED`.
  - `ForeshadowStore.audit()`로 이력 무결성을 먼저 검사하고, 작품 간 기록 섞임·입력 증거 변조·중복·잘못된 상태·오래된 revision을 거부.
- `check_episode_foreshadowing`은 65단계 `EpisodeDraftPreview` SHA-256, 미승인·미저장 상태를 확인한 뒤 같은 검사 수행.
- 보고서에 복선 제목·메모·원고 내용은 포함하지 않음. 복선 ID, 표시 위치, 결과 코드와 SHA-256 근거만 기록. SHA-256은 암호화나 비밀 보호 기능이 아님.
- DB 수정, 자동 수정, 신규 복선 이벤트 생성, 원고 자동 저장/확정, 출판 승인/출판 없음.

## 한계

- **검토자가 복선 언급과 예상 상태/행동 및 근거 위치를 직접 지정**해야 함. NLP로 복선 후보를 원고에서 자동 추출하지 않음.
- 기존 47단계 스키마에 **예정 회수 날짜/회차 필드가 없으므로** 예정 회수 기한 초과나 스토리 완결 여부를 자동 추정할 수 없음. 미해결 복선 전체 목록은 기존 `store.audit().unfinished_thread_ids`에서 별도 조회 가능.
- 같은 회차 **장면별 시간순**(회수 전/후) 검증이 아니라 회차 말 상태 기준 검사.
- 읽기 전후 revision 검사는 DB 전체에 대한 직렬화 격리를 보장하지 않음.
- 실제 Windows EXE/GUI, 실제 LLM 추론, Redis·Celery 실연동은 검증하지 않음.
- 외부 서버·클라우드 AI API·원격 저장소를 사용하지 않음. Novel Bible 우선, 참고작 원문 비복제, 사용자 승인 전 출판 금지 유지.

## 로컬 테스트

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage74*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

## 예제

```python
from ai_novel_factory.foreshadow_checker import ForeshadowClaim, check_foreshadowing

manuscript = '봉인된 문서가 다시 발견되었다.'
phrase = '다시 발견되었다'
start = manuscript.index(phrase)
claim = ForeshadowClaim(thread_id, start, start + len(phrase), phrase,
                        claimed_action='REVISIT')
report = check_foreshadowing(store, project_id, 5, manuscript, (claim,))
# report.findings 는 검토용 경고이며 전체 원고 품질 보증이나 출판 승인이 아님.
```
