# 87/100 — 120화 이상 장기 기억 안정성 통합 시험 (ANF-REQ-060)

## 요구사항과 근거

기존 `docs/requirements.md`의 **ANF-REQ-060**: "100화 이상 장기 기억 안정성 시험을 수행한다. / 100화 이상 테스트 실행 보고서와 설정 충돌 건수를 남긴다." 사용자 제공 공식 로드맵 87단계의 범위에 한정한다. 기존 86단계 누적 ZIP(1,021개 항목)의 CRC, `docs/stage86_test_results.json` 및 `docs/stage86_verification_log.txt`를 확인했다. 원본 기획안 TXT는 현재 대화 첨부 목록에서 찾을 수 없어 **직접 확인하지 못했다**.

## 구현·완료 기준

- `src/ai_novel_factory/long_memory_stability_trial.py`: **120개 연속 회차**를 단일 임시 로컬 SQLite 작품에 생성하고 기존 Story Arc, Episode Planner, Scene Planner, Novel Bible, Character, World, Context Selector, `MockSceneProvider`, Episode Integration, Task Queue, Manuscript Version API를 호출한다. 모든 정상 회차는 승인되지 않은 **DRAFT**와 테스트용 회차 요약만 기록한다.
- 1화의 고유 시험 앵커를 2–120화에서 기존 `search_episode_history`로 **119회 재검색**하고, 120화까지 동일한 Novel Bible/Character/World 항목이 유지되는지 **120회** 확인한다. 저장소를 닫았다 다시 열어 120개 원고·버전·1화 앵커의 지속성을 재검증한다. SQLite `integrity_check`와 `foreign_key_check`를 검사한다.
- **설정 충돌 건수**는 기존 Bible 규칙과 회차별 **명시적인 구조화 key/value 후보**의 불일치만 계산한다. 기본 시험의 충돌 건수는 0이다. `--conflict-episode 73` 실패 주입에서는 73화에 정확히 **1건**의 충돌을 탐지하여 해당 초고 저장을 차단하고 119개만 저장한다. 후보는 Novel Bible에 쓰지 않는다. 자연어 원고 속 설정 충돌은 검사하지 않는다.
- JSON에는 회차 번호·상태·SHA-256·충돌/오류 건수만 남기며 원고·프롬프트·세계관 본문·비밀정보·로컬 DB 파일을 포함하지 않는다. 임시 SQLite는 시험 후 삭제된다.
- 정상 시험은 오류 0, 충돌 0, 120화 DRAFT 120개, 요약 120개, 버전 120개, FINAL 0개, 앵커 재검색 실패 0, 정합성 검사 통과 시에만 성공한다. 실패 주입은 종료 코드 1이 정상 기대 결과다.

## 실행 명령

```bash
PYTHONPATH=src python -m unittest -q tests.test_stage87_long_memory_stability_trial
python scripts/stage87_run_long_memory_trial.py --output docs/stage87_long_memory_trial_report.json
python scripts/stage87_run_long_memory_trial.py --output docs/stage87_conflict_injection_report.json --conflict-episode 73  # 기대 종료 1
python scripts/stage87_partitioned_regression.py --prefix docs/stage87_worktree --start 1 --end 8
python scripts/stage87_partitioned_regression.py --prefix docs/stage87_worktree --aggregate
```

## 정확한 검증 한계

이것은 **120화 오프라인 Mock Writer 초고 + 구조화된 가상 설정과 과거 요약의 장기 저장·조회·충돌 계측 시험**이다. 120화 실제 AI 소설 생성, 자연어 설정 모순 검출, 실사용자의 기억 변경 승인, 자동 Memory Delta 추출·반영, 71–80단계 전체 자연어 품질검사 연계, 실제 pgvector 의미검색, Windows EXE/GUI, 실제 Redis/Celery, 실제 로컬 LLM, 출판 승인·업로드 검증이 아니다. 기존 84/85단계의 승인 체인·OS 예약 실행도 이번 시험에 연결하지 않는다. Novel Bible 우선, 무승인 FINAL/출판 금지, 외부 네트워크 미사용 원칙을 지킨다.

검증 수치는 `docs/stage87_test_results.json`, `docs/stage87_verification_log.txt` 및 최종 독립 압축 해제 검증 JSON을 확인한다.
