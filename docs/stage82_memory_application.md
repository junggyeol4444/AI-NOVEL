# 82/100 — 승인된 Memory Delta의 Novel Bible 반영 (ANF-REQ-058)

## 요구사항과 근거

공식 로드맵 82단계: **확정된 기억 변경 사항을 Character·World·Timeline 등 DB에 반영**. 기존 `docs/requirements.md`의 `ANF-REQ-058`: **동일 변경 재적용 시 중복 기록이 생기지 않는다.** 기준 누적본은 81단계 ZIP이며 원본 기획안 TXT는 현재 대화의 실제 접근 가능한 파일 목록에서 확인되지 않았다. 따라서 사용자가 제공한 기획 요약·100단계 로드맵과 기존 요구사항을 기준으로 한다.

## 동작과 승인 범위

`memory_application.MemoryCanonStore`는 기존 42/44/45/46/47단계의 로컬 Novel Bible 스키마를 같은 SQLite 연결로 초기화한다. `apply(episode_store, review_store, evidence, approvals)`는 다음 조건을 **모두** 만족해야 한다.

1. 81단계 `EpisodeStore.final_text`의 작품·회차·revision·SHA-256 및 **호출자가 제출한** 사용자 승인 주장이 일치한다.
2. 81단계 별도 SQLite 검토 목록을 현재 원고에서 재추출한 결과와 완전히 대조한다. 잘못된/누락된 검토 기록은 거부한다.
3. 변경 ID별로 사용자가 명시적으로 승인했다고 주장하는 `MemoryApproval`(검토 참조 ID, `explicitly_approved_by_user=True`, 대상 종류·ID, 필요 시 대상 revision)을 제공한다. 미승인 항목은 건너뛴다. 동일 승인 항목은 중복 전달할 수 없다.
4. `FACT`의 대상은 기존 Character/World/Timeline 항목 ID와 동일해야 하며 현재 revision이 일치해야 한다. 새 사실은 기존 설정의 이름·성격·목표·설명·사건 시간을 덮어쓰지 않고 `bible_memory_facts`에 **기존 정규 DB 항목과 외래키로 연결**하여 저장한다. 즉 자유형 자연어를 의미적으로 병합하거나 기존 사실과 충돌 해결하지 않는다.
5. `RELATIONSHIP`은 존재하는 두 Character ID에 대해 기존 `bible_relationship_events`에 해당 회차 관계 사건을 새로 삽입한다. 같은 회차·같은 쌍의 기존 수동 기록은 절대 덮어쓰지 않는다.
6. `FORESHADOW`는 기존 `bible_foreshadow_threads`/`bible_foreshadow_events`에 상태 전이 검사를 거쳐 삽입한다. `INSTALL`은 새 thread ID와 검토자가 지정한 제목이 필요하며, `REVISIT/RESOLVE/ABANDON`은 기존 thread의 정확한 revision이 필요하다. 종료 상태에서 다시 전개하거나 사건 순서를 어기는 변경은 거부한다.

동일한 변경 ID를 동일 승인·원고 근거로 다시 적용하면 `already_applied`만 증가하고 **canon 기록·project revision이 증가하지 않는다.** 다른 승인/대상으로 재적용하거나 저장 기록의 지문이 변경되면 실패한다. 적용 이력은 `bible_memory_applications`에 기록한다. 각 호출의 새 적용은 **동일 SQLite 트랜잭션**에 묶여 중간 오류 시 전체 롤백한다. 단, 원고·검토 DB는 별도 SQLite 연결일 수 있으므로 여러 파일에 걸친 원자적 커밋/동시 편집 잠금을 보장하지 않는다.

## 사용 예시

```python
from ai_novel_factory.memory_application import MemoryCanonStore, MemoryApproval

# episode_store: 기존 EpisodeStore, review_store: 기존 MemoryDeltaReviewStore
# evidence: 81단계 FinalTextAttestation; 해당 작품은 동일 Novel Bible SQLite에 존재해야 함.
canon = MemoryCanonStore('my_local_novel_bible.sqlite3')
try:
    candidate = review_store.list_review(episode_store, evidence)[0]
    # 예시: candidate.kind == 'FACT', candidate.fields[0]은 기존 인물 ID
    character = canon.get_character(evidence.project_id, candidate.fields[0])
    decision = MemoryApproval(
        change_id=candidate.change_id,
        target_kind='character',
        target_id=character.character_id,
        reviewer_reference='manual-review-123',
        explicitly_approved_by_user=True,
        expected_target_revision=character.revision,
    )
    result = canon.apply(episode_store, review_store, evidence, (decision,))
    facts = canon.list_facts(evidence.project_id, 'character', character.character_id)
finally:
    canon.close()
```

**주의:** `FinalTextAttestation`과 `MemoryApproval`의 승인 여부는 호출자가 입력하는 주장일 뿐 **사용자 신원/서명의 독립 인증이 아니다.** 89단계 사용자 승인 워크플로와의 연동은 미구현이다. 적용한 기억은 Novel Bible의 후속 집필 컨텍스트에서 별도 조회·선택하여 사용해야 하며, 모든 기존 컨텍스트 API에 자동 주입되지는 않는다. 원고 확정·출판 승인·플랫폼 업로드는 수행하지 않는다. 참고작 원문을 기억에 자동 수집하지 않는다.

## 검증 및 한계

- `tests/test_stage82_memory_application.py`: 승인/거부·대상 버전·세 종류의 FACT 연결·관계/복선 상태 전이·idempotent replay·위변조·원고 변경·원자적 롤백·재개 검증.
- `scripts/stage82_partitioned_regression.py`: 95개 테스트 모듈을 중복 없는 8개 그룹으로 나눠 전체 실행·로그 수집, 재현 가능한 그룹별 실행/합산.
- 단위 테스트는 SQLite 로컬 동작을 검증한다. 실제 승인 인증, 자연어 의미 충돌 해결, LLM 정보 추출, 실제 Windows EXE/GUI, Redis/Celery·pgvector 실연동은 검증하지 않았다.
- 기존 SQLite 연결 `ResourceWarning`이 일부 테스트에서 발생한다. 원고·민감 설정은 로컬 DB에 저장되며 암호화는 별도 운영 과제다. GitHub·원격 저장소·클라우드 AI API는 사용하지 않는다.
