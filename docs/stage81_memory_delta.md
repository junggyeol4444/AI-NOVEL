# 81/100 — 확정 원고 Memory Delta 검토 목록 (ANF-REQ-057)

## 근거 및 한계

공식 로드맵 81단계: 확정 원고에서 Memory Delta 자동 추출. 누적 `docs/requirements.md`의 **ANF-REQ-057**: “확정본에서 새 사실·관계·복선을 추출한다. 추출 내역을 검토 가능한 변경 목록으로 저장한다.” 원본 기획안 TXT 파일은 이번 실행에서 실제로 접근할 수 없었으므로 사용자 메시지의 기획 요약·로드맵과 80단계 ZIP을 근거로 했다.

기존 49단계 `EpisodeStore.final_text`는 **출판 승인이나 사용자 승인 증빙이 아니다.** 89단계 승인 워크플로는 아직 구현되지 않았다. 이번 API는 호출자가 명시적으로 전달한 `FinalTextAttestation`(작품·회차·DB revision·final_text SHA-256·승인 참조 ID·`explicitly_approved_by_user=True`)이 일치하는 경우에만 동작한다. 이는 **호출자 주장**일 뿐, 실제 사용자 신원이나 승인 기록의 진위가 암호학적으로 검증되었다는 뜻이 아니다. 자동으로 확정하거나 출판하지 않는다.

## 추출 방식

로컬 원고의 `final_text`에 **작성자/검토자가 명시적으로 삽입한 구조화 주석**만 추출한다. 자유형 자연어에서 새 사실·관계·복선을 LLM이나 규칙으로 추론하지 않는다. 각 주석은 본문에 정확히 `[[ANF_MEMORY|...]]` 형태로 들어가야 한다.

- `[[ANF_MEMORY|FACT|인물또는대상ID|새 사실 설명]]`
- `[[ANF_MEMORY|RELATIONSHIP|인물ID1|인물ID2|관계 상태]]`
- `[[ANF_MEMORY|FORESHADOW|복선ID|REVISIT|사건 설명]]` (허용 행동: INSTALL/REVISIT/RESOLVE/ABANDON)

구분자 `|`, 개행, 중첩 마커는 필드 안에서 지원하지 않는다. 표시되지 않은 일반 문장은 추출되지 않으며, 잘못 닫힌/잘못된 주석은 실패로 처리한다. 최대 200개, 각 필드 최대 1,024자. 모든 항목에 본문 문자 위치·주석 SHA-256·고유 변경 ID를 붙이고 `PENDING_HUMAN_REVIEW` 상태로 만든다. 본문 자체를 보고서에 복사하지 않는다.

## 사용 예시

```python
from hashlib import sha256
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.memory_delta import (
    FinalTextAttestation, MemoryDeltaReviewStore, extract_memory_delta,
)

# store는 기존 49단계 EpisodeStore; final_text는 별도 사용자 검토를 거쳐 저장되어야 함.
episode = store.get_episode(project_id, episode_number)
evidence = FinalTextAttestation(
    project_id, episode_number, episode.revision,
    sha256(episode.final_text.encode('utf-8')).hexdigest(),
    'explicit-approval-ref-001', True,
)
delta = extract_memory_delta(store, evidence)
reviews = MemoryDeltaReviewStore('local_review_only.sqlite3')
try:
    reviews.save(store, evidence, delta)
    pending = reviews.list_review(store, evidence)
finally:
    reviews.close()
# pending의 fields는 검토용 민감 데이터; 사용자 확인 없이 외부 전송 금지.
```

별도 SQLite `memory_delta_reviews` 테이블은 **검토 목록만 저장**한다. Novel Bible Character/World/Relationship/Foreshadowing DB는 수정하지 않는다(82단계 적용 예정). 동일 검토 목록 재저장은 중복 생성하지 않으며, 저장된 목록 변조·원고 해시/회차 버전 변경·누락을 차단한다. 원고 수정 후 이전 revision의 항목은 자동으로 최신 항목으로 간주하지 않는다. 목록 조회는 저장 원고와 재추출하여 대조한다. 원고·주석 텍스트는 로컬 SQLite 검토 DB에 저장되므로 저장소 접근 통제/암호화는 운영자의 책임이다.

## 미구현

완전 자동 자연어 정보 추출, 사실의 의미 검증, 기존 Novel Bible과의 의미 충돌 해결, 사용자 승인 진위 검증, 변경 승인/거절 UI, 정식 canon DB 반영(82단계), Windows EXE 및 GUI 실행, 실제 LLM/Redis/Celery/pgvector 연동은 포함하지 않는다. 원격 저장소·GitHub·클라우드 AI API를 사용하지 않는다.
