# 86/100 — 30화 연속 생성 통합 시험 (ANF-REQ-059)

## 근거

`docs/requirements.md`의 **ANF-REQ-059**: "30화 연속 생성 시험을 수행한다. / 30화 테스트 실행 보고서와 오류 건수를 남긴다." 사용자 제공 공식 100단계 로드맵의 86단계. 직전 산출물 `AI_Novel_Factory_stage85_local.zip`의 CRC, 단계85 검증 기록과 기존 테스트를 확인했다. 원본 `붙여넣은 텍스트(1)(7)(1).txt`는 이번 실행에서 접근 가능한 대화 파일 목록에 없으므로 직접 확인하지 못했다.

## 구현 및 실행

- `src/ai_novel_factory/thirty_episode_trial.py`: **고정 30회**, 3개 Story Arc, 매 회차 2개 Scene, Novel Bible 우선 컨텍스트, `MockSceneProvider`, `OfflineLiteralChecker`, `run_one_episode`, `LocalTaskQueue`, `ManuscriptVersionStore`의 실제 기존 로컬 API를 순서대로 호출한다.
- 각 회차의 기초 검사 통과 시에만 `DRAFT` 버전을 저장한다. 임시 SQLite는 시험 후 삭제한다. 검증 기록은 원고 본문 없이 회차 번호·상태·SHA-256·오류 코드만 남긴다. 30회 연속 완료와 누락 없는 회차·30개 큐 작업·60개 Scene·30개 DRAFT 버전·FINAL 0개를 검사한다.
- `scripts/stage86_run_30_episode_trial.py --output docs/stage86_trial_report.json`: 결과 JSON과 명령의 종료 코드 생성. 정상 시 종료 0, 오류가 있으면 종료 1.
- `--blocked-episode 17`: 17화의 사전 문자 검사에 의도적으로 위반을 주입한다. 이때 17화 DRAFT 저장을 차단하고 **30회 시도, 29개 초고, 오류 1개**를 기록한다. 예상되는 종료 코드 1은 실패 주입 검증의 성공 조건이다.
- `tests/test_stage86_thirty_episode_trial.py`: 회차 연속성, 버전/초고 수, 30개 지문, 미승인 상태, 비밀/원고 비노출, 의도적 오류 1개, 모의 제공자 예외 은닉, 입력 검증, CLI/파일 보호 검증.

## 범위와 한계

**30화 연속 모의 초고 생성·로컬 DB 통합 시험**이지 30화 실제 LLM 생성 시험이 아니다. 회차별 기획 목표/Scene은 시험용 더미이고 소설적 품질을 보증하지 않는다. 70단계의 문자 기반 기초 검사만 자동 실행한다. 71–80단계의 모든 품질 검사를 통합 자동 실행하지 않는다. 84단계의 '확정 후 다음 회차 자동 진행'은 **실제 사용자 승인 인증(89단계)이 없으므로 이 시험에서 호출하지 않는다.** 85단계의 실제 OS 스케줄러도 호출하지 않는다. 회차 1–30은 승인 없는 DRAFT로만 기록하고, FINAL/출판/메모리 변경을 수행하지 않는다. 외부 서버, GitHub, 클라우드 AI API, 실제 Redis/Celery/pgvector를 사용하지 않는다. Windows EXE/GUI와 실제 로컬 LLM은 검증하지 않았다.

## 재현 명령

```bash
PYTHONPATH=src python -m unittest -q tests.test_stage86_thirty_episode_trial
python scripts/stage86_run_30_episode_trial.py --output docs/stage86_trial_report.json
python scripts/stage86_run_30_episode_trial.py --output docs/stage86_injected_rejection_report.json --blocked-episode 17  # 기대 종료 코드 1
python scripts/stage86_partitioned_regression.py --prefix docs/stage86_worktree --start 1 --end 8
python scripts/stage86_partitioned_regression.py --prefix docs/stage86_worktree --aggregate
```

`docs/stage86_test_results.json`, `docs/stage86_verification_log.txt`와 독립 압축 해제 검증 JSON에서 최종 결과를 확인한다. 테스트는 Linux Python 환경에서 실행하며 Windows 검증이 아니다.
