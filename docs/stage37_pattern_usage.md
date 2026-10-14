# 37단계 — 패턴 사용 기록 관리 (로컬 SQLite)

## 목표와 적용 범위

36단계 관련 패턴 검색의 결과 또는 35단계 참고 요소 선택을 **사용자가 명시적으로 창작 기획에 참고했다고 기록**할 수 있도록 한다. 검색 결과를 열람하는 것만으로는 사용 이력이 생기지 않는다. Novel Bible/실제 집필 엔진은 현재 미구현이므로, **기획 메타데이터 기록**이며 실제 AI 집필을 뜻하지 않는다.

## 저장하는 정보와 저장하지 않는 정보

새 `reference_pattern_usage` 테이블에는 임의 생성 UUID, 기준 장르 코드, 참고 패턴 장르 코드, 가중치 구분, 선택된 고정 통계 항목 코드, 비교 근접도 숫자(타 장르 선택 시), UTC 기록 시각 및 익명 통계 지문 SHA-256만 저장한다. **소설 원문, 인용문, 대사, 인물명, 파일명, 전체 경로, 저자 이름, 자유 입력 설명, 프롬프트, 생성 원고를 저장하지 않는다.** 통계 지문은 현재 숫자 관찰값에서 계산하며 원문 SHA나 원문 자체가 아니다.

## 안전 규칙

1. `record()` 호출에만 새 기록을 추가한다. `list()/get()`, 36단계 `search()`는 사용 기록을 생성하지 않는다.
2. 기록 전 **기준 장르의 저장된 요소 선택**과 **장르 패턴 최신성, 참고작 2개 이상, 개별 비중 60% 이하**를 재검증한다.
3. 다른 장르를 참고할 때는 36단계 `RelatedPatternSearch`에서 실제 검색 가능한 안전 후보인지 검증한다. 편중·삭제·변경된 대상 장르는 거부한다.
4. 기록 후 해당 구성·통계가 달라지면 지문 불일치로 **`current=False`**로 표시한다. 과거 기록을 조용히 덮어쓰지 않는다.
5. 조회 필터는 코드에 정한 장르·가중치/상태 값만 받으며, SQL은 항상 바인딩한다. 오류 메시지에 사용자 제공 문자열을 그대로 넣지 않는다.
6. 삭제는 UUID로 특정 기록 한 건만 삭제한다. 프로필, 참고작 파일, 장르 설정, 선택 요소는 삭제하지 않는다.
7. GitHub·네트워크·원격 DB·클라우드 API 사용 없음. PySide6가 없더라도 CLI와 SQLite 테스트 가능.

## 명령줄 예제

먼저 32~35단계에서 기준 장르의 장르 패턴과 선택 요소가 저장되어 있어야 한다.

```sh
# 프로젝트 루트에서 실행, Windows에서는 python 명령 사용
set PYTHONPATH=src
python -m ai_novel_factory.references.profile_cli --database ./references.sqlite3 usage-add fantasy
python -m ai_novel_factory.references.profile_cli --database ./references.sqlite3 usage-add fantasy --pattern-genre romance
python -m ai_novel_factory.references.profile_cli --database ./references.sqlite3 usage-list --genre fantasy
python -m ai_novel_factory.references.profile_cli --database ./references.sqlite3 usage-list --status stale
python -m ai_novel_factory.references.profile_cli --database ./references.sqlite3 usage-show 0123456789abcdef0123456789abcdef
python -m ai_novel_factory.references.profile_cli --database ./references.sqlite3 usage-delete 0123456789abcdef0123456789abcdef
```

위 UUID는 형식 예시일 뿐 실제 저장된 ID가 아니다. `usage-list`에서 실제 생성된 ID를 확인한다.

Windows GUI의 참고작 분석 페이지에 **사용 기록 / 사용 이력 보기 / 선택 기록 삭제** 컨트롤이 추가됐다. 현재 장르 선택을 기준으로 기록하고, 패턴 라이브러리에서 항목 한 개를 선택했으면 대상 장르로 연결해 기록한다. 수동 확인 없이 기록이 발생하지 않는다.

## 실제 검증

- Python **3.13.5**에서 `PYTHONPATH=src python -m unittest discover -s tests -q` → **886개 실행, 875개 통과, 11개 건너뜀, 실패 0개**.
- 이번 단계 **41개** 테스트 중 **40개 통과**, PySide6가 필요한 UI 테스트 **1개 건너뜀**.
- `PYTHONPATH=src python scripts/smoke_test.py`, `python scripts/check_dependencies.py`, `python -m compileall -q src tests` 성공.
- 네트워크 연결 차단, 파일명·원문을 이력 행에 보존하지 않음, 손상된 DB 데이터 거부, 복수 이력·삭제·상태 재검증, CLI 사용 흐름 검사.
- PySide6가 현재 개발 환경에 설치되지 않아 GUI 실기기 실행은 검증하지 않았다. Windows EXE도 빌드하지 않았다. 프로젝트 지정 Python **3.12** 검증과 실제 로컬 AI Writer 구현도 이후 단계에 남아 있다.

## 파일

- `src/ai_novel_factory/database/pattern_usage.py`: 저장·조회·삭제·검증·이력 보고서
- `src/ai_novel_factory/references/profile_cli.py`: `usage-*` 명령 연결
- `src/ai_novel_factory/desktop/reference_profile_browser.py`: 사용 기록 UI
- `tests/test_pattern_usage.py`: 오프라인 및 회귀 테스트

다음 38단계는 **원문 비복제 보호**다. 관련 검색·사용 기록이 원문 재생성이나 스타일 복제로 이어지지 않는 후속 보호장치를 구현한다.
