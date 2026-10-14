# 67/100 — Redis·Celery 비동기 작업큐 연동: 오프라인 부분 구현

## 정확한 범위와 요구사항

- 공식 로드맵 67단계: **Redis·Celery 비동기 작업큐 연동**.
- `docs/requirements.md`에서 67단계로 직접 매핑한 ANF-REQ 항목 없음. 요구사항 ID를 임의 지정하지 않음.
- 외부 서버/클라우드 API 및 GitHub 사용 금지에 따라 로컬 SQLite 작업큐를 **실행·테스트 가능한 대체 백엔드**로 개발하고, Redis·Celery는 **루프백 전용 구성 어댑터**까지만 제공. 후자의 실제 작업 전송은 미검증이며 공식 단계의 완전한 Redis·Celery 연동이라고 주장하지 않음.

## 구현 파일

- `src/ai_novel_factory/local_task_queue.py`: SQLite에 작업 ID·작품 ID·회차·상태·시도 횟수·비식별 오류 코드만 기록. `enqueue`, `claim`, `finish`, `run_one`, `run_one_async` 지원. `BEGIN IMMEDIATE`로 동시 선점 중복 방지. 재시작할 때 미완료 RUNNING 작업은 `INTERRUPTED`로 전환하고 임의 자동 재시도 없음.
- `src/ai_novel_factory/celery_local_adapter.py`: `127.0.0.1`/`::1` 숫자형 루프백 Redis URL만 허용. 명시적 승인 없는 Celery 구성 거부. Celery는 선택적 의존성. 구성 함수는 실제 작업 전송/연결을 하지 않음.
- `tests/test_stage67_local_queue.py`: 24개. 상태 전이, 재시작, 동시 선점, 비밀정보 미저장, 스레드 실행, 비정상 완료, 루프백 제한, 실제 66단계 Orchestrator를 호출하는 테스트 포함.

## 실제 호출 예

```python
from pathlib import Path
from ai_novel_factory.local_task_queue import LocalTaskQueue

queue = LocalTaskQueue(Path('user_data') / 'queue.sqlite3')  # 디렉터리는 사전에 생성
queue.enqueue('novel-1', 5, task_id='novel-1-episode-5')

# 명시적으로 로컬 작업 핸들러 연결. 실제 Writer 실행은 호출자 책임.
# Orchestrator 결과 상태가 AWAITING_HUMAN_REVIEW인 경우에만 True 반환할 것.
thread = queue.run_one_async(lambda project, episode: True)  # 테스트용 예시
thread.join()
assert queue.get('novel-1-episode-5').status == 'COMPLETED'
```

**주의:** `COMPLETED`는 **작업 핸들러의 실행 종료**만 의미하며 원고 확정, 공식 품질 검사, 사용자 승인 또는 출판 성공을 의미하지 않음. 테스트용 핸들러를 실제 생성기로 오해하지 말 것.

## 보안 및 기능 제한

- 큐에 원고/프롬프트/참고소설 원문/자격 증명은 넣지 않음. 핸들러는 같은 실행 중인 프로그램에서 별도로 제공해야 하며, 재시작한 프로세스에서 과거 작업을 자동 재실행하지 않음.
- Queue DB 경로는 심볼릭 링크인지 검사하지만 경로 디렉터리와 파일 간 경쟁 상태(TOCTOU)까지 완전히 방어하지 않음. 사용자 소유 신뢰 폴더에서만 사용할 것.
- 실제 Redis·Celery 설치, 브로커 연결, 워커 실행, 분산 상태 일관성, 네트워크 절대 차단은 검증하지 않음. Celery를 실행하면 프로세스 자체가 네트워크를 사용할 수 있으므로 이번 검증에서는 시작하지 않음.
- 실패 자동 재시도·체크포인트·일시정지·취소·진행률은 68~69단계 과제. Windows EXE, PySide6 실화면, 실제 AI 모델 추론도 검증하지 않음.
- 기존 SQLite `ResourceWarning`은 이번 신규 큐가 아니라 구형 DB 테스트에서 남아 있음.

## 검증 방법

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage67*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -v
```

전체 테스트 실행 출력을 `docs/stage67_full_stdout.txt` 및 `docs/stage67_full_stderr.txt`에 포함. 별도 폴더에서 ZIP 재압축 해제 검증 및 ZIP CRC/숨김 파일 검사 수행.
