# 63단계 — Novel Bible 우선 Writer 프롬프트 구성

- 공식 100단계 개발 로드맵 63: `Novel Bible 우선 Writer 프롬프트 구성`
- 관련 기존 기준: `ANF-REQ-031` (Novel Bible 우선), `ANF-REQ-046` (61단계 로컬 모델 계약), `docs/requirements.md`에 63단계로 직접 매핑된 독립 요구사항 ID는 없음.
- 입력 소스: `AI_Novel_Factory_stage62_local.zip` (304개 파일), `docs/stage62_test_results.json`, `docs/stage62_verification_log.txt`를 검토함.

## 구현

`src/ai_novel_factory/writer_prompt.py`에 `build_writer_prompt(project_id, episode, scene, context)` 추가.

1. 53단계 `EpisodePlan`, 54단계 `ScenePlan`, 55단계 `EpisodeContext`를 입력받아 61단계 `SceneDraftRequest` 계약으로 변환.
2. Novel Bible 사실을 요청의 최상단에 놓고, 회차 계획과 보조 사실은 낮은 우선순위로 명시. Style Bible은 별도 필드에 배치.
3. 작품 ID, 회차/장면, 상태, 필수 장면 내용, 동일 작품 출처, 사실의 유효 회차 및 사건/인물 관련성을 다시 검사.
4. `reference_novel` 등 허용하지 않는 출처를 거부. 참고 원문을 위한 입력 필드를 만들지 않음.
5. 요청 전체 길이 제한을 61단계 검증기로 강제하며, 너무 길면 자동 생략하지 않고 오류 반환.
6. 저장·모델 실행·원고 확정·출판 없이 사용자 검토가 필요한 요청 미리보기만 반환.
7. 사실은 JSON 문자열로 이스케이프해 데이터 구역에 놓고 명령처럼 취급하지 않도록 지침 추가. 이는 프롬프트 인젝션 방어 **보장**이 아님.

## 오프라인 사용 예

```python
from ai_novel_factory.writer_prompt import build_writer_prompt
from ai_novel_factory.episode_context import select_episode_context, ContextFact
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.scene_planner import ScenePlan

plan = EpisodePlan(1, 1, '서재 탐색', ('단서 발견',), ('주인공',), '', (), '')
scene = ScenePlan(1, 1, '서재', ('주인공',), '열쇠 발견', '잠긴 서랍', '긴장')
facts = (ContextFact('my-work', 'novel_bible', 'canon-1', '주인공의 기억은 지워지지 않는다'),)
context = select_episode_context('my-work', plan, facts)
preview = build_writer_prompt('my-work', plan, scene, context)
assert preview.persisted is False
# 사용자가 요청을 검토한 뒤 별도로 승인할 수 있다. AI 추론은 이 함수가 수행하지 않는다.
```

## 범위와 한계

- 입력 사실이 사용자의 고유 설정인지 여부는 호출자가 확인해야 하며, 문자열 내용이 실제 참고작 원문인지 자동 판별하지 못함.
- JSON 이스케이프 및 지침 분리만으로 실제 LLM의 프롬프트 인젝션이나 설정 충돌을 완전히 방지할 수 없음.
- 장면 플롯이 완성되어 있어야 하며 기획 미리보기의 빈 장면 슬롯은 거부됨.
- 실제 로컬 모델 추론, 생성 품질, 품질 검사, Windows EXE 실행, 실제 Windows DPAPI 동작 검증은 이 단계의 범위 밖임.
- 실행은 오프라인 Python 표준 라이브러리로만 수행하며, GitHub/원격 저장소/외부 API 미사용.
