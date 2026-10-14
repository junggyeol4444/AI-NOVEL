# 60단계 — 전체 기획 파이프라인 테스트

## 기준 및 범위

- **원본 100단계 개발 로드맵 60단계:** 전체 기획 파이프라인 테스트.
- 입력 누적 소스: `AI_Novel_Factory_stage59_local.zip` (281개 파일; 검증 기록 기준 1,904개 테스트 중 1,890개 통과/14개 건너뜀).
- `docs/requirements.md`에서 60단계에 직접 부여된 ANF-REQ ID는 없음. 기존 51~59단계 계약에 대한 통합·회귀 시험이며 신규 번호를 발명하지 않음.

## 구현

`src/ai_novel_factory/planning_pipeline.py`에 **읽기 전용** `build_planning_preview()` 연결 함수와 `PlanningPipelinePreview` 데이터 객체를 추가.

1. `draft_premise`(51) → `plan_story_arcs`와 Arc 범위 검증(52).
2. `plan_episodes`와 회차 전체 범위 검사(53) → 요청 회차 선택.
3. `plan_scenes`와 회차/장면 검사(54) → `select_episode_context`의 프로젝트 격리 및 Novel Bible 우선(55).
4. 선택된 경우에만 이전 회차 요약 키워드 검색(57) 및 제공받은 벡터의 오프라인 코사인 검색(56) 수행. 원고 내용 검색은 이 인터페이스에서 **허용하지 않음**.
5. 선택적 Reference Pattern(58)은 사용자가 확인한 선택, 명시적 해당 작품 사용 허용, 실제 `PatternUsageStore.get()`를 통한 **현재 유효성 재확인** 이후에만 통계형 메모를 제공. 사용 기록이 변경·무효화되면 적용 거절. 참고작 원문을 기획 단계에 넣지 않음.
6. `PlotEditorSession`(59)과 실제 SQLite 임시 DB를 연결하는 통합 시험에서만 수동 저장·재조회 실시. 미리보기 함수는 저장하지 않음.

## 통합 검증

- `tests/test_stage60_planning_pipeline.py`: 22개 테스트. 내부 파이프라인 단계 연결, 실제 프로젝트별 SQLite DB에서 과거 요약 조회, 제공 벡터의 현재/미래·다른 작품 제외, 안전한 오류 처리 및 설정 개수 상한, 소켓 연결 차단, 결정성, 참조 텍스트 비노출.
- 37단계 ReferenceCatalog + GenrePatternStore + ElementSelectionStore + PatternUsageStore를 실제 임시 SQLite에서 구성한 후, 승인된 익명 수치만 58단계 검토 메모로 연결하고 변경된 패턴은 거절하는지 검사.
- 59단계 UI 독립 편집 세션으로 실제 회차/장면을 명시적으로 저장하고 DB를 닫았다가 다시 열어 원고 상태를 확인.
- 이전 단계의 1,904개 테스트를 포함하여 전체 테스트 재실행.

## 사용 예시

```python
from ai_novel_factory.planning import PlanningInput
from ai_novel_factory.planning_pipeline import build_planning_preview

preview = build_planning_preview(
    PlanningInput('판타지', '새로운 소재', 100, '긴박함'),
    'local_work_id', 1, facts=(), scene_count=3
)
assert preview.status == 'DRAFT_REQUIRES_USER_APPROVAL'
```

참고 패턴이 필요한 경우 `usage_store`, `usage_id`, `selection`과 `pattern_project_authorized=True`를 같이 넘겨야 함. `pattern_project_authorized`는 **호출 측 권한 판단을 표시하는 인자일 뿐** 별도의 인증·접근제어가 구현된 것은 아님. 사용 기록 저장소 자체가 프로젝트 범위를 가지고 있지 않으므로 호출 측에서 작품 권한을 신뢰성 있게 결정해야 함.

## 하지 않은 것

- LLM이 전체 줄거리나 장면의 사건을 창작하는 기능, 새 계획의 자동 저장·확정·출판은 구현하지 않음.
- 실제 임베딩 모델 또는 PostgreSQL/pgvector 서버를 설치·연결하지 않음. 장면 검색은 이미 생성되어 제공된 벡터로만 동작.
- PySide6가 없는 환경에서는 화면 표시·마우스 조작 및 Windows EXE 실행을 시험하지 않음.
- 참고작 구조의 예술적 독창성이나 실제 유사성 검사 품질을 보장하지 않음.

## 오프라인 테스트 명령

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage60*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

다음 로드맵은 61단계 AI 모델 제공자 API 연동이나, 본 사용자 요구의 외부 서버·클라우드 AI API 금지 원칙에 따라 향후 범위를 재검토해야 한다.
