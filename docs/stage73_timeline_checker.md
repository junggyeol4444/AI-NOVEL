# 73/100 — Timeline 날짜·시간·사건 순서 검사

## 계획 및 요구사항 근거

- 사용자가 제공한 **100단계 로드맵 73단계**: **Timeline 날짜·시간·사건 순서 검사**.
- `docs/requirements.md`: 73단계에 직접 매핑된 별도 ANF-REQ 번호는 없음. 기존 46단계 **ANF-REQ-036**의 `EventTimelineStore`를 **읽기 전용 원고 대조 검사**로 연결.
- 기준 ZIP: `AI_Novel_Factory_stage72_local.zip` (418개 파일). `docs/stage72_test_results.json`, `docs/stage72_verification_log.txt` 확인 후 개발.

## 구현

- `ai_novel_factory.timeline_checker.check_timeline(store, project_id, episode_number, manuscript, mentions, order_claims)`.
- 검토자가 **사건 ID, 원고의 근거 위치와 실제 인용 구간, 주장된 날짜/시간**을 지정한 경우 해당 작품의 Timeline DB와 비교.
- 절대 날짜(`YYYY-MM-DD` = UTC 하루의 구간), timezone-aware ISO timestamp(정확한 시각), 기준 사건에서 분 단위 상대시간을 구분.
- 검토자가 사건 A가 사건 B보다 **실제로 먼저 발생했다고 명시적으로 주장**한 경우, 저장된 선후관계의 추이성·상대시간·절대시간을 근거로 검사. **원고에 먼저 서술된 사건이 먼저 발생했다고 가정하지 않음**(회상 등 고려).
- 검사 결과 유형:
  - `TIME_CONFLICT`: 주장 날짜·시간과 Timeline 상의 확인 가능한 시간 구간이 겹치지 않음.
  - `TIME_UNVERIFIABLE`: Timeline에 비교 가능한 절대시간이 없음.
  - `ORDER_CONFLICT`: 명시된 순서가 저장된 선후관계 또는 확실한 시간 선후와 충돌함.
  - `ORDER_UNVERIFIABLE`: 같은 날처럼 시간 구간이 겹치거나 순서 정보가 없어 판별할 수 없음.
- `check_episode_timeline`은 65단계 `EpisodeDraftPreview`의 SHA-256 및 미승인 상태를 확인한 후 동일하게 검사.

## 무결성 및 비파괴성

- 다른 작품의 사건·누락된 사건, 중복된 주장, 잘못된 위치·증거 구간·시간 형식은 안전하게 거부.
- 기존 `EventTimelineStore.audit`를 먼저 실행하여 순환 참조·시간 제약 오류를 감지. 작품 revision 변경 및 잘못된 기대 revision을 거부.
- 보고서에는 원고 문장이나 사건 제목을 저장하지 않고 **사건 ID·근거 위치·SHA-256·유형**만 담음. 지문은 암호화나 비밀 보호가 아님.
- `persisted=False`, `publication_approved=False`, `status=REQUIRES_HUMAN_REVIEW_NOT_FULL_QC`로 반환. DB 수정, 자동 수정, 승인 또는 출판을 수행하지 않음.
- 참조소설 원문을 조회·복사하지 않으며 외부 서버·GitHub·클라우드 AI API에 접근하지 않음.

## 예시

```python
from ai_novel_factory.database.event_timeline import EventTimelineStore
from ai_novel_factory.timeline_checker import TimelineMention, TimelineOrderClaim, check_timeline

text = '주인공은 다음 날 그 사건을 떠올렸다.'
span = '그 사건'
start = text.index(span)
mention = TimelineMention(event_id, start, start + len(span), span,
                          claimed_when='2026-10-02')
report = check_timeline(store, project_id, 3, text, (mention,))
# report.findings 의 유형과 근거 위치를 검토. 최종 원고 승인 아님.
```

## 테스트

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage73*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

- Windows에서 직접 GUI/EXE 실행: **미검증**.
- 사건·날짜 주장과 시간적 관계는 **검토자가 명시적으로 표시**해야 함. 자유서술 NLP 시간·사건 추출 및 회상 자동 판별은 미구현.
- 상대시간이 날짜만 지정된 사건에 연결되면 해당 시간은 여전히 시간 구간이므로, 결과가 불확실할 수 있음.
- 읽기 작업 전후 revision 비교는 DB 트랜잭션 수준의 동시성 직렬화 보증이 아님.
- 과거 테스트에서 알려진 SQLite 연결 미종료 ResourceWarning이 재현됨.
