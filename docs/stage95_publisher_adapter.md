# 95단계 — 공식 API Publisher Adapter (ANF-REQ-066): 오프라인 부분 구현

## 원본과 판단 기준

- 사용자 제공 2026-10-13 공식 100단계 로드맵의 **95단계**: 공식 API 기반 Publisher Adapter.
- 누적 ZIP `docs/requirements.md`의 **ANF-REQ-066**: "공식 API가 있는 플랫폼에 한해 Publisher Adapter를 지원한다" / 인수 기준 "공식 연동 규격을 확인한 대상에서 테스트 환경 업로드를 검증한다".
- 원본 기획안 `붙여넣은 텍스트(1)(7)(1).txt`는 이 실행에서 직접 열지 못했습니다. 사용자 제공 로드맵과 ZIP 내부 요구사항만 확인했습니다.
- **공식 API 제공 플랫폼·버전·규격·공식 테스트 서버를 확인하지 못했으므로, ANF-REQ-066의 공식 인수 기준은 미충족입니다.** 플랫폼명을 추정하거나 공식 연동 성공으로 주장하지 않습니다.

## 구현된 범위

`src/ai_novel_factory/publisher_adapter.py`에는 다음의 **오프라인 전용 계약**을 구현했습니다.

1. `PublisherAdapterContract`: 향후 공식 문서를 확인한 플랫폼 전용 어댑터가 준수해야 할 Python 인터페이스 경계. **현재 실제 플랫폼 구현체는 없음**.
2. `prepare_offline_publisher_plan`: 89단계의 **실제 로컬 DB 승인 상태**를 매번 재검증하고, 94단계 업로드 초안의 매니페스트 SHA-256, 전체 회차 범위와 각 회차 본문이 승인된 최신 FINAL 후보에 일치하는지 비교합니다. 문서 제목/작가의 말은 별도 출판자 검수가 필요합니다. 데이터는 원고 문장 대신 SHA-256과 길이·회차만 메모리에 유지합니다.
3. `LocalSandboxPublisherAdapter.simulate` / `simulate_offline_upload`: 메모리 내 모의 작업 수락만 반환. **스테이지 89 승인 철회나 변경 후에는 모의 실행도 차단합니다.** 외부 요청, 게시, 업로드, API 인증, 파일 쓰기, 원고 확정은 하지 않습니다.
4. `upload_to_real_platform`: 무조건 실패합니다. URL, 토큰, HTTP transport, 소켓 기능 자체를 갖추지 않습니다. 호출자 제공 실제 플랫폼 어댑터도 거부합니다.
5. 모든 결과는 `official_api_spec_verified=False`, `official_sandbox_upload_verified=False`, `publication_executed=False`이고, 유일한 영수증 상태는 `LOCAL_SIMULATION_NOT_UPLOADED`입니다.

### 사용 예 (승인 자동 생성 금지)

```python
from ai_novel_factory.publisher_adapter import prepare_offline_publisher_plan, simulate_offline_upload
# 사용자가 89단계에서 직접 검토/승인을 마친 기존 로컬 approval_store/evidence 필요.
# 94단계 초안의 이미 계산된 sha256을 신뢰 가능한 경로에서 전달해야 함.
plan = prepare_offline_publisher_plan(
    '/local/private/upload_drafts', expected_draft_sha256=known_manifest_sha256,
    project_id=project_id, approval_request_id=request_id,
    approval_store=approval_store, evidence=current_review_evidence)
receipt = simulate_offline_upload(
    plan, '/local/private/upload_drafts', approval_store=approval_store,
    evidence=current_review_evidence)
assert receipt.status == 'LOCAL_SIMULATION_NOT_UPLOADED'
```

## 보안 및 검증 한계

- 내부 Python 객체·입력은 신뢰할 수 있는 로컬 앱 호출자 수준입니다. 이 기능만으로 OS 사용자 인증, 로컬 악성 코드, 파일 교체 경쟁조건(TOCTOU), 전체 시스템의 다른 게시 경로 차단을 보증하지 않습니다.
- 메타데이터의 제목·소개·가격·작가의 말에 대해 **89단계 승인 스냅샷과 별도 동등성 검사하지 못합니다**. 현재 유효한 승인 원고 **본문**과 동일한 초안에 한해 모의 작업이 가능합니다. 실게시 구현에 앞서 메타데이터·작가의 말까지 확인해야 합니다.
- 89단계 사용자의 로컬 명시적 승인 과정도 신원 인증을 의미하지 않습니다. 78단계 유사성 검사가 저작권의 완전한 안전을 보장하지 않습니다.
- 오프라인 단위/통합 테스트는 **공식 플랫폼의 테스트 업로드가 아닙니다**. 공식 문서/서명·규격 검증, 승인된 시험 환경, API 키 연결, 예외·재시도·응답 상태 처리, 실제 업로드 검증은 모두 **미실시**입니다.
- 실제 Windows EXE/GUI, 실제 로컬 AI, PostgreSQL/pgvector 및 Redis/Celery 연동은 검증하지 않았습니다.
- 현재 산출물은 **95단계 부분 구현·모의 검증**입니다. 공식 인수 기준을 충족할 때까지 95단계를 완료 처리하거나 96단계로 자동 진입하지 않습니다.

## 재검증

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_stage95_publisher_adapter.py -v
python scripts/stage95_partitioned_regression.py --prefix docs/stage95_worktree --start 1 --end 8
python scripts/stage95_partitioned_regression.py --prefix docs/stage95_worktree --aggregate
```

그룹별 stdout/stderr/exit 및 coverage JSON, ZIP 보존·CRC와 별도 압축 해제 회귀 테스트 기록은 `docs/stage95_*` 및 외부 JSON에 포함됩니다. 모든 작업은 로컬입니다.
