# 80/100 — 선택적 Scene 재작성·재검사 (ANF-REQ-056)

## 근거·범위

- 사용자가 제공한 공식 로드맵의 80단계: **문제가 있는 Scene만 재작성하고 재검사**.
- 누적 소스 `docs/requirements.md`의 **ANF-REQ-056**: “문제가 있는 Scene만 재작성하고 재검사한다. 문제 없는 Scene은 변경되지 않음을 검증한다.”
- 입력 기준은 79단계 전체 누적 ZIP(603개 파일). 원본 기획안 TXT 첨부파일은 이번 실행에서 실제로 접근할 수 없었으며, 사용자 메시지의 로드맵 및 누적 ZIP 요구사항을 근거로 했다.

## 구현

`ai_novel_factory.scene_revision`은 기존 65단계의 **미승인** `EpisodeDraftPreview`를 받아, 검토자가 원고의 특정 장면에 부착한 `SceneIssue(scene_number, code, start, end, evidence_sha256)`와 그 장면만을 위한 `SceneReplacement`를 검증한다. 모든 이슈 근거 위치와 SHA-256은 **원본 원고**에 결속된다. 선택하지 않은 장면의 본문·장면 해시·기존 프롬프트 해시·근거 사실 ID는 그대로 보존하며, 수정된 장면만 교체한 뒤 전체 원고의 새로운 위치·해시를 계산한다. 원본 객체를 변경하지 않는다.

- `replacement_from_scene_preview`는 이미 별도로 만들어진 64단계 `SceneDraftPreview`를 입력받아 동일 작품·회차·장면·Novel Bible 근거·provider 및 해시를 확인한다. **새 모델을 실행하지 않는다.** 반환된 데이터 클래스 자체는 암호학적으로 서명된 증명서가 아니므로, 외부 입력은 호출 시 다시 신뢰 경계를 검증해야 한다.
- 수동 교체는 `origin=REVIEWER_SUPPLIED`, `prompt_sha256=None`으로 표기하여 실제로 생성하지 않은 프롬프트 근거를 위조하지 않는다.
- **재검사:** 변경된 전체 원고를 대상으로 77단계 `check_repetition`을 필수 재실행한다. 참고작 입력이 제공되면 78단계 `check_reference_similarity`를 전체 원고·새 장면 위치·새 추상 사건구조에 대해 재실행한다. 모든 장면의 **새** 수동 주석이 제공되면 79단계 `simulate_reader_profiles`를 재실행한다. 등록 참고작 확인은 기존 `ReferenceCatalog`와 `required_reference_ids`가 모두 있어야 성립한다.
- 제공되지 않은 참고작 검사·새 독자 주석, 미수행 Continuity/Knowledge/Timeline/Foreshadowing/Logic/Style/Novel Bible 검증 및 사용자 승인은 `pending_checks`에 남는다. 결과는 항상 `REVIEW_REQUIRED_NOT_APPROVED`이며 **자동 합격·확정·출판하지 않는다**.
- 결과 보고서에는 원고 문장과 참고작 문장을 넣지 않는다. `EpisodeRevisionPreview.draft`는 임시 메모리 객체에만 존재하며 `repr`에서 숨긴다. 로컬 DB·파일·네트워크 쓰기 없음.

## 사용 예시 (직접 코드 호출)

```python
from hashlib import sha256
from ai_novel_factory.scene_revision import SceneIssue, SceneReplacement, rewrite_selected_scenes

# original: 기존의 미승인 EpisodeDraftPreview
span = original.scenes[1]
fragment = original.draft[span.start:span.end]
new_scene = '검토자가 새로 작성한 장면.'
result = rewrite_selected_scenes(
    original,
    issues=(SceneIssue(2, 'MANUAL', span.start, span.end, sha256(fragment.encode()).hexdigest()),),
    replacements=(SceneReplacement(2, span.draft_sha256, new_scene,
                                   sha256(new_scene.encode()).hexdigest()),),
)
assert result.draft_sha256 == result.report.revised_sha256
assert not result.publication_approved
```

## 구현되지 않은 범위

- 문제 장면 **자동 발견**, 실제 LLM **자동 재작성**, 사람의 미학적 판단, AI 독자 반응 예측, 전체 설정/논리 검사의 일괄 재실행은 구현되지 않았다. 64단계 Writer를 명시적으로 별도 호출해 미승인 재작성 초고를 만들 수는 있으나, 이번 함수가 Writer를 실행하지는 않는다.
- 이슈 코드와 근거의 **사실적 타당성**은 자동 검증하지 않는다. 근거 위치·해시가 원고와 일치하는지만 확인한다.
- 78단계 검사에서 `clear`가 나오더라도 표절·저작권 안전 또는 출판 가능성을 보증하지 않는다. 수정 뒤 참고작의 장면/구조 주석은 새로 제공해야 한다.
- 새 미승인 초고는 65단계의 `EpisodeDraftPreview`가 아닌 **`EpisodeRevisionPreview`**이므로, 후속 기능이 이를 원고 확정 객체로 간주해서는 안 된다. 별도의 사용자 승인 절차(89단계)가 필요하다.
- Windows EXE/GUI, 실제 로컬 모델 추론, Redis/Celery, pgvector, 출판 기능은 이번 단계에서 검증하지 않았다. 기존 SQLite 연결 미종료 경고가 다른 테스트에서 나타날 수 있다.
