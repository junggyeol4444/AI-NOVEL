# 66/100 — Planner·Writer·Checker 제어 Orchestrator

## 로드맵 및 요구사항

- 공식 100단계 로드맵 66단계: `Planner·Writer·Checker 제어 Orchestrator 개발`
- 기존 `docs/requirements.md`: **ANF-REQ-047** — `계획→집필→검수→수정→기억 업데이트를 순서대로 조정한다.` 검증 기준: `모의 작업에서 단계별 상태 전이가 기록된다.`
- 이 단계의 구현 범위는 **검수/수정/기억 업데이트를 위한 상태 제어 경계 구축**이며, 후속 71~80단계 품질 검사·재작성과 81~82단계 실제 기억 DB 갱신은 아직 없음. 따라서 명시적으로 미구현 상태를 표시하고 해당 단계들을 성공으로 가장하지 않음.

## 구현

`src/ai_novel_factory/orchestrator.py`

- API: `orchestrate_episode(project_id, episode, scenes, context, provider, checker, *, local_execution_approved=False)`
- 검증된 `EpisodePlan`, 순서대로 완성된 `ScenePlan`, 해당 작품·회차의 `EpisodeContext`를 수신. 미완성/승인되지 않은 계획, 작품/회차 불일치, 다른 제공자/검사기 객체 등은 실행 전에 거부.
- 단계별: `PLANNER/VALIDATED` → 장면마다 `WRITER/DRAFTED` → `ASSEMBLER/ASSEMBLED` → `CHECKER/PRELIMINARY_PASS` 또는 `PRELIMINARY_ISSUES` → `HUMAN_GATE/PENDING` 또는 `BLOCKED`.
- 각 전이는 `WorkflowEvent(sequence, step, status, scene_number)`로 순번을 기록. 오류가 나면 `WORKFLOW/FAILED`와 비식별 오류 코드를 반환하며, 이전 단계 부분 초고를 반환하지 않음.
- `OfflineLiteralChecker`는 **사용자 제공 금지 문자열의 정확한 부분 문자열 매칭만 확인하는 제한적 오프라인 검사기**. 검사 결과는 `LITERAL_TERMS_ONLY_NOT_FULL_QC`. `PRELIMINARY_PASS`는 정식 품질 검사를 통과했다는 뜻이 아님.
- 검사 문제 발견 시 `REWRITE_REQUIRED_NOT_IMPLEMENTED`. 문제가 없으면 `AWAITING_HUMAN_REVIEW`. 어느 경우에도 `persisted=False`, `publication_approved=False`, `memory_updated=False`, `rewritten=False`.
- 출력에는 참고소설 원문을 노출하는 필드 없음. Novel Bible 최우선 문맥 검사는 기존 `writer_prompt`와 `scene_writer`를 재사용. SHA-256 출처/변조 검사는 `episode_assembler` 재사용. 금지 단어는 지문만 보고하고 로그에는 기록하지 않음.
- 본 모듈은 자체 네트워크/파일/DB 호출 없음. 다만 **승인된 사용자 실행 파일 자체의 네트워크 사용은 강제 차단하지 않음**. 오프라인 신뢰 실행 파일만 연결해야 하며 오프라인 절대 보증을 주장하지 않음.

## 예

```python
from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.orchestrator import OfflineLiteralChecker, orchestrate_episode

# episode, scenes, context: 사용자가 이미 완성하여 검증된 기존 53~55단계 객체
run = orchestrate_episode('novel-1', episode, scenes, context,
                          MockSceneProvider(), OfflineLiteralChecker(('금지 표현',)))
assert run.status in ('AWAITING_HUMAN_REVIEW', 'REWRITE_REQUIRED_NOT_IMPLEMENTED')
assert not run.persisted and not run.publication_approved
```

## 제한 사항

- **실제 AI 장면 집필 품질**, 완전한 Continuity·Logic·Style·Similarity Checker, 재작성 실행, 메모리 Delta/DB 자동 갱신, 확정/출판, 반복 재시도/체크포인트는 검증/구현하지 않음. 각각 후속 단계 대상.
- 실제 Windows EXE/PySide6 GUI, DPAPI 및 실제 로컬 LLM 추론은 Linux 테스트로 검증하지 못함.
- 단계 상태 기록은 메모리 내 불변 튜플이며, 작업 이력 DB 영속 저장은 수행하지 않음.
- 임의 코드를 실행하는 승인된 로컬 실행 프로그램의 내부 활동을 제한하는 OS 샌드박스는 제공하지 않음.

## 테스트

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage66*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

실행 stdout/stderr 및 최종 ZIP 재추출 검증 결과는 같은 폴더의 `stage66_*` 파일에 기록.
