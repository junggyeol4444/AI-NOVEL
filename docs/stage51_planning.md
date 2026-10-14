# Stage 51 — ANF-REQ-041

장르·소재·회차 수·분위기·참고작 식별자를 입력받아 제목·로그라인·세계관 초안을 작성한다.

- 구현: `src/ai_novel_factory/planning.py` (`PlanningInput`, `PremiseDraft`, `draft_premise`)
- 테스트: `tests/test_stage51_planning.py`
- 참조작 텍스트를 초안에 삽입하지 않는다.
- 결과는 사용자가 Novel Bible에서 검토·확정해야 하는 미승인 템플릿 초안이다.
- 외부 AI API/로컬 LLM 호출, 데이터베이스 저장, UI 연결은 아직 없다.
- AI 기반 창작 능력 또는 Windows EXE는 이 단계에서 검증되지 않았다.
