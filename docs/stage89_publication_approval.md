# Stage 89 — 출판 전 사용자 검수·승인 게이트 (ANF-REQ-067)

**공식 범위:** 89/100, `docs/requirements.md`의 ANF-REQ-067. 원본 기획안 TXT 첨부는 이번 실행에서 직접 확인할 수 없었으므로 **미확인**이다. 사용자 제공 100단계 로드맵 및 누적 요구사항을 따른다.

## 완료 기준과 실제 구현

`ai_novel_factory.publication_approval.PublicationApprovalStore`는 **동일한 로컬 Novel Bible SQLite**에서 다음을 수행한다.

1. 88단계의 미해결 복선·갈등·시간선·완결 회차 검사를 최신 상태로 재실행한다. 세 검토 범위의 명시적 확인이 모두 필요하다.
2. 83단계 `ManuscriptVersionStore`의 각 회차 **최신 FINAL 후보**와 EpisodeStore 원고 내용·버전을 대조한다. 중간에 다른 경로로 수정된 원고는 거절한다.
3. 참고작이 없는 경우 **실제로 전달된 ReferenceCatalog가 비어 있음**과 `no_references_confirmed=True`를 모두 요구한다. 참고작이 있으면 카탈로그 전체와 검사 입력 집합을 대조하고, 각 회차의 현재 원고에 대해 78단계 유사성 검사를 **다시 실행**, 기존에 기록된 `clear` 영수증과 대조한다. 검사 범위가 불충분하거나 누락되면 승인 준비를 차단한다.
4. 원고·설정·완결 검사·참고작 유사성 근거의 SHA-256을 결합한 검토 스냅샷을 생성한다. 원고와 참고작 원문은 **승인 테이블에 저장하지 않는다**. 원고는 기존 Episode/Version DB에 존재한다.
5. `begin_review`는 `PENDING` 요청과 1회용 무작위 확인 코드를 만든다. **사용자가 직접 명시한** `APPROVE <request_id> <code>` 또는 `REJECT <request_id> <code>`가 일치할 때만 결정한다. 확인 코드 자체는 DB에 저장하지 않고 SHA-256만 기록하며 처리 후 무효화한다.
6. `APPROVED` 이후에도 `require_current_publication_approval`은 현재 원고·설정·참고작 검사·완결 근거를 재확인한다. 변경·철회·거절·새 검토 요청 시 게이트를 차단한다. `REVOKE <request_id>`로 로컬 승인 철회 가능. 요청·결정·철회 이벤트를 식별자/시각만 기록한다.
7. `PublicationGateReceipt`는 **로컬 검토 증빙**이며 외부 게시나 원고 확정 자체를 수행하지 않는다. `identity_authenticated=False`, `publication_executed=False`를 명시한다.

## 오프라인 호출 예시 (참고작이 없는 작품)

```python
from ai_novel_factory.publication_approval import PublicationApprovalStore, PublicationReviewEvidence
from ai_novel_factory.database.reference_catalog import ReferenceCatalog

with PublicationApprovalStore('novel.db') as store, ReferenceCatalog('reference.db') as catalog:
    report = store.inspect_ending(project_id, ending_episode,
        foreshadow_inventory_reviewed=True,
        conflict_inventory_reviewed=True,
        timeline_inventory_reviewed=True)
    evidence = PublicationReviewEvidence(
        ending_report=report, reference_catalog=catalog, similarity_store=None,
        no_references_confirmed=True,
        foreshadow_inventory_reviewed=True,
        conflict_inventory_reviewed=True,
        timeline_inventory_reviewed=True)
    ticket = store.begin_review(project_id, evidence)
    # UI는 검토 내용과 요청 ID를 사용자에게 표시하고, 사용자가 확인 코드를 직접 입력해야 한다.
    # 여기서는 호출 계약만 설명한다. 사용자가 입력하기 전에는 decide를 호출하지 않는다.
    # store.decide(project_id, ticket.request.request_id, evidence,
    #     decision='APPROVE', confirmation=user_typed_confirmation)
    # 이후에도 require_current_publication_approval로 현재 상태를 다시 확인한다.
```

참고작이 등록된 경우 `ReferenceMaterial`과 회차별 `EpisodeSimilarityInput`, `ReferenceSimilarityReviewStore`의 기존 영수증을 함께 전달해야 한다. 예시는 승인 명령을 **자동 실행하지 않는다**.

## 제한 및 보안 경계

- **신원 인증 미구현:** 확인 코드는 명시적 로컬 동작을 유도할 뿐 실제 사용자의 신원을 인증하지 않는다. 코드를 전달받은 다른 로컬 프로세스도 승인할 수 있다. 사용자 계정·OS 인증·서명·불변 감사로그는 구현되지 않았다.
- **출판 어댑터 미연결:** 95단계 Publisher Adapter나 기존 모든 외부 호출 경로에 이 게이트를 강제 연결하지 않았다. 따라서 이 모듈만으로 시스템 전반의 외부 업로드 차단을 보증하지 않는다. 실제 외부 게시·원고 확정·업로드는 이 단계에서 실행하지 않는다.
- **참고작 목록 경계:** 전달된 `ReferenceCatalog`를 현재 작품의 전체 참고작 집합으로 취급한다. 작품별 등록 집합을 별도 인증하지 못하므로 다른/빈 카탈로그를 바꿔 전달하면 누락을 독립적으로 발견하지 못한다. 신뢰 가능한 로컬 UI/DB 연결이 필요하다.
- **비동기 변경 경계:** SQLite 작품 DB는 원자적 스냅샷으로 읽지만, 별도 참고작 카탈로그와 검사 영수증 DB는 같은 트랜잭션으로 잠그지 못한다. 승인 이후 매 사용 시 다시 검증하나 외부 게시까지 원자적으로 보증하지는 않는다.
- **품질 판단 한계:** 78단계 유사성 검사는 표면적/주석 기반 검사의 확인된 범위에 한정한다. 완전한 저작권·의미 유사성 판정이 아니다. 88단계도 구조화 복선·갈등·시간선 데이터만 확인한다.
- **데이터 보안:** SQLite 파일은 로컬 저장이며 디스크 암호화는 없다. 기존 원고 DB에 본문이 저장되어 있으므로 전체 DB 덤프가 비밀이라고 주장하지 않는다. 승인 테이블은 원고·참고작 문장·확인 코드 평문을 별도로 저장하지 않는다.
- **미검증:** Windows EXE/GUI, 실제 LLM, Redis/Celery/pgvector, 출판 플랫폼, 사용자 계정 인증.

## 재현 가능한 검증

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage89_publication_approval.py' -v
python scripts/stage89_partitioned_regression.py --prefix docs/stage89_worktree --start 1 --end 8
python scripts/stage89_partitioned_regression.py --prefix docs/stage89_worktree --aggregate
```

누적 ZIP은 이전 88단계 1,182개 항목의 보존과 CRC를 확인하고 별도 새 폴더에 압축 해제하여 **동일 전체 회귀 테스트를 재실행**한다. 그룹별 명령/stdout/stderr/종료코드와 중복 없는 테스트 모듈 범위는 별도 검증 JSON 및 로그에 기록한다.
