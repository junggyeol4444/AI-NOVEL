# 83/100 — 초고·수정본·최종본 버전관리

## 근거 및 범위

사용자가 제공한 공식 100단계 로드맵의 **83단계**를 구현한다. `docs/requirements.md`에 **83단계에 직접 배정된 ANF-REQ ID는 없다.** 기존 회차 저장 요구사항 `ANF-REQ-039`(49단계)은 관련 기반 기능으로만 참고한다. 새로운 요구사항 ID를 만들지 않는다. 원본 기획안 TXT는 이 실행 환경에서 직접 확인되지 않았으므로 사용자 제공 로드맵/기획 요약 및 82단계 누적 ZIP의 요구사항을 기준으로 했다.

## 구현

`ai_novel_factory.manuscript_versions.ManuscriptVersionStore`는 기존 `EpisodeStore`의 프로젝트별 SQLite DB에 `bible_manuscript_versions`를 추가한다. 모든 기록은 작품·회차 ID에 귀속되며, 버전 ID, 순번, 종류, 당시 회차 revision, draft/final_text 전체 스냅샷, 선택적 메모, 생성 시각, SHA-256 지문을 가진다. 읽기 API는 지문·버전 순서·형식 무결성을 검사한다. 기본 딕셔너리 출력은 원고와 메모를 마스킹한다.

- `save_version(..., kind='DRAFT'|'REVISION'|'FINAL', expected_revision=...)`: 명시적으로 새 원고를 저장하고 **같은 SQLite 트랜잭션**에서 회차 revision 및 버전 스냅샷을 갱신한다. 버전은 누적·조회할 수 있고 과거 스냅샷을 덮어쓰지 않는다. optimistic revision과 마지막 스냅샷 대조로 외부 수정/충돌을 감지한다.
- `capture_current(..., expected_revision=...)`: 버전관리 도입 전에 저장한 기존 draft/final_text를 첫 `BASELINE` 스냅샷으로 명시적 보존한다. 기존 회차 revision은 변경하지 않는다. 최초 이력이 없는 회차에서 기존 원고가 발견되면 저장 전에 이 작업을 요구한다.
- `restore_as_revision(..., version_id=..., expected_revision=...)`: 과거 버전의 원고를 **새 REVISION**으로 저장하며 최종본/출판 승인 상태를 복원하지 않는다. 이력은 유지된다.
- `list_versions`, `get_version`: 이력 순서·지문 검증 및 작품/회차별 조회. `delete_episode`는 버전 이력이 있는 회차의 실수 삭제를 차단한다.
- `FINAL`은 회차 DB의 **로컬 최종본 후보**일 뿐, 사용자 승인·출판 승인·플랫폼 업로드를 의미하지 않는다. 새 DRAFT/REVISION 저장 시 이전 `final_text`를 지워 오래된 최종본이 남지 않도록 한다.

```python
from ai_novel_factory.manuscript_versions import ManuscriptVersionStore

store = ManuscriptVersionStore('novel_bible.sqlite3')
try:
    # 프로젝트/회차는 기존 Novel Bible / EpisodeStore API로 먼저 생성한다.
    current = store.get_episode(project_id, episode_number)
    if current.draft or current.final_text:
        store.capture_current(project_id, episode_number, expected_revision=current.revision)
        current = store.get_episode(project_id, episode_number)
    version = store.save_version(project_id, episode_number, '사용자가 작성한 초고',
                                 kind='DRAFT', expected_revision=current.revision)
    history = store.list_versions(project_id, episode_number)
finally:
    store.close()
```

## 경계 및 알려진 한계

- 다른 모듈에서 `EpisodeStore.update_episode` 등을 직접 호출하면 자동 버전 기록은 생기지 않는다. 다음 `save_version` 호출 시 revision/본문 불일치를 감지해 차단하지만 **이전에 누락된 수정 내용은 복구할 수 없다.** 기존 저장 API 전체의 투명한 버전관리 교체는 이번 단계 범위 밖이다.
- 지문은 우발적 변조 탐지용이지 악의적인 DB 관리자에 대한 인증/암호화가 아니다. 로컬 SQLite 파일을 직접 삭제하거나 프로젝트를 삭제하면 버전도 삭제될 수 있다. 외부 백업·암호화·독립 승인 인증은 미구현이다.
- 원고 버전관리 범위는 draft/final_text다. plot, summary, scene, 검사·기억 DB 각각의 완전한 버전 스냅샷은 아니다. scene 수정 등 회차 revision을 바꾸는 기존 API를 사용하면 이후 버전 작업이 충돌로 차단될 수 있다.
- 사용자 승인을 확인하거나 원고를 확정·출판하지 않는다. 참고소설 원문 수집/복제, 원격 호출, GitHub, 클라우드 AI API를 수행하지 않는다. Windows EXE/GUI, 실제 LLM, Redis/Celery, pgvector는 이번 단계에서 검증하지 않았다.
- 검증: `tests/test_stage83_manuscript_versions.py`, 전체 회귀 테스트와 별도 ZIP 압축 해제 후 재실행. 일부 기존 SQLite 연결 `ResourceWarning`은 남을 수 있다.
