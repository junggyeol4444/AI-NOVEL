# Stage 58 — 선택한 Reference Pattern을 새 플롯에 반영

기존 공식 로드맵 58단계의 **오프라인·통계 전용** 초기 통합입니다.

- `apply_reference_patterns(episode, context, selection, usage)`은 이미 사용자가 선택한 `ElementSelection`(35단계)과 **명시적으로 기록한 사용 기록** `PatternUsageRecord`(37단계), `EpisodePlan`(53단계), `EpisodeContext`(55단계)를 함께 받습니다.
- `usage.current == True`인 경우에만 처리합니다. 실제 사용 전에는 로컬 `PatternUsageStore.get(usage_id)`를 호출해 **현재 상태를 다시 검사**해야 합니다. 기록은 데이터베이스로부터 받은 객체를 전달할 책임이 호출자에게 있습니다.
- `selected_keys`에 들어 있는 통계 항목만 스키마 순서대로 `PatternPlotNote`로 옮깁니다. 수치의 허용 범위, 가중치, 참고작 수, 집중도(최대 60%), 장르 및 사용 기록 일치를 검증합니다.
- 출력은 실제 회차 목표·감정 흐름·필수 사건·Hook을 덮어쓰지 않습니다. 대신 `ending_hook`, `required_events`, `emotional_flow`, `style`, `scene_dialogue`에 대한 **고정된 편집 검토 질문**과 **원문 없는 익명화 관찰 수치**를 제공합니다.
- Novel Bible을 포함한 해당 작품의 컨텍스트는 **별도 `canon_facts`**에 유지하며, 참고 통계는 그보다 낮은 우선순위의 검토 메모입니다. 다른 작품의 설정 또는 참고작 원문 자료가 섞이면 오류입니다.
- 원본 참고소설·작가 문장·등장인물명·고유 사건·외부 AI 호출 없이 동작하며 데이터베이스 쓰기, 자동 수정, 자동 확정, 출판을 수행하지 않습니다.
- **한계:** 작가적 플롯 창작 및 AI 해석은 하지 않습니다. 다른 장르의 패턴을 교차 적용하는 기능은 아직 제공하지 않으며 거절합니다. 패턴 사용 기록 자체는 프로젝트 ID로 묶여 있지 않으므로 프로젝트별 사용 권한은 호출 애플리케이션이 관리해야 합니다. 원본 대조 기반 유사성 검사는 별도 후속 단계입니다.

## 실행

```sh
PYTHONPATH=src python -m unittest tests/test_stage58_pattern_application.py -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

Windows EXE 빌드나 PostgreSQL/pgvector 통합 실행은 이 단계에서 검증하지 않았습니다.
