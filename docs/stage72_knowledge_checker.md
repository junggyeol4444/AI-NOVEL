# 72/100 — 등장인물 지식 범위 충돌 검사

## 계획 근거 및 구현 범위

- 원본 100단계 로드맵: **72단계: 등장인물 지식 범위 충돌 검사**.
- `docs/requirements.md`의 **ANF-REQ-033**은 43단계 Character Knowledge DB에 직접 매핑되어 있습니다. **72단계 전용 ANF-REQ 번호는 요구사항 표에 없습니다**. 이번 기능은 기존 DB 기록을 실제 원고 검사와 연결하는 새 읽기 전용 모듈입니다.
- `src/ai_novel_factory/knowledge_checker.py`는 `CharacterKnowledgeStore`의 회차별 지식 획득·상실 이력을 조회합니다. **검토자가 표시한 원고의 주장 위치, 인물 ID 및 사실 ID**를 대조하여 다음을 보고합니다.
  - `NOT_RECORDED`: 해당 인물에게 기록된 지식 이력이 없음.
  - `NOT_YET_LEARNED`: 향후 회차에서 배우지만 현재 회차에는 알 수 없음.
  - `NOT_KNOWN`: 현재 회차에서 모르는 것으로 명시됐거나 잊은 상태.
- 검사 대상 장면에서 특정 표현이 등장했다는 사실만으로 **그 인물이 사실을 알고 있다고 자동 추론하지 않습니다**. 검토자가 해당 인물이 그 사실을 사용했다고 표시하는 **구조화된 증거 표시**가 필요합니다.

## 안전성 및 상태

- 실제 원고 범위 `[start:end)`와 `evidence`가 일치해야 합니다. 근거를 변조하거나 다른 작품의 인물/사실을 연결하면 검사 오류로 거부합니다.
- 작품 revision을 검사 전후에 비교합니다. 이전 버전이 전달되면 거부합니다. 동시 트랜잭션의 엄밀한 직렬화 스냅샷을 보증하지는 않습니다.
- 결과는 원고 문자열·인물 비밀·지식 설명을 보관하지 않습니다. 위치, 사실·인물 식별자, SHA-256, 충돌 유형만 반환합니다. SHA-256도 비밀정보 보호용 암호화가 아니라 무결성 지문입니다.
- 검사 결과는 **읽기 전용**, `persisted=False`, `publication_approved=False`, `status=REQUIRES_HUMAN_REVIEW_NOT_FULL_QC`입니다.
- 65단계 `EpisodeDraftPreview`의 작품 ID·원고 SHA-256·미승인 상태를 검사하는 `check_episode_knowledge` 어댑터를 제공합니다.
- Novel Bible 및 Character Knowledge DB의 **사용자 작성 사실만** 사용합니다. 참고작 원문 자동 활용, 외부 서버, 클라우드 AI API 사용, 자동 수정·최종 확정·출판은 없습니다.

## 간단한 사용 예시

```python
from ai_novel_factory.knowledge_checker import KnowledgeUseClaim, check_character_knowledge

text = '주인공이 비밀 지도를 알고 있다고 말한다.'
start = text.index('비밀 지도')
claim = KnowledgeUseClaim(character_id, fact_id, start, start + len('비밀 지도'), '비밀 지도')
report = check_character_knowledge(store, project_id, 3, text, (claim,))
# report.findings: 아직 지식을 획득하지 않은 경우 NOT_YET_LEARNED 등
# 보고서에 소설 원문은 포함되지 않으며 승인을 의미하지 않음.
```

## 테스트 및 한계

`PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage72*.py' -q`

`PYTHONPATH=src python -m unittest discover -s tests -q`

- **완전한 NLP 지식 추론 검사가 아닙니다.** 표시되지 않은 대사·독백·암시는 검사하지 못합니다.
- 43단계 저장소의 상태 모델은 **회차 단위**입니다. 같은 회차 안에서 '발견하기 전'과 '발견한 후'의 장면 순서는 판별할 수 없습니다.
- Windows GUI/EXE, 실제 LLM 추론, Redis/Celery 라이브 통신은 이 단계에서 검증하지 않습니다.
