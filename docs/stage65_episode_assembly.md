# 65/100 — 여러 Scene을 하나의 회차 초고로 결합

## 범위

공식 100단계 계획의 65단계. 64단계 `scene_writer.generate_scene_draft`가 이미 반환한 `SceneDraftPreview` 여러 개를 **회차·장면 계획 순서대로** 결합하는 오프라인 메모리 전용 기능입니다. `docs/requirements.md`에는 65단계 전용 요구사항 ID가 직접 매핑되지 않아 임의로 새 ID를 만들지 않았습니다.

- 구현: `src/ai_novel_factory/episode_assembler.py`
- 신규 테스트: `tests/test_stage65_episode_assembler.py`
- API: `assemble_episode_draft(project_id, episode, scenes, previews, *, maximum_chars=1_000_000)`
- 결과: `EpisodeDraftPreview` (회차 원고, SHA-256, 장면별 시작·끝 위치 및 원고/프롬프트 지문, Novel Bible 출처 ID, 생성 경로)

### 검증 규칙

- 정확히 하나의 초고가 각 장면 계획에 대응해야 하며 입력 순서는 장면 1부터 순차적으로 일치해야 합니다. 누락, 중복, 순서 변동, 회차/작품 불일치, 불완전한 장면 계획을 거부합니다.
- `SceneDraftPreview`의 텍스트 SHA-256 일치, SHA-256 형식, 메타데이터, 제공자/원점 정보를 재검증합니다. **지문은 무결성 확인용이지 서명이나 작성자 신원 인증은 아닙니다.**
- 장면별 Novel Bible 사실 ID 집합이 동일한지 검사합니다. 모의/로컬 제공자를 한 회차에 혼용하지 않습니다.
- 입력이 이미 저장·승인·출판 상태이거나 초고 상태가 아니면 거부합니다.
- 장면 원고 텍스트는 손실 없이 그대로 이어 붙이며 장면 사이에 `\n\n`을 삽입합니다. 장면별 `[start:end]`는 Python 문자열 인덱스이고 `end`는 미포함입니다.
- 1~100개 장면, 장면마다 최대 100,000문자, 회차 최대 1,000,000문자로 제한합니다. 초과 시 자르지 않고 거부합니다.
- 반환 원고는 `DRAFT_REQUIRES_USER_APPROVAL`; DB·파일 저장, 자동 승인, 유사성 검사, 자동 출판은 수행하지 않습니다.

### 사용 예

```python
from ai_novel_factory.episode_assembler import assemble_episode_draft

# episode: EpisodePlan, scenes: 순서대로 된 tuple[ScenePlan, ...]
# previews: 각 장면에 대해 64단계가 생성한 tuple[SceneDraftPreview, ...]
preview = assemble_episode_draft('novel-1', episode, scenes, previews)
assert preview.draft[preview.scenes[0].start:preview.scenes[0].end] == previews[0].result.draft
assert not preview.persisted and not preview.publication_approved
```

### 제한 사항

실제 언어모델 추론 품질/독창성 보장 없음. 입력으로 이미 생성된 장면 초고만 받으므로 참고 소설의 원문을 의도적으로 추출·복사하지 않지만 **모델 출력의 원문 유사성 자동 검사는 수행하지 않습니다.** 참조 원문 복제 방지는 이후 Similarity Checker에서 따로 검증해야 합니다. 수동 저장 UI나 Episode DB에 대한 자동 연결도 이 단계의 범위가 아닙니다. Windows EXE/PySide6 실제 구동, DPAPI, 실제 PostgreSQL/pgvector 및 로컬 AI 모델 실행은 별도 검증 필요.

### 테스트

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage65*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -q
```
