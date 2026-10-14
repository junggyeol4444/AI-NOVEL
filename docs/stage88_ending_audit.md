# Stage 88 — 완결 후 미회수 복선·미해결 갈등·시간선 오류 검사

- 공식 범위: 88/100, ANF-REQ-061 (`docs/requirements.md`에서 확인).
- 원본 기획안 TXT: 대화에서 직접 접근할 수 없어 **미확인**. 사용자가 제공한 공식 로드맵과 기존 요구사항 사용.
- 전제: 사용자 소유 Novel Bible의 동일 로컬 SQLite 파일. 외부 서버·클라우드·Git 없음.
- 범위: 등록된 복선의 회차별 상태, 사용자가 명시적으로 등록한 갈등의 해결 상태,
  기존 Timeline Store의 선후관계·시간 오류, 완결 회차까지의 원고 최종 후보 존재,
  완결 이후 초고·복선·갈등 기록 여부.
- 완료 기준: 미회수 복선, 미해결 갈등, 날짜 불확실/시간선 손상,
  원고 누락 또는 검토 범위 미확인이 있으면 `ready_for_human_review=False`.
  명시적 검토 범위 확인, 근거 지문 및 최신성 재검사 지원.
- `OPEN`/`DEVELOPING` 복선은 미회수로 차단, `ABANDONED`는 의도적 폐기인지
  인간 검토가 필요하므로 차단. 갈등도 동일하게 OPEN/ABANDONED를 차단.
- 알 수 없는 사건 날짜는 곧바로 오류라고 단정하지 않고 `NEEDS_REVIEW`로 차단.
  구조적 시간선 모순은 `TIMELINE_INVALID`로 차단.
- 검토 범위 확인 플래그는 **호출자 주장**이며 사용자 신원/실제 승인 증빙이 아님.
  데이터베이스에 갈등·복선 기록이 없다는 사실만으로 작품의 갈등·복선이
  없음을 자동 추론할 수 없으므로 플래그를 요구함.
- 보고서의 `ready_for_human_review=True`는 완결 확정 또는 출판 승인 아님.
  실제 원고 상태를 변경하거나 출판하는 기능을 제공하지 않음. 현재 모든
  최종 확정 경로를 이 검사에 연결했다고 주장할 수 없음(89단계 승인 통합 예정).
- 자연어의 복선·갈등·시간선 의미 추론, 누락된 등록 항목 자동 탐색,
  실제 Windows EXE/GUI/LLM/pgvector/Redis/Celery 검증은 범위 밖.

## 로컬 사용 예시

```python
from ai_novel_factory.ending_audit import EndingReviewStore
with EndingReviewStore('novel.db') as review:
    # project_id는 동일 DB에 존재하는 사용자 작품 ID
    report = review.inspect_ending(project_id, 30,
        foreshadow_inventory_reviewed=True,
        conflict_inventory_reviewed=True,
        timeline_inventory_reviewed=True)
    if report.ready_for_human_review:
        review.require_current_review(report,
            foreshadow_inventory_reviewed=True,
            conflict_inventory_reviewed=True,
            timeline_inventory_reviewed=True)
        # 여전히 사용자 최종 검수/승인 필요. 자동 확정/출판하지 않음.
```

갈등은 `create_conflict`로 생성하고 `close_conflict(... outcome='RESOLVED',
expected_revision=...)`로 해결 기록을 남김. 명시적 폐기(`ABANDONED`)는
자동으로 해결 처리하지 않음. 모든 변경은 작품별 SQLite 트랜잭션 및
낙관적 버전 검증을 사용함. `:memory:`는 각 DB 스토어가 별개 메모리 DB가
되는 문제를 막기 위해 거절함.

## 검증

`PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage88_ending_audit.py' -v`

`python scripts/stage88_partitioned_regression.py --prefix docs/stage88_worktree`

`python scripts/stage88_partitioned_regression.py --prefix docs/stage88_worktree --aggregate`

최종 누적 ZIP을 별도 폴더에 압축 해제해 같은 명령을 재실행하며
그룹별 stdout/stderr/exit code와 테스트 모듈 중복 없음 증빙을 저장함.
