# 70/100 — 한 회차 자동 집필 통합 테스트 (오프라인 모의 모델)

## 공식 로드맵 및 관련 요구사항

- 공식 100단계 로드맵의 70단계: **한 회차 자동 집필 통합 테스트**.
- `docs/requirements.md`에 70단계로 **직접 지정된 ANF-REQ는 없음**. 이전 단계 관련 항목: ANF-REQ-043/044/045/046/047/048. 새 요구사항 번호를 만들지 않음.
- 69단계는 로컬 명시 재시도·체크포인트까지만 부분 구현됨. 이 테스트가 최종 원고 저장 멱등성이나 자동 무인 재개를 증명하지는 않음.

## 구현/실제 통합 흐름

- `src/ai_novel_factory/episode_integration.py`는 **이미 사용자가 큐에 등록한 작업만** ID·작품·회차 일치 검사 후 선점.
- 계획·장면·Novel Bible 포함 문맥의 메타데이터를 검증하고 `orchestrate_episode`를 호출해 **오프라인 모의 제공자** 또는 별도 승인된 로컬 실행 파일로 장면 생성 → 순서대로 결합 → **문자열 규칙에 국한된 기초 검사** → 사용자 검토 대기 상태로 전환.
- 67~68단계 로컬 SQLite 작업큐/진행률과 통합. 안전 지점은 **모델 실행 직전과 Orchestrator 반환 직후**임. 실행 중인 로컬 모델 프로세스를 강제로 중지할 수 없음.
- 작업 상태 `COMPLETED`는 작업 시도의 완료일 뿐 **원고 품질·확정·저장·출판을 의미하지 않음**. 검사 경고 시 `REWRITE_REQUIRED_NOT_IMPLEMENTED`를 반환하며 자동 고치거나 확정하지 않음.
- 오류·취소 시 부분 원고를 반환하지 않음. 원고는 메모리에만 보유하고 SQLite 작업큐는 작품·회차·상태·진행률 같은 메타데이터만 저장.
- 신규 통합 테스트는 69단계 `RetryCheckpointCoordinator`에 **실제 Orchestrator 생성 결과를 바이트 아티팩트로 전달**하여 일시 실패·수동 재대기·해시 기반 복구·변조 및 문맥 변경 차단을 확인. 체크포인트 DB에는 본문을 저장하지 않음.

## 로컬 실행 예제

```bash
PYTHONPATH=src python scripts/stage70_one_episode_smoke.py
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage70*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

예제는 임시 SQLite 작업 DB를 생성 후 삭제하며, 출력에는 장면 원고나 Novel Bible 내용 대신 상태만 표시함.

## 안전 원칙 및 미검증 범위

1. **실제 언어모델이 아닌 결정적 모의 제공자**에서 전체 통합 검증. 로컬 실행 파일은 선택적 계약만 존재; 임의 실행 파일이 스스로 네트워크에 접속하는 것을 강제로 차단하지 않음. 사용자의 실제 오프라인 모델 추론 품질은 미검증.
2. Checker는 사전에 지정한 금지 문자열 검사일 뿐 71~80단계 Continuity·Logic·Style·Similarity 검사 및 자동 재작성 아님. 참고작 유사성 자동 검사가 없으므로 이 산출물은 출판 허가 불가.
3. DB 최종본 저장·버전 충돌 해결·자동 기억 갱신·최종 사용자 승인·EPUB/출판은 수행하지 않음. 69단계 **확정본 중복 저장 방지**의 통합 검증도 여전히 미완료.
4. 69단계 체크포인트 재시작은 호출자가 기존 아티팩트를 별도 제공해야 하고, 이 70단계 편의 함수는 69단계와 자동 연결되는 무인 복구 서비스가 아님. 체크포인트 복구는 통합 테스트에서 별도 검증.
5. Redis·Celery 실제 워커, PostgreSQL·pgvector 실제 서버, PySide6 GUI, Windows EXE, 실제 Windows DPAPI를 검증하지 않음. Linux Python 환경에서 테스트하며 기존 SQLite 연결 `ResourceWarning`이 나타남.
6. 로컬 시험에서 GitHub, 외부 서버, 클라우드 AI API는 사용하지 않음. Novel Bible 우선·참고작 원문 비복제·출판 전 사용자 승인 원칙 유지.

## 로그

`docs/stage70_test_results.json`, `docs/stage70_verification_log.txt`,
`docs/stage70_full_stdout.txt`, `docs/stage70_full_stderr.txt`에 실제 테스트 결과를 포함.
