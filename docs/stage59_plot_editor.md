# 59단계 — 회차·장면 플롯 확인 및 수동 편집 UI

기준: 공식 100단계 로드맵 59단계, 누적 58단계 ZIP. `docs/requirements.md`의 번호표에 59단계 직접 매핑된 ANF-REQ 항목은 없으며 이 로드맵에서 정의된 UI 범위를 구현합니다.

## 구성

- `src/ai_novel_factory/desktop/plot_editor_model.py`: PySide6 없이 테스트 가능한 오프라인 데이터 세션. 기존 SQLite 파일 열기, 프로젝트/회차 열람, 회차 생성, 회차 플롯 저장, 장면 추가·수정·삭제.
- `src/ai_novel_factory/desktop/plot_editor.py`: PySide6 `PlotEditorWidget`. 'Episodes' 페이지에 나타나며 로컬 SQLite 파일 선택, 작품/회차 목록, 회차 플롯 편집창, 장면 플롯 편집창과 개별 명시적 저장 버튼을 제공.
- `src/ai_novel_factory/desktop/app.py`: 기존 Episodes 페이지의 자리표시자를 실제 PlotEditorWidget으로 연결. 다른 페이지 및 로컬 API 확인 버튼 유지.
- `tests/test_stage59_plot_editor_model.py`: SQLite 실DB 임시 파일 기반의 저장·다른 작품 격리·손실 업데이트 방지·입력 검증.
- `tests/test_stage59_plot_editor_optional.py`: PySide6가 설치된 환경에서만 가능한 GUI 오프스크린 연동 테스트. 이번 검증 환경에서는 PySide6 미설치로 건너뜀.

## 사용자 흐름

1. `python -m ai_novel_factory.desktop` (PySide6 설치된 환경; 실제 GUI 실행 검증 별도 필요)
2. `Episodes` 메뉴 → `로컬 DB 열기`. **이미 Novel Bible 및 Episode 스키마가 있는 로컬 SQLite DB만 허용**. 빈 파일이나 무관한 DB를 열 때 신규 스키마를 임의 생성하지 않음.
3. 작품과 기존 회차 선택. 필요하면 별도 번호로 새 회차 생성(명시적 입력).
4. 회차 플롯을 수정하고 `회차 플롯 저장`; 장면을 추가한 후 자유 텍스트로 장면 계획(장소/인물/목표/갈등/감정)을 입력하고 `장면 저장`.
5. 기존 EpisodeStore의 회차별 낙관적 버전 검사를 사용하므로 다른 창에서 변경된 경우 변경 내용 덮어쓰기를 거절. 외부 변경 후 다시 조회해야 함.
6. 선택 변경·화면 닫기 시 미저장 수정은 확인 대화상자로 경고. 장면 삭제도 확인 필요.

## 보장과 한계

- DB 저장은 버튼 클릭 시에만 발생. 초고·최종 원고, Novel Bible 규칙, 사용자 출판 승인 상태를 편집하거나 변경하지 않음.
- 해당 작품의 회차/장면만 접근. 로컬 GUI에는 원격 API 호출 코드가 없음.
- 기존 `bible_episode_scenes.text`는 일반 텍스트 필드로, **ScenePlan 속성별 구조화 영속화·시각화는 구현하지 않음**. 장면별 플롯을 사용자가 자유 텍스트로 편집하는 기능임.
- 다중 항목 동시 일괄 저장/저장 취소(Undo)/자동 복구는 지원하지 않음. 회차 플롯과 장면은 각각 독립 명시적 저장.
- Qt 모듈 코드는 작성하고 컴파일했으나 이번 Linux 검증 환경은 PySide6 미설치이므로 **실제 GUI 렌더링/클릭/Windows EXE 실행은 미검증**.
- AI 기반 플롯 자동 창작, 원문 참고, 집필, 출판은 이 단계에서 수행하지 않음.

## 검증 명령

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage59*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

기존 `docs/requirements.md`의 요구사항은 변경하지 않고 공식 단계 59 범위에 구현을 연결했습니다.
