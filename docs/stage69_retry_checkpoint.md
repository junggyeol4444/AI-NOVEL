# 69/100 — API 실패 재시도 및 작업 체크포인트 (오프라인 부분 구현)

## 원본 요구사항

- 공식 100단계 로드맵 69단계: **API 실패 재시도 및 작업 체크포인트 저장**.
- `docs/requirements.md`의 **ANF-REQ-048**: "실패 작업을 재시도하고 마지막 성공 지점에서 재개한다." 완료 기준: "중간 실패 후 확정본을 중복 저장하지 않고 재개한다."
- 외부 서버/클라우드 AI API 사용 금지에 따라 실제 원격 API 호출은 하지 않음. 로컬 모델 또는 모의 장면 생성 단계에서 발생한 **명시적 일시 오류**만 재시도 대상으로 제한.

## 구현 범위

- `src/ai_novel_factory/local_task_queue.py`: `claim_identified(task_id, project_id, episode_number)` 추가. 원래 `claim()`의 FIFO·기존 API 유지. 지정한 작품/회차 이외의 작업을 잘못 점유하지 않음.
- `src/ai_novel_factory/retry_checkpoint.py`: `RetryCheckpointCoordinator` 클래스, `RetryableStepError`, `CheckpointRecord`, `RetryRun`.
  - 기존 SQLite `local_tasks` DB에 `retry_checkpoints` 메타데이터 테이블 추가. 작업 ID·단계 순서·단계명·문맥 SHA-256·산출물 SHA-256만 저장. **원고 본문·프롬프트·비밀키는 저장하지 않음**.
  - 작업 시작 시 해당 작품·회차·작업 ID를 원자적으로 선점. 신규 단계의 실행 직전 68단계 `TaskMonitor.checkpoint()`로 일시정지·취소에 협력. 취소가 검사된 경우 이후 단계를 실행하지 않음.
  - 중간에 `RetryableStepError`가 발생하면 오류 메시지를 저장하지 않고 `LOCAL_PROVIDER_TRANSIENT` 코드로 `FAILED`. 다른 오류는 `CHECKPOINT_EXECUTION_FAILED`로 실패 처리하며 자동 재시도 금지.
  - 호출자가 `retry_failed()`를 **명시적으로 호출해야만** 실패한 작업을 대기열로 복귀. 허용 오류만, 최대 시도 횟수(1~5, 기본 3) 이내에서 실행. 과거 승인/취소 상태에서 자동 실행하지 않음.
  - 재개 시 모든 이전 단계의 산출물을 호출자가 `restore` 콜백에서 다시 제공해야 함. SHA-256·단계명·순서·Novel Bible 포함 문맥 지문이 하나라도 다르면 **실행을 중단**. 검증 성공한 단계만 재사용하여 그 다음 단계부터 실행.
  - 완료 반환의 `approved`, `final_saved`, `published`는 항상 `False`. `FINAL_SAVE`, `PUBLISH`, `APPROVE`, `MEMORY_UPDATE` 단계는 거부.

## 실제 사용 계약 예시

```python
from hashlib import sha256
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.retry_checkpoint import RetryCheckpointCoordinator, RetryableStepError

queue = LocalTaskQueue('local_user_data/queue.sqlite3') # 디렉터리는 미리 준비
queue.enqueue('novel-1', 10, task_id='draft-10')
coordinator = RetryCheckpointCoordinator(queue)
canon_fingerprint = sha256(b'caller-verified-novel-bible-and-plan-version').hexdigest()

# 실제 앱에서는 신뢰할 수 있는 사용자 소유 저장소에서 산출물을 로드·검증한다.
artifacts = {}
def execute(name, index, previous):
    result = b'safe-offline-step-result'  # 설명용 예시, 실제 모델 아님
    artifacts[name] = result
    return result

def restore(name, index):
    return artifacts[name]

run = coordinator.run_task('draft-10', 'novel-1', 10, ('PLAN','SCENE_1','CHECK'),
                           context_sha256=canon_fingerprint,
                           execute=execute, restore=restore)
# 실패 상태가 LOCAL_PROVIDER_TRANSIENT인 경우에만 사용자가 명시적으로 재대기 요청:
# coordinator.retry_failed('draft-10', max_attempts=3)
# 그리고 동일한 run_task(...)을 다시 호출한다.
```

## 중요한 미완료 범위 및 검증 한계

1. **실제 HTTP/API 실패 판정·외부 통신은 없음.** 사용 금지 정책에 따라 테스트는 오프라인 콜백의 예외 분류로 수행. 로컬 실행 파일의 실제 일시 오류 식별은 애플리케이션이 안전하게 분류하여 `RetryableStepError`로 전달해야 함. `LocalExecutableProvider`가 반환하는 모든 오류를 자동으로 재시도하지 않음.
2. **완전 무인 자동 복구는 아님.** 장면 텍스트를 큐 DB에 저장하지 않으므로 재시작 후 호출자가 이전 산출물을 별도 안전한 장소에서 재제공해야 함. 없거나 변조되면 중단; 자동으로 과거 원고를 재생성해서 원본과 동일하다고 가정하지 않음.
3. **확정본 중복 저장 통합 검증 미완료.** 현재 Orchestrator는 초고만 메모리에 반환하고 원고 최종 확정 저장 기능은 없음. 본 모듈은 승인/최종 저장 단계의 실행 자체를 차단하여 이 구간의 중복 저장을 발생시키지 않지만, 향후 확정본 저장 서비스에 대한 원자적 멱등성 테스트를 대신하지 않음. 해당 통합 완료를 주장하지 않음.
4. `execute`는 **미확정 초고 생성 등 되풀이 가능한 단계**에만 사용해야 함. 임의 콜백 내부의 부작용/자체 네트워크 통신까지 차단하는 보안 샌드박스는 제공하지 않음.
5. 실제 PySide6 GUI, Windows EXE, Redis/Celery 서버, 실제 로컬 AI 추론 미검증. Linux Python 3.13 환경의 테스트이며 공식 메타데이터가 Python 3.12를 대상으로 함. SQLite 연결 관련 기존 ResourceWarning이 여전히 관찰됨.
6. 해시 검증은 아티팩트 불변성 검증이지 원고 품질·유사성·Novel Bible 의미적 정합성 인증이 아님. 체크포인트 DB 자체의 악의적 동시 변조·로컬 저장소 침입 방어는 별도의 보안 체계가 필요함.

## 테스트 실행 방법

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage69*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

통합 테스트는 `tests/test_stage69_retry_checkpoint.py`에 있으며, 재시작 재개, 작품별 격리, 누락·변조 아티팩트 거부, 기획 변경 시 거부, 원자적 재대기 요청, 취소·일시정지 연동, 시도 제한을 검증함. 검증 기록은 `docs/stage69_test_results.json`, `docs/stage69_verification_log.txt`, `docs/stage69_full_stdout.txt`, `docs/stage69_full_stderr.txt` 참조.
