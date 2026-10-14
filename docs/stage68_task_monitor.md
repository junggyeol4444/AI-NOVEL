# 68/100 — 집필 진행률·일시정지·취소 화면

## 원본 범위와 직접 요구사항
- 원본 100단계 로드맵 68단계: **집필 진행률·일시정지·취소 화면**.
- `docs/requirements.md`의 **ANF-REQ-004**: 작업 진행 상태·일시정지·취소, 화면 반영 및 취소 후 재개 규칙.
- 입력 기준: `AI_Novel_Factory_stage67_local.zip`, 351개 파일. 원본 66/67단계 실행 기록과 소스 확인.
- 오프라인·로컬 PC, Novel Bible 우선, 참고작 원문 비복제, 출판 전 사용자 승인 원칙 유지.

## 구현
- `src/ai_novel_factory/local_task_queue.py`: 기존 `local_tasks` 스키마는 유지. `task_controls`를 별도 추가해 제어 요청, 0~100 진행률, 작업 단계, 실제 중지 확인 상태를 보존. 작업 대기 시 일시정지 상태는 선점에서 제외. 실행 중 취소 요청은 작업 완료 처리 시에도 원자적으로 **중단** 상태를 우선 적용. 실행 중 모니터를 열어도 `recover_running=False`로 작업이 임의 INTERRUPTED 처리되지 않도록 처리.
- `src/ai_novel_factory/task_monitor.py`: 작업 조회·작품별 목록·일시정지/재개/취소 요청, **안전 지점에서만** 제어 요청을 처리하는 `checkpoint` 및 선택적 `run_one_controlled`/`run_one_controlled_async` 호출.
- `src/ai_novel_factory/desktop/task_monitor_widget.py`: 로컬 SQLite 큐 파일을 사용자가 직접 선택한 경우에만 읽기/제어. 진행 상태, 단계, 진행률, 새로고침, 일시정지, 재개, 취소 표시. 주기적 폴링은 로컬 SQLite만 조회. 취소 전에 사용자 확인. 미선택 DB를 자동 생성하거나 작업 실행하지 않음.
- `src/ai_novel_factory/desktop/app.py`: 기존 12개 메뉴 항목을 변경하지 않고 **Episodes**의 별도 탭에 작업 모니터를 연결.
- `tests/test_stage68_task_monitor.py`: 이전 SQLite 데이터 호환, 진행률 단조 증가, 작업 중지/재개, 경합, 재시작, 다른 작품 필터링, 비밀정보 저장 방지, 네트워크 없는 호출, 선택적 GUI 스모크 테스트.

## 작업 상태와 제한사항
- `QUEUED` 대기 / `RUNNING` 실행 / `PAUSE_REQUESTED` 요청 접수 / `PAUSED` 일시정지 확인 / `CANCEL_REQUESTED` 취소 요청 접수 / `CANCELLED` 취소 완료 / `COMPLETED` 핸들러 처리 완료 / `FAILED` 실패 / `INTERRUPTED` 재시작 등 중단.
- **강제 프로세스 종료는 구현하지 않음.** 기존 67단계의 일반 `run_one` 핸들러는 실행 중 `checkpoint` 호출이 없으므로 진행률·즉시 일시정지를 보장하지 않는다. 새 `run_one_controlled`도 호출자 핸들러가 적절한 안전 지점에서 `checkpoint`를 호출해야 실시간 요청이 처리된다. 취소 요청은 그 사이 `CANCEL_REQUESTED`로 표시되고, 종료 직전의 취소도 성공 상태로 잘못 기록되지 않도록 방어한다.
- `PAUSED` 상태에서 앱을 종료하면 해당 실행이 보존되는 게 아니라, 다음 정상 재시작에서 `INTERRUPTED`로 표시된다. 이어쓰기 체크포인트·자동 재시도는 미구현(69단계 이후 작업).
- 성공 시 100%는 **작업 핸들러 실행이 끝났음**을 의미하며 품질검사 통과, 원고 확정·저장, 출판 승인 또는 실제 AI 생성 성공을 의미하지 않는다.
- 큐 DB에는 작업 ID, 작품 ID, 회차 번호, 작업 상태, 비식별 오류코드, 진행률·단계만 저장하며 원고·프롬프트는 저장하지 않는다.
- UI 조작은 **PySide6 설치가 필요**하고 실제 GUI 시험은 현재 Linux 환경에서 PySide6 미설치로 3건 건너뜀. Windows EXE 빌드·동작은 미검증. 신규 기능은 로컬 SQLite 기준이며 실제 Redis/Celery와 작업상태 동기화는 지원하지 않는다.
- SQLite 파일을 직접 조작하는 별도 프로세스와 스키마 사용에 대한 일반적인 보안 경합·권한 보호는 신뢰 가능한 사용자 로컬 폴더에 의존한다. 절대적인 실시간 강제 정지를 주장하지 않는다.

## 사용 예
```python
from pathlib import Path
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.task_monitor import TaskMonitor

queue = LocalTaskQueue(Path('existing_dir') / 'tasks.sqlite3')
monitor = TaskMonitor(queue)
queue.enqueue('novel-1', 1, task_id='job-1')

def handler(project_id, episode_number, checkpoint):
    checkpoint(25, 'PLANNING')
    # 실제 Writer 실행은 호출자가 안전하게 구성하고 검수 단계까지 제어해야 함.
    checkpoint(75, 'CHECKING')
    return True  # 예시 전용: 실제 집필/검수 성공을 의미하지 않음

thread = monitor.run_one_controlled_async(handler)  # 명시적 시작만 허용
thread.join()
print(monitor.get('job-1'))
```

## 테스트
`PYTHONPATH=src python -m unittest discover -s tests -v`

테스트 상세 출력: `docs/stage68_full_stdout.txt`, `docs/stage68_full_stderr.txt` 및 `docs/stage68_test_results.json`, `docs/stage68_verification_log.txt`. Python 3.13 Linux 실행에 한정. 이전 SQLite 연결 `ResourceWarning` 잔존.
