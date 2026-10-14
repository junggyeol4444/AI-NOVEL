# 90/100 — 작업 로그·비용·오류 모니터링 UI (ANF-REQ-069)

## 원본 근거와 완료 기준

공식 100단계 로드맵 **90단계: 작업 로그·비용·오류 모니터링 UI**.
`docs/requirements.md`의 **ANF-REQ-069**: "작업 로그·오류·비용을 추적한다. 작업 ID로 실행 내역과 오류 원인을 조회할 수 있다."
기준 ZIP: `AI_Novel_Factory_stage89_local.zip` (1,241개 파일; CRC 정상, 기존 89단계 2,906 통과/17 건너뜀/실패 0 기록). 원본 기획안 `붙여넣은 텍스트(1)(7)(1).txt`는 현재 첨부에서 접근하지 못했으므로 **원본 미확인**. 사용자 제공 100단계 로드맵과 누적 요구사항에만 근거하여 작성.

## 구현 내용

- `src/ai_novel_factory/operations_monitor.py`: **기존** 로컬 SQLite 작업큐를 `mode=ro`로 열어 `task_id`·`project_id`·회차·상태·시도·진행률·오류코드 등을 조회. 예약 실행 데이터가 있으면 85단계 `writing_schedule_runs`도 조회. 새 DB 생성, 작업 시작/재시도 없음. 기존 `TaskMonitor` 상태와 SQLite를 공유.
- `OperationsLedger`: 호출자가 **명시적으로 제출한** STARTED/CHECKPOINT/RETRIED/COMPLETED/FAILED/INTERRUPTED 실행 이벤트를 로컬 `operation_events` 테이블에 기록. 작업이 이미 존재해야 하며 원고/프롬프트/본문/토큰 문자열/API키/예외 메시지를 받지 않음. 예외 대신 허용된 비식별 오류 코드만 저장.
- 시간(ms)·입출력 토큰 수·금액 최소 단위(USD cent, KRW 원)를 숫자형으로 검사. 비용 출처 `UNKNOWN`, `ESTIMATED`, `REPORTED`를 구분하고 통화 혼합 집계 금지. **미보고 비용은 0원이라고 가정하지 않음.** 금액은 외부 모델/API 가격표를 자동 조회하지 않으며 호출자가 제공한 추정/보고 수치일 뿐 실제 청구액 또는 결제 확인이 아니다.
- 프로젝트별 필터 및 목록 200건 제한; 합계는 페이지 제한을 받지 않는 DB 전체 범위. 오류 코드가 등록된 안전 목록 밖이면 `UNKNOWN_ERROR`로 축약하여 UI에 임의 오류 메시지가 노출되지 않게 함.
- `src/ai_novel_factory/desktop/operations_monitor_widget.py`: PySide6 Episodes 탭 **「작업 로그·비용·오류」** 에서 사용자가 직접 선택한 **기존** DB의 작업·이벤트·예약 실행 이력, 보고/추정/미확인 비용 합계를 표시. 읽기 전용 모니터링. SQLite만 3초 간격 재조회하며 네트워크·집필·승인·출판 동작 없음.
- 기존 12개 사이드바 메뉴와 68단계 작업 제어 탭, 기존 데이터 스키마는 유지. UI 연결 때문에 `src/ai_novel_factory/desktop/app.py` 수정.

## 호출 예시

```python
from pathlib import Path
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.operations_monitor import OperationsLedger, OperationsReader

queue = LocalTaskQueue(Path('existing_dir/tasks.sqlite3'), recover_running=False)
# 이미 등록된 job ID를 사용하는 호출자가 기록을 명시적으로 제공할 때만 사용.
ledger = OperationsLedger(queue)
ledger.record('existing_job_id', 'CHECKPOINT', duration_ms=200,
              input_tokens=120, output_tokens=45,
              cost_kind='ESTIMATED', cost_minor=3, currency='USD')
reader = OperationsReader(queue.path)
print(reader.list_jobs(), reader.list_events(), reader.summary())
```

`cost_minor=3`은 **USD 0.03 추정액**을 뜻한다. 실제 모델 사용 대금이나 결제 기록으로 간주하지 않는다.

## 기술·보안 한계

- **자동 계측 전체 연동 아님:** 기존 모든 Writer/Orchestrator/Redis/Celery 호출을 가로채는 자동 집계가 아닌 선택적 기록 API와 큐/스케줄러 기존 상태 조회. 이전 실행의 사용량·비용은 알 수 없으며 비용 이벤트가 없는 작업은 비용을 계산할 수 없다.
- 오류 원인은 등록된 **분류 코드**로만 확인할 수 있고 Python traceback/원문 예외 내용·원인 분석은 제공하지 않는다. 이 제한은 민감정보 노출을 막기 위한 것이다.
- SQLite 파일에 대한 OS 파일 권한·디스크 암호화·사용자 계정 인증은 별도. 변조 불가능한 감사 로그는 구현하지 않음.
- PySide6 미설치 Linux 환경에서는 **GUI 코드는 구현했지만 실제 GUI/Windows 화면 검증은 건너뜀**. 네이티브 Windows EXE는 97/99단계까지 미검증.
- 실제 로컬 LLM 추론, 원격 API, Redis/Celery/pgvector 실연동, 사용자 승인/출판/외부 업로드 동작 없음.

## 실행/검증

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage90_operations_monitor.py' -v
python scripts/stage90_partitioned_regression.py --prefix docs/stage90_worktree --start 1 --end 8
python scripts/stage90_partitioned_regression.py --prefix docs/stage90_worktree --aggregate
```

테스트 실행 명령·stdout·stderr·종료코드와 8개 상호배타적 그룹 범위는 `docs/stage90_*` 결과에 보관. 최종 ZIP의 모든 항목 CRC, 89단계 파일 바이트 동일성(수정된 README 및 UI 연결 `desktop/app.py` 제외), 별도 추출 폴더의 전체 회귀 재실행을 확인한다.
