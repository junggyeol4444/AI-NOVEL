# 85/100 — 자동 집필 Scheduler/예약 (ANF-REQ-050)

## 근거와 구현 범위

기존 `docs/requirements.md`의 **ANF-REQ-050**(자동 집필 일정 및 작업 실행 이력 관리, 설정 시간의 실행·실패·재시도 기록 조회)과 사용자가 제공한 공식 100단계 로드맵에 맞추었다. 원본 기획안 `붙여넣은 텍스트(1)(7)(1).txt`는 이번 실행에서 직접 접근할 수 없어 원문 검증을 하지 못했다. 기존 84단계 ZIP, 단계별 검증 로그, 요구사항을 확인했다.

`src/ai_novel_factory/writing_scheduler.py`의 `LocalWritingScheduler`는 기존 67단계 `LocalTaskQueue`의 **동일 로컬 SQLite DB**에 예약, 실행 기록, 이벤트 이력을 추가한다. `ONCE`, `HOURLY`, `DAILY` UTC 시각을 지원하며, 호출자가 명시적으로 `tick(now=..., dispatch_authorized=True)`를 실행해야 기한이 된 **초고 작업 메타데이터만** 큐에 넣는다. DB 트랜잭션 안에서 예약 진행/작업 큐/실행 로그를 원자적으로 기록하여 재실행·다중 호출 중복을 방지한다. 같은 작품·회차의 QUEUED/RUNNING/FAILED/INTERRUPTED 작업이 있으면 `SKIPPED_BUSY`로 기록하고 중복 작업을 생성하지 않는다. PC가 꺼진 동안 놓친 반복 슬롯은 소급 집필하지 않고 누락 개수만 기록하며, 재가동 후 1회 작업만 준비한다.

실제 실행은 **별도의 명시적 승인** `execute_run(run_id, handler=..., local_execution_approved=True, now=...)`을 통해서만 가능하다. 외부 제공자, 사용자 원고, API, 출판은 자동 호출하지 않는다. 콜백은 호출자가 공급하는 로컬 집필 함수이며 호출자가 Novel Bible 우선, 품질 검사, 권한·원고 상태를 검증해야 한다. 콜백 반환값이 리터럴 `True`일 때만 큐 작업 성공으로 기록한다. 실패 예외 문자열은 저장하지 않고 안전한 코드 `HANDLER_EXCEPTION` 등으로 기록한다. `refresh_run`은 다른 기존 큐 워커가 처리한 결과를 관찰하고 이력을 남긴다.

실패 재시도는 `retry_run(..., retry_authorized=True)`를 별도로 호출해야 하며 69단계와 동일한 `RETRYABLE_CODES`·최대 시도 횟수 정책만 허용한다. 상태 변화는 `writing_schedule_events`에서 시간·시도 횟수·오류 코드로 조회할 수 있다. 승인 없는 재시도, 이미 완료한 작업 재실행, 무제한 재시도는 차단한다. 반복 예약은 **명시된 동일 회차**에 대한 작업 준비이며 다음 회차를 추측하지 않는다. 다음 회차 생성은 84단계의 별도 확정 검증 흐름에서 진행해야 한다.

## 간단한 로컬 사용 예

```python
from datetime import datetime, timezone
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.writing_scheduler import LocalWritingScheduler

queue = LocalTaskQueue('jobs.sqlite')  # 부모 폴더가 미리 존재해야 함
scheduler = LocalWritingScheduler(queue)
schedule = scheduler.create_schedule(
    'project-1', 2, start_at=datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc),
    frequency='HOURLY', max_occurrences=3)
# 실행 중인 로컬 애플리케이션에서 명시적으로 호출해야 함:
runs = scheduler.tick(now=datetime.now(timezone.utc).replace(microsecond=0),
                      dispatch_authorized=True)
# 실제 로컬 집필은 handler와 별도 명시 허가가 있을 때만 수행.
# scheduler.execute_run(runs[0].run_id, handler=guarded_local_draft,
#                       local_execution_approved=True,
#                       now=datetime.now(timezone.utc).replace(microsecond=0))
```

## 보안 및 한계

- 예약 등록/`tick`은 백그라운드 데몬이 아니다. **Windows 작업 스케줄러 연동, PC 자동 켜짐/복구, 실제 Windows GUI 예약 화면, 예약 시각의 무인 자동 실행은 미구현·미검증**이다. 실행 프로세스가 꺼져 있으면 작업이 실행되지 않는다.
- `execute_run`의 콜백은 호출자가 제공한다. 본 모듈이 임의의 콜백의 네트워크/출판 부작용을 기술적으로 샌드박싱하지는 못하므로 신뢰할 수 있는 로컬 콜백만 전달해야 한다. 본 모듈 자체는 원고 확정·승인·출판·외부 API 호출을 하지 않는다.
- 84단계 `confirmation_asserted`는 독립 인증이 아니며 89단계 승인 흐름 미구현. `QUEUED`는 집필 완료가 아니며, `COMPLETED`도 **초고 작업 핸들러의 성공 반환**일 뿐 원고 품질/승인/출판이 아니다.
- 시각은 timezone-aware datetime만 받으며 UTC로 정규화한다. `HOURLY`/`DAILY`는 3600/86400초 간격이므로 지역 일광절약시간제에 따른 '매일 현지 시각' 조정은 지원하지 않는다.
- 원고·프롬프트·키는 예약/이벤트 DB에 저장하지 않는다. SQLite 파일의 암호화나 악의적 관리자에 대한 무결성 보호는 없다.
- 테스트는 Linux Python 3.13.5 기준. Windows EXE/GUI, 실제 로컬 LLM, Redis/Celery/pgvector 실연동, OS 예약 서비스는 검증하지 않았다. GitHub·원격 저장소·클라우드 AI API 사용 없음.
