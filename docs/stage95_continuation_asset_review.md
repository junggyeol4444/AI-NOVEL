# 95단계 추가 보강 — 제목·작가의 말·메타데이터 로컬 검토 결속

**ANF-REQ-066 공식 인수 기준: 여전히 미충족.** 95단계의 *부분 보강*이며 96단계는 구현하지 않았습니다.

## 기준과 원본 확인 상태

- 사용자 제공 2026-10-13 공식 로드맵 95단계(공식 API 기반 Publisher Adapter), 원본 기획안 TXT는 **직접 확인하지 못함**.
- 최신 이전 파일 `AI_Novel_Factory_stage95_local.zip`의 `docs/requirements.md` `ANF-REQ-066`: 공식 연동 규격을 확인한 대상에서 **테스트 환경 업로드 검증**이 인수 기준.
- **공식 API 규격·테스트 환경·플랫폼·자격증명은 확인하거나 사용하지 않았고, 외부 요청을 전혀 수행하지 않음.** 이 제약하에 최종 인수 완료 불가.

## 기존 95단계 보존

기존 `publisher_adapter.py`의 89단계 실제 로컬 승인·최종 원고 본문/94단계 해시 대조·모의 receipt/외부 업로드 완전 차단은 변경하지 않았습니다.

## 보강한 범위

신규 `publisher_asset_review.py`: 사용자 검토자에게 별도 일회용 확인 문구를 제시하는 **로컬 검토 기록 저장소**.

1. 95단계 `prepare_offline_publisher_plan`이 현재 89단계 승인을 재검증하며 94단계의 전체 원고·제목·작가의 말을 매니페스트 SHA에 결속합니다.
2. 92단계 `publication_metadata.json`이 정확한 UTF-8 구조·필수값을 만족하며 외부에서 제공한 파일 SHA-256과 같은지 검증합니다. 작품 ID를 현 프로젝트와 대조합니다.
3. 계획·승인 스냅샷·메타데이터 파일 SHA·모든 제목·작가의 말 SHA를 연결한 fingerprint를 **원문 없이** 별도 SQLite에 기록합니다.
4. 확인 코드의 SHA-256만 저장하고 사용자가 명시적으로 `CONFIRM-PUBLISHER-ASSETS <id> <code>`를 전달한 경우만 `REVIEWED`로 바꿉니다. `REJECT` 및 명시적 철회도 지원합니다.
5. `simulate_reviewed_offline_upload`는 사용 직전 재검사, 승인 취소·파일 변경·현재 데이터 불일치를 차단하며, 기존의 메모리 내 **비전송 모의 receipt**만 반환합니다.

이 보강은 **89단계의 승인이나 신원 인증을 대체하지 않으며, 출판 승인·게시 허용이나 공식 테스트 업로드가 아닙니다.** 현재 다른 모의 경로는 여전히 존재하나 실제 게시 경로는 모두 차단돼 있습니다.

## 호출 예 (모두 기존 검수 절차를 거친 로컬 자료만 사용)

```python
from hashlib import sha256
from ai_novel_factory.publisher_asset_review import PublisherAssetReviewStore, simulate_reviewed_offline_upload

# plan = prepare_offline_publisher_plan(...), approval_store/evidence 준비,
# metadata_path는 92단계 로컬 초안, directory는 94단계 초안
metadata_sha = sha256(metadata_path.read_bytes()).hexdigest()
with PublisherAssetReviewStore('/private/publisher_reviews.sqlite') as store:
    challenge = store.request_review(plan, directory, metadata_path,
        expected_metadata_sha256=metadata_sha, approval_store=approval_store, evidence=evidence)
    # 이 확인은 반드시 사람이 검수한 뒤 선택해야 함. 다음 호출을 자동 수행하지 말 것.
    store.decide(challenge.review_id, plan, directory, metadata_path,
        expected_metadata_sha256=metadata_sha, approval_store=approval_store, evidence=evidence,
        decision='REVIEW', confirmation=challenge.confirmation())
    receipt = simulate_reviewed_offline_upload(plan, directory, metadata_path,
        expected_metadata_sha256=metadata_sha, review_id=challenge.review_id,
        review_store=store, approval_store=approval_store, evidence=evidence)
    assert receipt.status == 'LOCAL_SIMULATION_NOT_UPLOADED'
```

## 한계

- `publication_metadata.json`의 내용은 92단계 사용자 초안이며, 사람이 실제 검토했다고 신뢰할 수 있는 추가 로컬 확인만 제공합니다. 공식 플랫폼 메타데이터 스키마 검증, 법적 독창성 검증, 신원 인증은 제공하지 않습니다.
- 공격자가 로컬 SQLite 및 코드를 모두 수정할 수 있으면 무결성을 보장하지 못합니다. SHA-256은 전자서명 아님. 파일 교체 경쟁조건/OS 레벨 접근통제를 완전히 해결하지 못합니다.
- PostgreSQL/pgvector, Redis/Celery, 실제 Windows EXE GUI, 로컬 LLM, 공식 API·플랫폼 테스트 업로드는 **미검증**. 누락된 조건을 성공으로 계산하지 않습니다.

## 재검증 명령

```bash
PYTHONPATH=src:tests python -m unittest -q test_stage95_publisher_asset_review
python scripts/stage95_continuation_partitioned_regression.py --prefix docs/stage95_continuation_worktree --start 1 --end 8
python scripts/stage95_continuation_partitioned_regression.py --prefix docs/stage95_continuation_worktree --aggregate
```
