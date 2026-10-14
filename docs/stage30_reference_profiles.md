# Stage 30/100 — Reference Profile 저장·목록·표시 (PC 독립 실행)

## 범위

**기준 ZIP:** 29단계의 `AI_Novel_Factory_stage29_OFFLINE_ARCHITECTURE_FIXED.zip`에 있던 110개 파일.
GitHub 연동 없이 이 대화의 작업 공간에서 누적 개발한 30단계 파일이다.

1. `references/reference_profile.py` — 원고는 **메모리에서만** 분석하고, Stage 18·21·24·25·28·29 지표를 고정 스키마에 합쳐 프로필 생성.
2. `database/reference_profiles.py` — 기존 참고작 메타데이터의 SQLite 파일에 별도 `reference_profiles` 테이블(프로필 JSON, 버전 1, 생성 기준값 없음, 수정 시각만 저장). 원문, 대사, 특정 매칭 단어, 인물명 및 원본 디렉터리 경로는 저장하지 않음. 메타데이터의 *파일명(경로 제외)* 과 SHA-256 등은 Stage 19부터 존재하며 그대로 유지.
3. `references/profile_pipeline.py` — 원본 파일을 **한 번만 제한된 크기로 읽고**, 파싱·회차 분리·프로필 검증을 성공한 뒤 메타데이터와 프로필을 등록. 잘못된 파일일 경우 DB 미변경.
4. `references/profile_cli.py` — 서버 및 PySide6 없이도 등록, 목록, 보고서, 파생 프로필만 삭제 가능.
5. `desktop/reference_profile_browser.py` — 기존 참고소설 선택 UI에 로컬 SQLite 프로필 목록·조회 및 명시적 클릭에 따른 분석·저장 기능을 추가. **창을 열 때 분석/DB 파일 생성/외부 연결 없음.** Qt UI 검증은 Windows/PySide6 장치에서 추가 확인 필요.
6. 기존 `database/reference_catalog.py`에 `PRAGMA foreign_keys=ON`을 적용해 연결된 프로필의 FK 무결성을 보장.

## 실행 (Windows 터미널, Python 및 의존성 설치 필요)

프로젝트 최상위 폴더에서:

```powershell
$env:PYTHONPATH = "src"
python -m ai_novel_factory.references.profile_cli --database "$env:LOCALAPPDATA\AI Novel Factory\references.sqlite3" import "C:\사용자\참고작.txt"
python -m ai_novel_factory.references.profile_cli --database "$env:LOCALAPPDATA\AI Novel Factory\references.sqlite3" list
python -m ai_novel_factory.references.profile_cli --database "$env:LOCALAPPDATA\AI Novel Factory\references.sqlite3" show <등록_ID>
```

**주의:** CLI의 DB 부모 폴더는 미리 만들어져 있어야 한다. 예를 들어 처음 실행 전에
`New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\AI Novel Factory"`로 생성한다.
반면 PySide6 화면은 사용자가 버튼을 누를 때 로컬 데이터 폴더를 생성한다.

일반 검사:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -q
python scripts/smoke_test.py
```

TXT/Markdown, DOCX, PDF 지원. **EPUB는 기존 파서 누락으로 지원하지 않는다.**

## 프로필 버전 1 — 개인 정보·참고 원문 보호

저장 항목은 `source_format` (고정 enum), 전체·회차별 글자/문단/단어 수,
대사·서술 비율, 사건 후보 수·밀도, 말미 후보 고정 분류, 평균 문장 길이,
토큰 다양도, 감정/복선 단서 집계 등 **고정 이름과 유한 숫자/불리언**뿐이다.
`save()` 이전 스키마와 범위 검증을 수행하고, 읽을 때도 버전/스키마/값을 재검증한다.
SQL 파라미터 바인딩과 파일 크기 제한을 적용한다. SQLite 프로필은 약 2MB로 제한된다.

Stage 26~27 인물 분석에는 등장인물 이름 입력이 필요하므로, **해당 이름·별칭은
프로필에 넣지 않는다.** 수치 통계만 저장하는 형태를 유지한다.

## 데이터 정합성과 한계

- 원본 파일의 SHA-256을 메타데이터 등록 키로 사용하므로 같은 바이트 재등록은 한 프로필로 합쳐진다.
- 파일 분석에 실패하면 신규 메타데이터/프로필이 추가되지 않는다. 단, 디스크 오류로 저장 도중 실패하면 상태가 `analyzing`에 머무를 수 있고, 다음 분석 재시도로 회복 가능하다.
- 프로필만 삭제하면 기존 메타데이터는 유지한다. 반대로 메타데이터 행이 삭제되면 외래키 CASCADE로 파생 프로필도 삭제된다.
- 단순 정규식/키워드 기반 후보 지표이므로 실제 사건·클리프행어·서사 복선·감정 의미를 이해하는 로컬 LLM과 다르다.
- 긴 문서의 전체 분석은 GUI 메인 스레드에서 진행되어 **잠시 응답이 느려질 수 있다**. 진행 표시, 취소 버튼 등은 추후 개발 범위다.
- 기존 Stage 29 문체 분석은 문서의 정규화 텍스트가 200만 문자를 초과하면 거부한다. Stage 30에도 이 제한을 유지한다.
- Windows 실행 EXE/설치 파일, 로컬 모델 연동, 현장 GUI 검증은 별도 후속 단계다.
- 기존 전체 테스트 실행 시 SQLite 연결 미종료 ResourceWarning이 간헐적으로 발생할 수 있다. 새로운 저장소 자체 테스트는 context manager로 닫는다.

## 외부 시스템 없음

GitHub, 원격 DB, 클라우드 AI, 유료 API, Redis/Celery, 게시 API는
이 단계의 프로필 생성·저장·표시에 사용되지 않는다. 기존 선택형 `127.0.0.1`
진단 API도 이 단계에는 필요하지 않다. 사용자가 PC에서 계속 이용할 수 있도록
로컬 SQLite를 기본으로 유지한다.
