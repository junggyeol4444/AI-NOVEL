# 33/100 — Reference Pattern Library (완전 오프라인)

## 목적과 한계

32단계에서 **사용자가 직접 장르를 지정하고** 로컬 SQLite에 저장한 장르 패턴 선정 정보를 목록·검색·선택·상세·비교하는 읽기 전용 라이브러리를 구축한다. 참고소설 원문이나 파일 경로를 검색 색인에 복제하지 않는다. 통계가 특정 장르의 창작 공식이라는 뜻이 아니며, 특정 작가의 문장·장면·전개를 모방하는 기능이 아니다.

**실행 아키텍처:** Python 표준 라이브러리 및 기존 로컬 SQLite 파일만 사용한다. GitHub, 외부 DB, 클라우드 서버, 유료 AI API, 모델 파일 다운로드는 필요하지 않다. PySide6가 설치된 경우 기존 참고소설 화면에도 선택형 위젯이 나타난다. 별도의 서버를 시작하지 않는다.

## 파일 및 범위

- `src/ai_novel_factory/references/pattern_library.py`: `ReferencePatternLibrary.search/get/compare`, 목록·비교 데이터 모델, 원문 없는 보고서.
- `src/ai_novel_factory/references/profile_cli.py`: `pattern-list`, `pattern-show`, `pattern-compare` 명령 추가.
- `src/ai_novel_factory/desktop/reference_profile_browser.py`: 검색어 입력·검색 버튼·저장된 패턴 목록·단일 상세·복수 선택 비교.
- `tests/test_pattern_library.py`: 새 자동 테스트 54개(로컬 GUI 미설치 환경에서 1개 건너뜀).
- `docs/stage33_test_results.json`: 본 개발 환경에서 실제 실행한 검증 요약.

## 데이터 설계

**새 DB 테이블을 만들지 않는다.** 32단계 `genre_pattern_selections` 테이블을 기존 `GenrePatternStore.list_patterns()`로 읽는다. 목록의 상태(`current`)는 저장 당시 참고작 ID 집합과 현재 장르 분류의 ID 집합을 비교해 결정한다. 상세/비교를 요청할 때는 원문이 없는 `ReferenceProfile`에서 통계를 다시 계산한다. 따라서 이전에 삭제·이동·재지정한 참고작이 있으면 해당 패턴의 상세/비교는 중단하고 재구축을 요청한다.

검색은 미리 정해진 장르 코드 12개, 한글 장르 이름, `equal`/`characters` 문자열 **내에서만 수행**한다. 사용자 입력을 SQL에 붙이거나 파일명을 검색하지 않는다. 목록에는 `장르`, `가중치`, `참고작 수`, `최신/재구축 필요`만 나온다. 1회 검색은 최대 100개 목록을 반환하며 페이지 오프셋도 사용할 수 있다.

**비교 조건:** 현재 유효한 *서로 다른 장르* 2~12개, **동일 가중치**(`equal` 또는 `characters`)에 대해 6개 항목별 관찰 평균을 보여 준다. 여러 지표를 단위가 다른 상태로 합산하거나 우열 점수를 매기지 않는다. `characters` 패턴이 만들어지지 않았다면 `equal` 패턴을 자동 대체하지 않는다. 비교 결과에는 원문, 대사, 소설·작가 이름, 파일 경로가 없다.

## 명령줄 사용 (Windows PowerShell)

실행 전에 32단계 방식으로 참고작 2개 이상을 특정 장르에 지정하고 `genre-build`를 수행해야 한다. **비교하려면 다른 장르에도 2개 이상을 지정하여 별도 구축**해야 한다.

```powershell
$env:PYTHONPATH='src'
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 pattern-list
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 pattern-list --search 판타지 --status current
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 pattern-list --weighting characters --limit 20 --offset 0
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 pattern-show fantasy
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 pattern-compare fantasy romance
# 두 장르 모두 characters 방식으로 구축했을 경우에만 사용 가능
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 pattern-compare fantasy romance --weighting characters
```

`--status` 값: `all`(기본), `current`, `stale`. CLI 오류는 원문이나 DB 내부 값을 보여 주지 않고 간략한 한국어 오류 문구만 표시한다. GUI에서는 기존 참고소설 화면에서 **패턴 검색 → 목록에서 1개 선택·상세 또는 2~12개 선택·비교**를 사용한다. GUI의 패턴 검색 버튼을 눌러야 목록을 읽으며 백그라운드 동기화는 없다.

## 검증과 보류 사항

- 개발 환경 Python 3.13.5: 누적 `unittest` 716개, 709개 통과, 7개 건너뜀, 실패 0개. 33단계 신규 54개 중 53개 통과, PySide6 GUI 1개 건너뜀.
- 로컬 DB를 종료하고 다시 열어도 패턴 목록·비교를 재구성할 수 있으며, 원본 소설 파일을 제거한 뒤에도 이미 저장된 통계가 있다면 조회 가능함을 검증.
- 소켓 연결을 패치해 차단한 상태에서 검색·비교 성공, SQL 주입 모양의 잘못된 검색·분류 입력 차단, 오래된 패턴 거부, 읽기 호출에서 SQLite 레코드 변경 없음을 검사.
- 스모크 검사 필수 항목 및 의존성 정책 검사 통과.
- PySide6가 설치된 **Windows 실기기** GUI 동작·실제 Windows EXE 빌드/실행은 검증하지 않음. 실제 로컬 모델을 통한 의미 이해/집필도 아직 구현하지 않음.
- 기존 32단계 설계의 사용하지 않는 원격 서비스용 선택 의존성은 여전히 `pyproject.toml`에 있어 추후 정리가 필요함. 그러나 33단계 실행에는 사용되지 않음.

## 다음 단계

**34/100 — 참고 작품별 패턴 강도 설정:** 특정 참고작 또는 장르 패턴의 영향 강도를 제한된 범위로 사용자가 조절하고, 원문 복제 방지 정책을 유지하도록 이어서 개발한다.
