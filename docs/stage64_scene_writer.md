# 64/100 — 장면 단위 소설 초고 생성 (로컬 연동)

## 범위 및 기존 기능 재사용

- 63단계 `writer_prompt.build_writer_prompt`가 EpisodePlan, ScenePlan, EpisodeContext를 다시 검증하고 Novel Bible 최우선 컨텍스트를 만듭니다.
- 61단계 `local_models.draft_scene`로 **장면 하나만** 생성합니다.
- `scene_writer.generate_scene_draft`는 오프라인 모의 제공자 또는 사전 승인한 로컬 실행 파일만 허용합니다. 반환값은 `SceneDraftPreview` (원고, 2개 SHA-256, 설정 출처 ID, 명확한 생성 원점) 입니다.
- 사용자가 직접 작성한 Novel Bible과 현재 회차 설정만 보냅니다. 참고 작품 원문과 다른 작품/미래 회차 사실을 전달하지 않습니다.
- 반환값은 **미확정·메모리 내 초고**입니다. DB 저장, 자동 승인, 출판, 파일 기록, 자동 품질 검사는 없습니다.

## 사용 예 (모의 모델)

```python
from ai_novel_factory.scene_writer import generate_scene_draft
from ai_novel_factory.local_models import MockSceneProvider

preview = generate_scene_draft('work1', episode_plan, scene_plan,
                               selected_episode_context, MockSceneProvider())
assert preview.origin == 'DETERMINISTIC_MOCK_NOT_AI'
assert not preview.persisted and not preview.publication_approved
print(preview.result.draft)  # 사용자가 검토할 테스트용 문장
```

`LocalExecutableProvider`는 절대 경로의 로컬 실행 파일을 **생성할 때** `explicitly_allowed=True`로 설정해야 하고,
64단계 호출에서 `local_execution_approved=True`를 **다시 명시**해야 실제 실행합니다. 이 어댑터가 실행 파일 자체의 네트워크 사용을 금지할 수는 없으므로 실행 파일의 신뢰성은 사용자가 오프라인에서 사전 검증해야 합니다.

## 주요 예외/검증

- 작품 ID·회차·장면 불일치, Novel Bible 필수 사실 누락, 제한 초과, 허용되지 않은 출처 → 생성 거부.
- 모의 공급자 및 허용된 로컬 실행 파일의 구체 타입만 허용. 임의 공급자 ID 사칭 차단.
- 로컬 프로세스의 요청/응답은 JSON, 타임아웃·응답 형식 검증은 61단계에서 수행.
- 원고는 승인되지 않았고 유사성 검사 결과도 없습니다. 모델 출력 자체는 문장 복제 가능성을 완전히 배제하지 못하며 이후 품질/유사성 검증이 필수입니다.

## 실행과 한계

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage64*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -q
```

이 단계는 실제 로컬 모델의 추론 품질을 보증하지 않습니다. 모의 공급자의 출력은 템플릿 문장이고, 로컬 프로세스 테스트는 직접 작성한 JSON 테스트 프로그램입니다. Windows EXE 및 실제 PySide6 GUI, Windows DPAPI, PostgreSQL/pgvector, 실제 자동 집필·출판은 검증하지 않았습니다. 원고 저장도 구현하지 않았습니다.
