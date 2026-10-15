# AI NOVEL FACTORY — 다음 대화 전체 개발·검증 인수인계

## 2026-10-16 오전 추가 — Windows 3377 전체 검증 실패의 직접 근거와 SQLite 잠금 처리
- [전체 CI #38822819078](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38822819078): 기존 한 프로세스 실행 Linux 3389 tests, 4 FAIL; Windows 3377 tests, 5 FAIL + 21 ERROR + 2 SKIP, 따라서 전체 검증 FAIL. Windows 21 오류의 실제 로그는 테스트 임시 SQLite 파일에서 `PermissionError: [WinError 32]`. `with sqlite3.connect(...) as conn`이 **트랜잭션만 종료하고 연결은 닫지 않는다**는 점을 반영하여 SQLite 검사/마이그레이션 제품 코드 및 해당 합성 테스트들에 `contextlib.closing` 추가. 재시작 후 기존 데이터는 임의 변경하지 않음.
- Windows 추가 FAIL: `test_stage96_platform_format_audit` POSIX `stat().st_mode & 0o777==0o600`은 NTFS DACL 권한 기준과 동일하지 않아 Windows만 명시 SKIP (별도 실제 Windows ACL 검증은 여전히 NOT_RUN; 보안 합격 주장 금지). Test reopened store에서 새 연결을 cleanup에 등록하지 않는 문제도 수정.
- 후속 후보는 Python 전체 테스트를 실행시키되 Windows에서는 각 `test_*.py` 모듈을 독립 프로세스로 기한 150초, 개별 결과/log와 summary JSON으로 보존하고 전체를 탐색한다. Linux는 한 프로세스 테스트도 유지하여 cross-test 결함을 계속 감지. 후보 CI 결과가 종료 전까지 PASS 선언 금지.
- #38822818948 실제 Windows GGUF 네이티브 종료 코드 `3221226356`(heap corruption)에 대한 **가설적 완화로 단일 스레드/단일 배치 스레드 사용**을 후보로 시험한다. 기존 런타임 결함을 해결했다고 단정하지 않으며 반복 CI 결과를 확인해야 한다.


## 2026-10-16 — EPUB 참고작 입력 실제 파이프라인 통합 후보 (최종 CI 검증 대기)

- 이 변경은 `references/epub_parser.py`의 방어적 ZIP/OPF/XHTML spine 파서 및 합성 테스트를 실제 import→Reference Profile→SQLite 연결 경로에 추가하고 Linux·Windows 검증 워크플로에 신설 테스트를 포함한다. 참조 문장·설정은 프로필/SQLite에 저장하지 않고 합성 EPUB만 시험한다.
- 단독 합성 파서 검사 28/28 PASS. 새 저장소 전체 통합 테스트와 Windows 실제 실행은 해당 신규 CI 로그가 종료되기 전까지 NOT_RUN/UNVERIFIED. 코드 커밋만으로 기능 전체 합격 또는 릴리스 합격 금지.
- 기존 기준 CI Linux Qt #38749433138, Windows Qt #38749433653, PG/Redis/Celery #38749433240, Windows EXE/GGUF #38749433656 PASS, Windows11 UIA #38749433493 FAIL: 12개 메뉴 조작 PASS, WWAHost 전경 점유로 실제 전경 인수 FAIL. 물리 Windows 사람 인수·전체 Similarity/수정 재검사·실 모델 장편 품질·01~100 완료는 RELEASE_BLOCKED.


## 2026-10-16 08시 KST — EPUB DEFLATE 손상 오류 수정 (로컬 검증, 원격 코드 미반영)

- 기준 validation 브랜치 HEAD `478b16f614db2f1d82c0a0ec96416acb5ddf8ff3` (GitHub compare `identical`), 보호 main `69225edeed0a09ded5f847dad9b9ea63bc45367c`. 기존 CI Linux Qt #38749433138, Windows Qt #38749433653, PG/Redis/Celery #38749433240, Windows EXE/GGUF #38749433656 성공; Windows 11 외부 UIA #38749433493 실패(선택 12/12 PASS, OS `WWAHost` 전경 점유 및 `QtForeground=False`). 기존 CI 결과이지 이번 EPUB 후보 CI가 아님.
- 이전 로컬 EPUB 후보에서 실제 손상된 DEFLATE 데이터를 파싱하면 `zlib.error`가 `ReferenceParseError`로 변환되지 않는 예외 누출을 합성 ZIP 변이로 재현. 파서 except에 `zlib.error`를 추가하고 DEFLATE 손상 회귀 테스트 1개를 추가.
- 단독 합성 파서 테스트 **28/28 PASS**, Python compileall PASS. 고정 시드로 DEFLATE 바이트 1,000개 변이 검사: 안전 거부 985, 허용 15, 미처리 예외 0. 이는 일반 보안 증명이 아님. 새 프로젝트 전체 테스트 20개는 **NOT_RUN** (격리 실행 환경에는 실제 전체 저장소 패키지가 없음), 실제 GUI·Windows 신규 CI도 NOT_RUN.
- 변경 코드 및 테스트는 대화 첨부 `anf_run15_epub_deflate_safe_local.zip`에만 존재하며 원격 소스 파일에 반영되지 않음. 기존 사용자의 원고/SQLite/비밀키/설정/실계정/게시/예약 접근·변경 없음. 물리 Windows 전경 인수, 30·100·250화×5000자 문학 품질, 참고작 전수 Similarity·위험 장면 재검사, 전체 01~100 인수가 남아 `RELEASE_BLOCKED`.


## 2026-10-15 23시 KST — 신규 Windows Qt 실패 즉시 수정 및 전경 점유자 확인

- 직전 검증 커밋 [`37887965`](https://github.com/junggyeol4444/AI-NOVEL/commit/37887965be327571aa9dcf56b4ad5fa93ff84843)의 Linux Qt [#38748476593](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38748476593), PG/Redis/Celery [#38748476562](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38748476562), Windows EXE·실 로컬 GGUF [#38748476575](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38748476575) **SUCCESS**. Linux Qt에서 새 `test_reference_coverage.py` 8개 전부 실행·통과 로그 확인.
- Windows fast Qt [#38748476764](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38748476764) **FAILURE**: 새 합성 SQLite 테스트 8개가 `PermissionError: [WinError 32]`로 정리 실패. 원인은 테스트의 `with sqlite3.connect(path) as db:`가 커밋만 하고 연결은 닫지 않아 Windows에서 `TemporaryDirectory` 삭제 시 DB 파일 잠금 유지. 제품의 `read_reference_coverage`는 이미 `closing(...)`을 사용함.
- 회귀 테스트 7곳을 `with closing(sqlite3.connect(path)) as db, db:`로 변경하여 **트랜잭션 커밋 후 연결 명시 종료**. Linux 격리 합성 SQLite 7 PASS, GUI 1 SKIP(PySide6 미설치), compileall PASS. 수정된 테스트의 신규 Windows CI 결과는 실행 완료 전 **NOT_RUN**.
- Windows 11 외부 UIAutomation [#38748476592](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38748476592) **FAILURE**: `SelectedUnique=12`, `NativeSelectionClicks=12` PASS, `ForegroundRequestAccepted=False`, `QtForeground=False`, `ForegroundBlockerProcess=WWAHost; ForegroundBlockerPid=7580` 확인. Windows Web App Host가 전경을 점유한 것은 확인됐지만 화면의 구체적인 내용은 해당 실행 로그만으로 단정하지 않음. OS 창 강제 종료/우회 금지, 전경 실패 판정 유지.
- 보호 `main` SHA `69225edeed0a09ded5f847dad9b9ea63bc45367c` 불변. 기존 사용자 데이터/키/설정/계정/예약 변경·전송·재활성화 없음. **RELEASE_BLOCKED**: 물리 Windows 10/11 사람 인수, 참고작 전수 Similarity/재작성, 실 모델 30/100/250화 장편 품질, 01~100 통합/명시 승인 후 출판 미완.

## 2026-10-15 23:04 KST — 로컬 보강 재검증 및 Windows 11 전경 진단 (검증 브랜치 전용)

- 검증 HEAD `1fcd2397d2ef408e30057d53ec174f01bccc05cd`, 보호 `main` `69225edeed0a09ded5f847dad9b9ea63bc45367c` 읽기 재확인. 해당 HEAD Linux Qt #38724889966, Windows Qt #38724889882, PG/Redis/Celery #38724890183, Windows EXE/GGUF #38724889916 모두 SUCCESS; Windows 11 외부 UIAutomation #38724889869 FAILURE (실제 잡 로그 확인).
- Windows 11 실패 로그: `SelectedUnique=12`, `NativeSelectionClicks=12` PASS, `QtForeground=False` FAIL. OS 개인정보/OOBE 점유는 추정이지 이번 로그로 확정되지 않음. 구형 Windows EXE #38701708258 SUCCESS 확인.
- 기존 로컬 패치의 참고작 상태 이상/NULL `INVALID_STATUS` + `NOT_RUN`, Linux/Windows Qt CI 테스트 연결, Windows 11 `ForegroundRequestAccepted` 및 실제 전경 점유 프로세스 이름/PID 진단을 통합. 실제 OS 창 강제 종료/우회 없음, 전경 실패 판정 유지.
- 격리 합성 SQLite Python 단위 테스트 **7 PASS / 1 SKIP(PySide6 미설치)** 및 compileall PASS. Windows 11 진단 코드 실제 실행은 신규 CI 완료 전 **NOT_RUN**. 실제 전수 유사성 검사는 **NOT_RUN**.
- **RELEASE_BLOCKED** 유지: 물리 Win10/11 사용자 전경 인수, 등록 참고작 전수 검사/위험 장면 재작성, 실제 30/100/250화×약 5000자 문학 품질, 01~100 통합, 승인 후 출판 미완. 사용자 원고/SQLite/키/계정/기존 예약과 보호 main 변경 금지.

## 2026-10-15 20:02 KST — 등록 참고작 범위 읽기 전용 표시 연결 (검증 브랜치 전용)

- 시작 상태: 검증 브랜치 `15cae25ed12d6dbaa8a86d7768c27cde8b8348cd`, 보호 `main` `69225edeed0a09ded5f847dad9b9ea63bc45367c` 확인. 검증 브랜치 최근 5개 CI 모두 종료, 진행 중인 검증 없음. [Linux Qt #38713802843](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802843), [Windows Qt #38713802611](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802611), [실 PG/Redis/Celery #38713802634](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802634), [Windows EXE/로컬 GGUF #38713803500](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713803500) **PASS**. [Windows 11 외부 UIA #38713802649](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802649) **FAIL**: 12/12 UIA 메뉴 선택 PASS, 실제 OS 전경 인수는 Windows 11 OOBE 개인정보 설정 화면으로 **BLOCKED**. 구형 #38701708258은 SUCCESS 확인.
- 신규 코드: `desktop/reference_coverage.py`는 기존 로컬 `reference_files` 테이블의 전체 등록/분석 완료 메타데이터 건수만 SQLite `mode=ro`로 조회. 파일이 없으면 0건이라고 단정하지 않고 `MISSING` 처리, 스키마 오류/상대경로/심볼릭 링크는 `NOT_RUN`으로 실패 닫힘. 기존 DB 테이블 생성/수정, 원문 접근, 외부 전송 없음.
- `desktop/additional_workspaces.py` 유사성 검사 화면에 **사용자가 직접 누르는** '로컬 등록 참고작 범위 확인 (읽기 전용)' 버튼과 결과 라벨 추가. 분석 완료 건수와 **전수 유사성 검사 NOT_RUN**을 명시적으로 분리. 이는 자동 전수 유사성 검사 기능을 구현했다는 의미가 아니다. `scripts/reference_coverage_cli.py`는 같은 메타데이터를 명시 경로에서 로컬 확인.
- 로컬 합성 SQLite 테스트 `tests/test_reference_coverage.py`: **5 PASS, 1 SKIP(PySide6 미설치)**; Python compileall PASS. Windows GUI 선택 버튼은 새 CI에서 확인해야 하며, 이번 코드 커밋의 CI 성공은 실행 전까지 주장하지 않는다.
- 여전히 **RELEASE_BLOCKED**: 실제 등록 참고작 원문 전수 비교, 30/100/250화 실모델 장편 품질, 물리 Windows 10/11 사람의 전경 인수, OOBE 차단, 01~100 통합 및 승인 후 출판 미완. `main`/사용자 원고·SQLite·키/외부 계정/기존 예약 변경 금지.

---

## 2026-10-15 18:30 KST 정기 실행 — Windows 11 UIA 스크롤 불가 원인 확인 및 GUI 공간 수정

- 검증 브랜치 HEAD 확인: `e24a17100cc2f40437d1c0bb51ce01e6d4960f82`; 보호 `main` SHA `69225edeed0a09ded5f847dad9b9ea63bc45367c` (ahead 158, behind 0). 신규 예약 생성·기존 예약 변경 없음.
- 같은 HEAD의 [Windows 11 외부 UIA #38712716301](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38712716301) **FAIL** (실제 잡 로그 확인): `AdvancedMenuControlType=ControlType.CheckBox`, `NativeSidebarFound=True`, `NativeSidebarScrollAvailable=False`, `NativeSidebarScrollBarCandidates=1`, `NativeSidebarRangeScrollAvailable=False`, `SelectedUnique=5`, `NativeSelectionClicks=5`. 12개 중 화면에 노출된 5개만 선택되어 화면 캡처·전경 단계까지 진행하지 못했다. UIA 스크롤바 후보는 있으나 RangeValue 사용 불가.
- 동일 SHA의 [Linux Qt #38712716315](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38712716315), [Windows fast Qt #38712716351](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38712716351), [실 PG/Redis/Celery #38712716292](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38712716292), [Windows EXE/로컬 GGUF/Windows11 오프라인 #38712716317](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38712716317)는 잡별 **SUCCESS** 확인.
- 이번 수정: `desktop/app.py`의 세부 도구를 펼칠 때 기본 5개 작업 버튼을 일시 숨겨 전문 메뉴 12개에 전체 높이를 배정하고, 메뉴 행/여백을 줄여 최소 820×560 창에서도 모두 보이게 한다. 닫으면 기본 작업 버튼을 원상 복구한다. `tests/test_desktop_gui_optional.py`에서 Qt 최소 창 실제 렌더 기준 모든 12개 `visualItemRect`의 viewport 포함 여부와 스크롤 최대값 0, 토글 복원을 검증한다. 이는 UIA에 없는 스크롤 패턴을 우회하기 위한 **GUI 레이아웃 수정**이며 사용자 데이터·DB·게시 기능은 변경하지 않는다.
- **커밋 [`ca7b4442`](https://github.com/junggyeol4444/AI-NOVEL/commit/ca7b4442ab36ddc708c1a679c759c99b7fc5e442) 실제 CI**: Linux Qt [#38713802843](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802843), Windows Qt [#38713802611](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802611), 실 서비스 [#38713802634](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802634), EXE·로컬 GGUF·Windows11 오프라인 [#38713803500](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713803500) **SUCCESS**. 최소 820×560 Qt 화면의 전문 메뉴 12개 전부 viewport에 들어오고 스크롤 불필요한 테스트 PASS.
- Windows11 외부 UIA [#38713802649](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802649)는 **부분 PASS / 전체 FAIL**: `NativeSelectionClicks=12`, `SelectedUnique=12`, `PublicationPageActionsVisibleViaUIA=3`, 프로젝트 홈 복귀와 실제 Qt HWND Win32 캡처 PASS. 그러나 `QtForeground=False; ForegroundHandle=66058`. [실제 데스크톱/Qt 창 이미지 아티팩트](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38713802649/artifacts/11961499504)를 내려받아 육안 확인: OS 데스크톱은 Windows11 첫 실행 개인정보 선택(OOBE) 화면에 가려져 있고, Qt 창 이미지는 PrintWindow 캡처다. 12/12 OS UIA 메뉴 선택 결함은 해결됐지만 사람의 실제 전경 GUI 인수는 **FAIL/BLOCKED**.
- 다음 회차: disposable Windows11의 첫 실행 화면 차단을 안전하게 처리할 방법 검토. 물리 Win10/11 사람의 전경 인수, 장편 30/100/250화 문학 품질, 참고작 전수 Similarity, 01~100 통합 미완으로 **RELEASE_BLOCKED**. `main`/사용자 DB·원고·비밀키·실게시·출판·기존 자동화 변경 없음.

---

## 2026-10-15 18시 KST 후속 Windows 11 스크롤 패턴 부재 — UIA RangeValue 대체 구현

- [스크롤 탐색 수정 `50cb1a8a5ab0cc77f0ec5ef1b905b63af29fd30e`](https://github.com/junggyeol4444/AI-NOVEL/commit/50cb1a8a5ab0cc77f0ec5ef1b905b63af29fd30e)에서 [Windows 11 UIA #38711946763](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711946763) **FAIL**: `NativeSidebarFound=True`, `NativeSidebarScrollAvailable=False`, `SelectedUnique=5`, `NativeSelectionClicks=5`. 실제 Qt `QListWidget`의 가시 5개 행을 선택했으나 Windows UIA ScrollPattern은 지원되지 않아 추가 탐색 불가.
- 이번 변경은 정확히 식별된 `sectionSidebar`의 자손 또는 **사이드바 화면 영역 안에 위치한** OS UIA `ControlType.ScrollBar`를 찾고, `RangeValuePattern`이 쓰기 가능하면 큰 단계로 값을 올려 아래쪽 행을 표시한 뒤 목록을 다시 검색한다. ScrollPattern 지원 시 기존 경로 유지. UIA ScrollBar/RangeValue 지원 여부와 각 이동 수치만 기록하고, 12개 메뉴 각각의 `SelectionItemPattern.Select()` 성공을 요구한다. 패턴이 없으면 **FAIL**, OS 전경/실사용자 인수 PASS 주장 금지. 정적 회귀 검사에 RangeValue 경로 추가.
- 같은 SHA의 [Linux Qt #38711946732](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711946732), [Windows fast Qt #38711946817](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711946817), [PG/Redis/Celery #38711946780](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711946780), [Windows EXE/로컬 GGUF/Windows11 오프라인 #38711946757](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711946757) 모두 **SUCCESS**. 장시간 Windows 검증 종료 후에만 후속 변경 커밋. 신규 RangeValue 대체 변경의 CI는 아직 미확정이며 다음 회차에서 로그로 판정해야 한다.
- 제품 상태 **RELEASE_BLOCKED**: 물리 Windows 10/11 사람의 전경 인수, Windows 11 privacy/OOBE 차단, 전수 참고작 Similarity, 장편 30/100/250화×약 5000자 창작 품질, 01~100단계 통합 미완. `main`/실사용자 원고·DB·키/실계정/출판/기존 예약 무단 변경 없음.

---


## 2026-10-15 18시 KST 후속 Windows 11 UIA 스크롤 탐색 결함 — 12개 메뉴 전수 선택 수정

- [Qt `toggled` 신호 수정 `20844ccc2baee2d2cf7e932f47133237c4987c56`](https://github.com/junggyeol4444/AI-NOVEL/commit/20844ccc2baee2d2cf7e932f47133237c4987c56) 이후 [Windows 11 외부 UIA #38711139707](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711139707) **FAIL**: `AdvancedMenuControlType=ControlType.CheckBox`, `AutomationElements=126; MatchedMenuItems=6; NativeSelectionClicks=5`. 이전 1개/0회에서 개선되어 UIA 체크 상태와 실제 Qt `sidebar.setVisible` 연결은 작동했지만, **화면에 보이는 약 5개 행만 선택하고 스크롤 밖 나머지 행을 놓침**. UIA가 리스트의 가시 행만 노출하는지 여부는 다음 실행에서 스크롤 패턴 진단으로 확인해야 한다.
- 이 후속 변경은 `ci_windows11_desktop.ps1`에서 `sectionSidebar` AutomationId 또는 UIA List와 기존 메뉴 이름으로 실제 사이드바를 식별하고, 지원되는 **OS UIAutomation ScrollPattern**으로 목록을 아래로 스크롤하면서 UIA 트리를 다시 조회한다. 12개 서로 다른 메뉴 이름 각각에 `SelectionItemPattern.Select()`가 성공해야 통과한다. 진단은 `NativeSidebarFound`, `NativeSidebarScrollAvailable`, `NativeSidebarPass`, `NativeSidebarScrollPercent`, `SelectedUnique` 등 구조적 수치만 기록하며 원고·입력값·DB 경로는 출력하지 않는다. `tests/test_desktop_navigation.py`에 스크롤 탐색 코드 정적 회귀 검사 추가.
- 두 번째 수정 SHA의 나머지 CI는 [Linux Qt #38711139813](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711139813), [Windows fast Qt #38711139681](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711139681), [PG/Redis/Celery #38711139686](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711139686), [Windows EXE/실 로컬 GGUF/Windows11 오프라인 #38711139677](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38711139677) 모두 **SUCCESS**. 해당 장시간 Windows11 오프라인 검증 종료를 확인한 후에만 이 후속 커밋을 진행했다.
- 이번 스크롤 수정의 신규 Windows CI 결과는 아직 미검증. ScrollPattern 미지원 또는 목록 끝 도달로 12개를 찾지 못하면 명시적 **FAIL**로 남겨야 하며 합격 처리 금지. OOBE/privacy 전경 가림, 물리 Windows 10/11 사람의 전경 인수, 장편 품질·참고작 전수 검사·01~100 전체 연결은 계속 **RELEASE_BLOCKED**. 오직 검증 브랜치만 수정, `main`/실사용자 데이터/실계정/출판/기존 예약 불변.

---


## 2026-10-15 18시 KST 정기 실행 후속 결함 수정 — UIA TogglePattern과 Qt `toggled` 신호 연결

- 검증 브랜치 [첫 수정 `951a83d71cc953c234a17ee08f0b1c7074e8b9c9`](https://github.com/junggyeol4444/AI-NOVEL/commit/951a83d71cc953c234a17ee08f0b1c7074e8b9c9) 후 실제 CI를 기다려 확인했다. [Windows 11 외부 UIA #38710410703](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38710410703) **FAIL**: 기존 메뉴 제어 실패 단계는 통과해 `AdvancedMenuControlType=ControlType.CheckBox`가 실제 로그로 확정됐으나, `AutomationElements=120; MatchedMenuItems=1; NativeSelectionClicks=0`으로 **실제 사이드바가 펼쳐지지 않음**. 단순 UIA 패턴 성공은 화면 동작 증거가 아니다.
- 원인 가설(신규 Windows 11 CI 검증 필요): Qt `QPushButton.setCheckable(True)`에 대해 UIA `TogglePattern.Toggle()`이 `checked` 상태만 바꾸고 `clicked`는 발생시키지 않을 수 있다. 기존 `app.py`는 `clicked.connect(self._toggle_advanced_navigation)`에만 연결돼 있어 실제 `sidebar.setVisible(expanded)`가 누락된다. 이번 수정은 **`toggled.connect`로 연결을 변경**해 UIA 체크 상태 변화와 마우스/키보드 클릭을 모두 지원하도록 한다. `tests/test_desktop_gui_optional.py`에 `setChecked(True/False)`로 펼침·접힘과 접근성 버튼 문구를 실제 Qt 위젯에서 검증하는 회귀 테스트를 추가했다.
- 첫 수정 SHA의 나머지 CI: [Linux Qt #38710410754](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38710410754) **SUCCESS**, [Windows fast Qt #38710410622](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38710410622) **SUCCESS**, [실 PG/Redis/Celery #38710410467](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38710410467) **SUCCESS**, [compiled Windows EXE/로컬 GGUF/Windows11 오프라인 #38710410488](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38710410488) **SUCCESS**. 마지막 Windows 빌드까지 **완료를 확인한 후** 두 번째 커밋을 작성해 진행 중 빌드 취소를 피했다.
- 이번 두 번째 수정의 신규 CI 결과는 아직 미확정. 다음 회차에서 `MatchedMenuItems`, `NativeSelectionClicks`, `PublicationPageActionsVisibleViaUIA`, `QtForeground`를 실제 로그로 확인하라. Windows 11 OOBE/privacy 오버레이 및 물리 Windows 10/11 인간 전경 인수, 30/100/250화 문학 품질, 등록 참고작 전수 검사, 100단계 완전 통합은 **RELEASE_BLOCKED**. 검증 브랜치만 수정, `main`/사용자 원고·SQLite/실계정/실출판/기존 예약 변경 없음.

---


## 2026-10-15 18시 KST 정기 실행 1회차 — Windows 11 UIA 메뉴 제어 결함 수정 및 재검증 요청

- 사용자가 2026-10-15 한국시간에 명시적으로 `예약`을 지시해 **매시간 개발·검증 정기 작업 1개가 이미 생성/활성화**되었다. 아래 이전 인수인계의 '예약 없음/아직 생성 안 함' 문장은 과거 시점의 기록이다. 추가 예약 생성/기존 비활성 오전 8시 예약 재활성화 금지.
- 작업 전 확인: 검증 브랜치 HEAD `155194488db3f864caa0dbc4b21aa0f820e19de4`, `main` HEAD `69225edeed0a09ded5f847dad9b9ea63bc45367c`. GitHub Actions [Windows 11 외부 UIA #38701708179](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38701708179)는 **FAIL**: x64 EXE 빌드, offscreen 12화면, 외부 UIA 새 작품/원고 저장/종료/재시작/SQLite·Bible 복원 단계는 PASS, 별도 `ci_windows11_desktop.ps1`의 고급 12개 메뉴 펼치기에서 `AdvancedMenuButtonCandidates=1` 이후 실패. [Windows EXE + 로컬 GGUF #38701708258](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38701708258)는 빌드/실 모델/오프라인 Windows11 단계 모두 **SUCCESS**. 같은 SHA의 Linux Qt #38701708195, Windows fast Qt #38701708202, PG/Redis/Celery #38701708227 **SUCCESS**.
- 원인 가설(Windows 실행 재검증 필요): `app.py`는 `showAdvancedNavigationButton`을 `setCheckable(True)`한 `QPushButton`으로 만든다. 이전 PowerShell은 정확한 이름/ID로 요소 1개를 찾았으나 `ControlType.ProgrammaticName -notlike '*Button'`일 때 **TogglePattern/InvokePattern을 검사하기도 전에 건너뛰었다**. Qt의 체크 가능한 버튼은 Windows UIA에서 `ControlType.CheckBox`로 노출될 수 있다. 현재 변경은 정확히 일치한 접근성 요소에 대해 ControlType 선필터를 제거하고 TogglePattern 우선, InvokePattern 대체를 시도하며, **확장·축소 각각의 실제 ControlType만** 안전하게 로그에 남긴다. 원고·DB·입력값 로그 금지 유지. 정적 회귀 검사도 추가했다.
- **이번 커밋의 Windows UIA/전경 CI 결과는 아직 검증 전이므로 PASS 주장 금지.** 다음 회차에서 신규 Windows11 Actions run의 `AdvancedMenuControlType`, `MatchedMenuItems`, `NativeSelectionClicks`, `PublicationPageActionsVisibleViaUIA`, `QtForeground`와 실패 단계·아티팩트를 확인하라. OOBE/privacy 전경 가림, 물리 Win10/11 사람의 인수, 30/100/250화×약 5000자 문학 품질, 전수 참고작 Similarity/100단계 통합은 여전히 **RELEASE_BLOCKED**. `main`/실사용자 데이터/실계정/출판은 변경하지 않았다.

---


## 2026-10-15 후속 실개발·최신 CI 성공 — 검증 SHA 8e0d87e (신규 대화 우선 확인)

- 사용자 `계속`의 뜻은 이 자리에서 실제 개발·검증 계속하기이며 **예약/자동화가 아니다**. 향후 사용자가 정확히 `예약`이라고 지시할 때만 그 시점 한국시간 1시간 후 시작, 매시간 반복하는 작업을 만들어야 한다. 아직 **신규 자동화 생성 안 함**. 이전 비활성 오전 8시 예약 재활성화 금지.
- 최신 기능 수정 [`db0f99a82032e03cd72eb91fd2e09fa97633c5e3`](https://github.com/junggyeol4444/AI-NOVEL/commit/db0f99a82032e03cd72eb91fd2e09fa97633c5e3): `src/ai_novel_factory/desktop/authoring_session.py`에서 기존 작품 SQLite를 선택할 때 `get_project`, `list_rules`, 현재 회차/장면/검수 기록까지 **기존 작품 세션을 닫기 전 사전 조회**. 중간 실패 시 기존 선택 작품/회차/`pending_draft` 보존. `tests/test_authoring_session_safety.py`에 세 종류의 합성 손상 규칙/검수 메타데이터 예외 회귀 검증. 사용자 파일 변경 없이 합성 DB로 확인.
- 최신 CI 시작 커밋 [`8e0d87e210bd7b1372e61b0112320c8673e4f58a`](https://github.com/junggyeol4444/AI-NOVEL/commit/8e0d87e210bd7b1372e61b0112320c8673e4f58a): 두 Windows 검증 워크플로에서 **Windows 빌드·스모크 로그 및 실행 보고서만** `if: always()` 아티팩트로 보존하도록 변경(원고/DB/키/실 GGUF 모델 업로드 금지). 직전 스크립트 `_run_logged`/타임아웃 변경도 함께 실제 CI 검증을 위해 `[skip ci]` 없는 이 단 한 번의 검증 커밋에 포함.
- **이 SHA 8e0d87e에서 실제 성공 확인:**
  - [Linux Qt & synthetic data safety #38700360880](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38700360880) **SUCCESS**.
  - [Windows fast Qt·SQLite·원고 TXT·레거시 DB #38700360830](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38700360830) **SUCCESS**. 실제 GUI Qt 위젯 클릭·버전 저장/복원 등 보조 테스트 성공이나 포그라운드 Windows 사용자 인수 아님.
  - [PG/pgvector/Redis/Celery #38700360855](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38700360855) **SUCCESS**.
- **아직 결과 미확정:** [Windows 11 실제 GUI #38700361014](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38700361014)는 `qa-exe-x64-build` 단계에서 `IN_PROGRESS`; [compiled Windows EXE + real local GGUF #38700360835](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38700360835)는 의존성 설치/이후 EXE 빌드·검증을 수행할 예정. 최신 상태를 가장 먼저 재조회해 결과와 로그/아티팩트 확인. **미완료 PASS로 주장 금지**.
- 이전 SHA `6a18d9ca`의 Windows 11 GUI [#38694356766](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356766)는 `CANCELLED`/후속 검증 `SKIPPED`; compiled GGUF [#38694356849](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356849)도 장시간 빌드 진행이었고 새 커밋에 따른 취소 가능성이 있으므로 최신 job 결론 재확인. 취소를 사용자 사용승인 실패/합격으로 오해하지 말 것.
- `main`은 재확인 시 정확히 `69225edeed0a09ded5f847dad9b9ea63bc45367c`, 절대 변경·병합·삭제 금지. 사용자의 실제 원고·SQLite·환경설정·비밀키·연동 앱·실계정·출판/기존 자동화 무단 변경 없음.
- **현재 상태 `RELEASE_BLOCKED`.** 실제 Windows 10/11 네이티브 물리 PC 사용자 전경 검증, 기존 OS OOBE/개인정보 오버레이, 전 참조작 유사성, 01~100 완전 통합 및 30/100/250화×약 5000자 문학 품질 미완. 새 스크립트나 문서가 완료/출시 증거가 아니다.

---


## 2026-10-15 후속 대화 실제 개발·Windows 빌드 검증 추가 (원본 아래 전문 유지)

- 사용자는 현재 대화의 "계속"을 **즉시 개발**로 정의. 새로운 "예약" 지시가 들어올 때만 **그 시점 KST 기준 1시간 후 첫 실행 및 이후 매시간** 정기 작업을 설정하기로 새로 지시함. 아직 예약 요청은 없으므로 신규 예약은 만들지 않았다. 기존 비활성화된 오전 8시 일일 자동화도 건드리지 않았다. 반복 자동화는 새 지시가 들어오는 미래 시점에만 만들 것.
- 검증 브랜치 `validation/gui-authoring-e2e-20261014`, `main` 보호 SHA `69225edeed0a09ded5f847dad9b9ea63bc45367c` 재확인. 실사용자 SQLite/원고/키/환경설정/게시/출판 변경 없음.
- **커밋 `e3f7b549f8fa6cb64fdab79257ab660d49d155b2`:** `scripts/ci_windows11_external_authoring.ps1`에서 Windows UIA 대체 접근성 이름 2개를 실제 `project_studio.py` 라벨(`작가/필명 (선택)`, `최상위 작품 설정 *`)과 일치시킴. 이름 5개를 정적으로 비교해 일치 확인. 실제 Windows UIA 실행 PASS를 주장하지 않는다.
- **커밋 `24c08f17f3323381091cc9d4993da9f8ad650dc1`:** `authoring_workflow.py`의 기존 SQLite 열기/동기화가 누락된 오래된 `author` 및 `premise` 규칙에서 예외를 내지 않도록 읽기 전용 빈 값 대체. `project_studio._open_path` 오류 시 고급 도구의 DB 경로를 실제 열린 세션/기존 값으로 되돌리고 미저장 원고 보존. `tests/test_studio_gui_optional.py`에 합성 레거시 DB와 잘못된 경로 회귀 검사 추가. 새 코드의 Windows CI 실행은 아직 미검증.
- **Windows 11 실제 Actions run [38694356766](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356766):** 2026-10-15 16:15 KST 무렵 `CANCELLED`. `qa-exe-x64-build`에서 `Build unsigned x64 Windows EXE`가 약 29분 동안 추가 출력 없이 지속되다가 설정된 잡 30분 제한 무렵 취소. 후속 Windows 11 UIA·전경 검사 잡은 `SKIPPED`. 로그에 `The operation was canceled`와 종료 시 `AI_Novel_Factory` orphan 프로세스 청소가 있음. 정체 원인 확정은 금지. 새로운 코드나 물리 Windows PC의 합격 근거가 아님.
- **커밋 `49b9b449747f1940aff69b757cb7dad48e3122ea`:** 빌드 정체 대응으로 `scripts/build_windows_exe.py` PyInstaller·EXE smoke의 `capture_output` 파이프 수집 대신 새 파일 직접 리디렉션(`xb`)을 사용. Windows PyInstaller onefile 부트로더 자식이 타임아웃 뒤 파이프 EOF를 붙잡는 경우 무한 대기 위험 완화, 단계별 `ANF_WINDOWS_BUILD_STEP` 표식·900초 빌드 타임아웃 보고를 추가. `tests/test_stage97_windows_packaging.py`에 출력·덮어쓰기·타임아웃 격리 검사 추가. 실제 Windows 새 빌드/검증이 필요하며 원인 확정과 성공 선언 금지.
- 기존 장시간 [compiled Windows EXE+GGUF run 38694356849](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356849)는 최종 확인 시 `IN_PROGRESS`, 구 코드 `6a18d9ca`의 `Build actual Windows EXE` 단계. 이 실행에서 새 3개 코드 커밋이 검증되는 것은 아니다. 상태·실패 로그를 재확인해야 한다.
- 세 커밋 모두 장기 러너 취소를 피하려고 `[skip ci]` 적용. 따라서 최신 소스의 Linux/Windows GUI 테스트 `PASS` 또는 출시 승인 주장은 **금지**. 이전 SHA `6a18d9ca`의 Linux Qt `38694356844`, Windows Qt `38694356896`, 서비스 `38694356784`만 성공 증거다.
- **다음 과제:** 실제 Windows 빌드 정체 원인 재현·파일 로그 수집·30분 제한 내 실제 패키징→외부 UIA/전경 검증; 신규 합성 레거시 SQLite와 오류 경로 회귀 테스트; 전체 Reference→Bible→Arc/Scene→real local AI→전수 검수/재작성/Memory Delta→30/100/250화 문학 품질→EPUB/명시 승인 출판 통합. `RELEASE_BLOCKED` 유지. 절대 `main` 변경·기존 DB/원고 손상·무단 출판 금지.

---


**인수인계 작성:** 2026-10-15 15:54 KST 이후, 다음 대화용 / **개발 상태: RELEASE_BLOCKED**

> **이 파일의 첫 부분은 2026-10-15 최신 대화에서 새롭게 반영된 내용입니다. 아래 부록에는 그 이전까지의 통합 인수인계(67KB)와 사용자 원본 57개 섹션 기획안 전문을 수정하지 않고 이어 붙였습니다.** 다음 대화에서는 위아래 모두 확인하고 실제 GitHub의 최신 상태를 재조회해야 합니다. 이 문서 자체가 완제품, 실사용 Windows QA, 사용자 인수를 의미하지 않습니다.

## 0. 다음 대화를 시작하자마자 실행할 작업 (질문보다 실제 개발)

1. 이 파일과 GitHub [검증 브랜치의 최신 인수인계](https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/validation_20261015_full_handoff.md), [요구사항 감사](https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/validation_20261015_roadmap_gap_audit.md), `docs/requirements.md`, `docs/requirements.json`, 각 `docs/stageNN_*.md`와 실소스·테스트를 읽는다. 기존에 사용자가 답한 것을 다시 묻지 않는다.
2. [GitHub Actions 최신 실행](https://github.com/junggyeol4444/AI-NOVEL/actions?query=branch%3Avalidation%2Fgui-authoring-e2e-20261014)을 확인한다. **두 개의 미확정 Windows EXE 검증**을 최우선 확인: [Windows 11 real desktop QA #38694356766](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356766), [compiled Windows EXE full authoring journey #38694356849](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356849). 이 문서 작성 당시 양쪽 모두 `in_progress`, `Build unsigned x64 Windows EXE` / `Build actual Windows EXE` 단계였다. 이후 `success`/`failure`를 재조회해 단계별 로그·아티팩트를 확인하고, 실패는 수정하되 내부 테스트를 물리 Windows 사용자 인수로 착각하지 않는다.
3. 변경은 **오직 `validation/gui-authoring-e2e-20261014`** 브랜치. `main` 브랜치는 절대로 수정/병합/강제푸시/삭제하지 않는다. 실제 사용자 원고, 기존 SQLite DB, 비밀키, 설정, 외부 연동, 비활성화한 기존 예약/자동화 등을 임의 변경하지 않는다. 실계정 전송·게시·출판 금지. 검증은 합성/일회성 데이터로만 한다.
4. 실제 코드 결함을 찾아 수정·테스트·재검증, 필요시 합성 GUI 캡처를 직접 눈으로 검토한다. 원고 유실, SQL 파일 잠금, 회차/버전 충돌, EXE 설치/실행, 초기 작품 흐름, 로컬 AI 모델 실집필과 장편 품질에 우선순위를 둔다. 빠른 CI 때문에 연속 커밋이 러너 작업을 취소한다는 점을 고려하여 가능하면 **변경을 묶어 적은 수의 커밋으로** 테스트 완료까지 기다린다.
5. **출시 판정은 반드시 `RELEASE_BLOCKED`로 유지.** Windows 10/11 실제 PC의 전경 창·마우스/키보드 사용자 흐름, 참고작 전체 유사성, 30/100/250화 장편 AI 문학 품질, 단계 01–100의 진짜 통합 여부를 전부 만족하기 전 출시/실사용 PASS라고 말하지 않는다.

## 1. 사용자가 이 대화에서 반복 지시한 사항

- **“계속해”**는 예약이나 일정 제안이 아니라 **그 자리에서 자율적으로 실제 개발을 수행하라**는 뜻. 이미 제공된 답을 다시 묻거나 계획만 작성하지 말 것. 이번엔 사용자가 **명시적으로** 다음 대화 인수인계의 일회성 분 단위 예약을 요청했다. 이 한 번만 예약해야 하며 분 단위 반복 작업을 만들지 않는다.
- 2026-10-15 Assistant가 실수로 만든 일일 오전 8시 `AI Novel Factory 완성 개발` 자동화는 사용자 항의 후 **비활성화**했다. **재활성화하지 말고** 새 정기 예약을 만들지 않는다. 이전 사용자 요청으로 만들어졌다는 과거 인수인계의 5분 알림과 현재 신규 요청을 혼동하지 않는다.
- 제품은 HTML/HTTP 웹사이트가 아니라 **Windows에서 독립 실행하는 PySide6(Qt) GUI 데스크톱 EXE**. HTTP는 일부 API/서버 통신 수단이고, 로컬 SQLite에 작품 데이터가 저장된다. PostgreSQL·pgvector·Redis·Celery는 별도 서비스 기능에 사용될 수 있으나 모든 PC에 기본 탑재되었다고 주장하지 않는다.
- “완성될 때까지 계속해”의 완성 기준은 원본 01~100 요구사항, 실제 사람이 사용할 UI, 250화×회당 약 5,000자에 이를 수 있는 문학적 품질과 기억 관리, 저작권/유사성 안전, Windows 실사용 인수까지 포함한다. 일부 테스트 PASS나 코드 파일 수는 완성을 의미하지 않는다.
- 이전 Windows 화면에 대한 사용자의 평가: “저 화면이 맞다고 생각해? 누가 봐도 이상한데, 한두개가 아니고”. Qt 좌측 12개 폼만 만든 프로그램/좁은 집필칸/버려진 여백/앱 기동 시 DB 경로 요구, 참고·집필·검수·출판 단절을 개선할 것. 완전한 사용자 경험 통합은 아직 미완이다.

## 2. 정확한 원격 위치·브랜치·SHA (2026-10-15 15:54 KST 확인)

- **저장소:** https://github.com/junggyeol4444/AI-NOVEL
- **작업할 검증 브랜치:** https://github.com/junggyeol4444/AI-NOVEL/tree/validation/gui-authoring-e2e-20261014
- **GitHub Actions:** https://github.com/junggyeol4444/AI-NOVEL/actions?query=branch%3Avalidation%2Fgui-authoring-e2e-20261014
- **기존 장문의 개발 이력 문서:** https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/validation_20261015_full_handoff.md
- **원래 요구사항 및 100단계:** https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/requirements.md 와 `docs/stageNN_*.md`
- **제품 결함 감사:** https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/validation_20261015_roadmap_gap_audit.md
- **`main` 보호 기준 SHA:** `69225edeed0a09ded5f847dad9b9ea63bc45367c` (이 문서 작성 시 여전히 동일). 절대 건드리지 않는다.
- **검증 브랜치 확인 당시 최신 SHA:** `e87b189d600e72ff769fc3bae98bdef679c20864` (이 문서를 GitHub에 추가하면 변경될 것이므로 반드시 새 HEAD를 재조회).
- GitHub에 남길 새 인수인계 문서 경로: `docs/validation_20261015_next_chat_complete_handoff.md` (존재 여부 확인 후 이 파일의 최신 앞부분을 확인).

## 3. 지금 개발 중/가장 최신 기능 (검증 브랜치 전용)

### 작품 시작·집필 사용자 중심 UI

- `src/ai_novel_factory/desktop/project_studio.py`: 새 작품 홈/최근 열었던 SQLite 작품 선택·다시 열기, 스크롤 가능한 새 작품 마법사(제목/필명·장르·소재·작품 캐논·분위기·목표 화수·회당 목표 글자 수), 현재 작품·완료 회차 표시. 사용자 작품 DB 자동 오픈/교체/삭제 금지.
- 첫 회차 바로 생성, 새 회차 기획, 회차 번호·상태 검색, 이전/다음 회차(검색 결과와 현재 세션 회차 정합성), 넓은 본문 편집기, `Ctrl+S` 명시적 버전 저장, 글자 수·어절 수·목표 달성률·미저장 상태.
- 좌측 회차 목록과 우측 Novel Bible/설정·검수 패널, 900px 이하 창 자동 우측 패널 접기·명시적 토글. **집중 집필 모드** 버튼으로 양측 패널을 접고 본문 넓히기, 복귀 시 회차/원고 보존. 이는 Qt 합성 테스트로 성공했지만 물리 PC UX는 별도.
- 본문 `찾기→다음 찾기→선택된 1곳만 바꾸기`. SQLite는 사용자가 `원고 버전 저장`을 클릭할 때만 변경; 찾기/바꾸기 도중 DB 자동 저장/반복 전체 바꾸기 없음. 좁은 창에서는 2행 그리드.
- 과거 원고 버전 이력 읽기 전용 팝업 및 명시적 버전 복원. `src/ai_novel_factory/manuscript_versions.py`의 `restore_as_revision`을 사용해 **새 버전으로 추가**, 원래 버전은 보존하고 기존 최종본 자동 승인은 무효화한다. 동시수정·버전 오류·사용자 거절일 때 라이브 미저장 원고 보존.
- 종료·페이지/탭/회차/작품 변경 전 미저장 원고 확인. AI 실행 중 종료 거부가 필요한 경우 **원고 폐기 확인 전에** 블로커 체크. 회차 읽기 실패 시 이전 회차·미저장 원고 유지. 새 회차 생성 대화상자 취소 시 원고 손실/불필요한 폐기 확인 금지.

### **가장 최근 사용자 보호 기능 — 실제 파일 TXT 별도 보관**

- 핵심 코드: `src/ai_novel_factory/desktop/draft_backup.py`, UI: `project_studio.py` 내 `studioBackupCurrentDraft` 버튼. 현재 **편집기에 보이는 미저장 원고**를 사용자가 직접 선택한 새 절대경로 TXT에 UTF-8 그대로 보관. 기존 SQLite·원고 버전·출판/승인에는 변화 없음. 충돌 후에도 사용자 텍스트를 회복하기 위한 수동 비상 저장 경로다.
- 안전: 로컬 TXT만, `os.O_CREAT|os.O_EXCL` 원자적 새파일 만들기, 경합으로 생긴 사용자 파일 덮어쓰기 금지, symlink/기존파일/상대경로/빈 원고 거절, POSIX 권한 0600, fsync, 쓰기 실패 시 현재 호출이 만든 파일만 정리. **TXT는 암호화가 아님.**
- GUI 버튼을 눌러 새 TXT 생성·원문 일치·DB 이전 버전 2개 유지·중복 저장 시 원본 불변·편집기 미저장 상태 보존을 검증.
- 초기에 `Path` 클래스의 실제 `PosixPath`/`WindowsPath` 서브클래스를 잘못 거절하는 버그가 있어 `isinstance(destination,(str,Path))`로 수정. 이어 Qt 테스트에서 늦게 import한 `patch` 사용 오류를 메서드 시작 시 import하도록 수정.
- **실제 검증 성공**: [Linux Qt+TXT 안전 검사 38694356844](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356844), [Windows Qt+TXT 안전 검사 38694356896](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356896), [PostgreSQL/Redis 서비스 38694356784](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356784) — 모두 **SUCCESS**, 소스 커밋 `6a18d9caeac6034de1768d6bda76f17bd0301fdb`. 합성 GUI 스크린샷 실제 육안 확인: 한글 렌더링과 TXT 버튼 노출. **Windows 사용자 실사용 전경 인수 PASS 아님**.
- 주요 기능 커밋: `711dfd62130f15b143166df6d15270b2aac8c7ec` (버튼·유틸리티), `9b7fd77ff10fd666bef05c834002442a941a8f32` (Path 타입 수정), `6a18d9caeac6034de1768d6bda76f17bd0301fdb` (GUI mock import), `e87b189d600e72ff769fc3bae98bdef679c20864` (문서만, skip ci).
- 안전복구 테스트: `tests/test_draft_backup_safety.py` 7개 테스트 + `tests/test_studio_gui_optional.py` 실제 Qt 클릭. CI: `.github/workflows/anf-linux-studio-safety-ci.yml` 및 `.github/workflows/anf-studio-fast-ci.yml`.

### 최근 다른 중요한 버그 수정

- Windows SQLite 파일 잠금: `plot_editor_model.py`의 `sqlite3.Connection` `with`는 connection을 닫지 않으므로 `contextlib.closing` 사용. 실패 기록 [Windows fast 38690349590](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38690349590) → 이후 Windows success.
- 초고·이력 버전 및 중복 생성 회귀: `test_studio_gui_optional.py`에서 테스트용 2화 중복 생성 오류 제거; 합성 Qt 종료 시 `deleteLater()/sendPostedEvents()`로 Bus error 해결.
- 작품 재열기 원자성: `authoring_session.open_project`는 새 DB 회차/장면 사전 검사에 성공한 경우에만 이전 작품 연결을 닫는다. 다른 창 동시 수정일 때 `_loaded_revision` 확인하여 무단 덮어쓰기 거부.
- 최근 대표 성공 CI: [Linux GUI 38690721746](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38690721746), [Windows GUI 38690721575](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38690721575), [Linux 집중 모드 38693335765](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38693335765), [Windows 집중 모드 38693335630](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38693335630). 개별 결과를 새 HEAD 검증과 혼동 금지.

## 4. 현재 Windows EXE/실행 모델 검증: **진행 중, 판정 금지**

- [Windows 11 real desktop QA run 38694356766](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356766): SHA `6a18d9ca`, 상태 `IN_PROGRESS` (마지막 재조회 ~2026-10-15 15:55 KST). Windows unsigned x64 EXE 빌드 단계 진행 중. 완료 후 외부 Windows UIAutomation, 화면/foreground evidence/아티팩트와 오류를 반드시 검토. Windows 11 ARM 에뮬레이션·OOBE/privacy overlay의 이슈가 여전히 물리 PC 전경 합격의 장애다.
- [Compiled Windows EXE full authoring journey run 38694356849](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356849): SHA `6a18d9ca`, 상태 `IN_PROGRESS`, `Build actual Windows EXE`. 이후 앱 내 편집·실제 CPU GGUF 로컬 모델·저장·재시작 시나리오를 CI가 시도하나 실행/품질/인수를 실제 확인해야 한다.
- 앱 관련 CI 일부는 먼저 실패 후 빠른 추가 커밋에 의해 **cancelled**되었다. 특히 모델/EXE 장시간 job은 빈번한 코드 커밋으로 중간에 취소된다. 불필요한 CI 리트리거나 연속 커밋을 자제하고 최종 후보 코드가 run 완료할 때까지 관찰해야 한다.
- 과거 코드 단계에서 [Windows compiled EXE+실 GGUF run 38680175901](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175901) **SUCCESS**. 그러나 그 버전과 최신 PySide6 통합 UI는 다르고 실사용자 전체/250화 검증이 아니다.
- 과거 [Windows 11 ARM run 38680175938](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175938)는 외부 UIA 폼 클릭·SQLite·종료·재실행·복원 단계는 통과하였으나 OS 초기 개인정보 설정 화면이 창을 가려 `QtForeground=False` — **전체 FAIL**. 최신 run에서도 같은 OOBE 이슈 재발 여부를 보라. CI offscreen Qt와 실제 Windows foreground는 다른 것.

## 5. 원본 01~100 기능 계획 — **완료 기준은 실제 통합**

| 구간 | 필수 작업 및 현재 미달 |
|---|---|
| **01–10** | Python/환경·FastAPI API·PySide6 Windows GUI·독립 EXE·실제 설치와 기본 회귀. Qt 자동테스트 일부 PASS지만 PC 실사용 인수 미완. |
| **11–20** | 참고소설 다중파일 TXT/MD/EPUB/DOCX/PDF 가져오기·파싱·회차 분리·기초 통계·카탈로그. 부분 모듈 존재, Writer와 종단 연결 부족. |
| **21–30** | 대사 비율·문장/회차 구조·사건 밀도/간격/클리프행어·인물/관계/감정/복선/문체 통계·Reference Profile. 의미 기반 장편 품질 검증 부족. |
| **31–40** | 다중 Reference Profile/Genre Pattern Library/참고 가중치·요소 선택, 패턴 조회·사용, 원문 비복제/전수 유사성 게이트. 전체 기획/Writer 자동 적용 미완. |
| **41–50** | Novel Bible, Character/Knowledge, World, Relationship, Timeline, Foreshadowing, Style, Episode, schema migration. 로컬 CRUD 일부, 자동 기억 업데이트·사용자 UX 미완. |
| **51–60** | Premise→Arc→회차/장면 Plot→Context/Retrieval/pgvector→참고 패턴→플롯편집기 통합. 250화 빈 슬롯·단편 preview를 완성으로 오인 금지. |
| **61–70** | 로컬 모델/키 보안·Writer 프롬프트·Scene Writer/Assembly/Orchestrator/Celery·재시도/체크포인트/단일회차 실생성. CPU GGUF 샘플 성공과 문학 품질은 별개. |
| **71–80** | Continuity/Knowledge/Timeline/Foreshadow/Logic/Style/Repetition/Reference Similarity/Reader/Rewrite 전수 검사. 일부만 동작, 미수행 항목은 `NOT_RUN`; 자동 위험 장면 재작성/재검사 미완. |
| **81–90** | Memory Delta/적용·버전 관리·이어쓰기·예약/스케줄러·실제 30화/100화/장편 기억·완결 검사/승인/운영 모니터. 모의 30/120화 실험은 실제 모델 품질 증명이 아니다. |
| **91–100** | 원본 표지/메타데이터/EPUB3/원고 파일/Publisher Adapter/플랫폼/Windows EXE·설치·전체 회귀·정식 인수. 실계정 출판·물리 Win10/11 x64·정식 릴리스 미검증. |

**추가로 원래 통합본 부록의 사용자가 제공한 57개 기획 섹션을 모두 읽어야 한다.** 하위 메뉴·코드가 있는 것과 사용자가 한 번에 250화 독창적 문학 품질을 획득하는 것은 다르다. 반드시 실제 참조소설 분석→기획→로컬 모델 Writer→모든 검사→수정→메모리→결말→EPUB/출판 준비를 단일 사용자 세션으로 연결해야 한다.

## 6. 무엇을 먼저 할지 — 다음 대화의 구체적 실행 우선순위

1. **Windows 장시간 두 run 결과 조회**: 재시도 불필요하면 반복 실행하지 말고 job step/종료코드/실제 로그/아티팩트로 결함을 특정한다. Win11 OOBE/foreground 검증이 실패하면 물리 PC 인수 `BLOCKED`로 표기. 격리된 창 캡처를 실제 foreground로 표현하지 않는다.
2. TXT 보관 기능 검증이 통과한 최신 코드 `6a18d9ca`와 docs-only `e87b189d`를 기준으로 현재 브랜치 최신 SHA 재조회, main 보호 확인. 신규 기능은 **반드시 테스트, Windows Qt/GUI 둘 다 검사**.
3. 사용자 중심 GUI **더 본질적으로** 개선: 실제 작품 상태/최근 작품/집필/참고·인물·복선 메모리·품질 피드백·자동 AI 집필 대기와 중단/재개가 하나의 작업 흐름에 이어지는지, 좁은 화면/키보드/접근성/대량 회차에서 성능. 12개 폼 나열을 최종 UX로 포장하지 않는다.
4. **문학 품질 및 참고 비복제 핵심**: 여러 참고소설을 안전하게 등록/요약/가중치 선택하고 원문 아닌 구조 패턴을 Story Arc/Episode Planner/Writer에 연결. Novel Bible 일관성·인물 Knowledge/Timeline/Foreshadow/Reference Similarity/Reader 점검 모두 실질적으로 수행, 실패 장면만 재작성·재검사하고 Memory Delta의 명시적 승인과 롤백을 구현.
5. **장편 스트레스:** 실제 로컬 모델 30화→100화→목표 250화 연속, 회당 약 5000자, 소재·캐릭터 지식·장기 복선·인과관계·사건 다양성/반복·표절 유사성·작업 중단/재개·완결·시간/비용·품질 평가. Mock이나 135M 샘플 기계 통과를 문학 품질 PASS로 주장하지 않는다.
6. **출판/패키징:** Windows x64 EXE/한글 번들·설치/업데이트/보안, EPUB/표지/메타데이터 검증, 플랫폼별 공식 API/정책과 사람 승인 게이트. 실제 외부 게시·업로드/사용자 계정은 별도 명시 승인 전 불허.
7. 회귀 로그·스크린샷 육안 확인, 실패 우선 수리. 작업 결과·커밋·CI 링크와 미검증을 구분하여 짧게 보고. 갱신 인수인계 문서를 docs-only `[skip ci]`로 GitHub 검증 브랜치에 남긴다.

## 7. 검증용 파일·아티팩트와 참조

- UI 회귀 테스트 `tests/test_studio_gui_optional.py`, 신규 TXT 단독 테스트 `tests/test_draft_backup_safety.py`, DB/레이스 `tests/test_authoring_session_safety.py`, 버전 `tests/test_stage83_manuscript_versions.py`.
- 핵심 UI `src/ai_novel_factory/desktop/app.py`, `project_studio.py`, `authoring_session.py`, `authoring_controls.py`, `plot_editor_model.py`, `draft_backup.py`; DB `database/episodes.py`, `database/novel_bible.py`; `manuscript_versions.py`.
- QA 합성 스크린샷 생성 `scripts/ci_studio_snapshots.py` 및 GUI `.github/workflows/anf-linux-studio-safety-ci.yml`, `.github/workflows/anf-studio-fast-ci.yml`. GUI 스크린샷 아티팩트 [run 38694356844](https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38694356844) 내 `anf-linux-studio-qt-synthetic-screens` (합성 Qt offscreen, 실제 Windows 아님).
- Windows QA/EXE `scripts/ci_windows11_external_authoring.ps1`, `scripts/ci_windows11_desktop.ps1`, `desktop/ci_win11_ui.py`, `scripts/build_portable_ai_bundle.py`, `packaging/windows/local_model_bridge.py`.
- 서비스 구성 `.github/workflows/anf-live-services-ci.yml`, `src/ai_novel_factory/service_integration_ci.py`.
- 사용자 검증 원본 67KB 인수인계 문서 파일 `AI_NOVEL_전체개발_인수인계_20261015.md` 전문은 **아래 부록으로 통째로 포함**. 중복되는 과거 SHA/실행 상태/시간/예약 진술은 반드시 이 문서의 최신 0–7절에 우선시킨다.

## 8. 예약/다음 대화 전달의 한계

사용자가 이번에 **분 단위 일회성 인수인계 예약을 명시적으로 요청**했다. 1분 뒤 일회성 작업으로 이 문서의 GitHub URL을 전하고, 새 대화의 첫 작업이 위 0번부터 이어지는 지시를 전달하도록 구성한다. 자동화는 ChatGPT의 **새로운 작업 메시지**로 전달되며, 별도의 새 채팅을 자동 생성하거나 과거 대화 기록/모든 파일을 통째로 이관했다고 보장하지 않는다. 그래서 다음 대화에서는 이 파일 또는 GitHub 인수인계 URL을 읽고 진행해야 한다. 사용자 요청 없이 반복 예약·새 개발 스케줄을 만들지 말 것.

---

# 부록 — 2026-10-15 이전 전체 인수인계 + 사용자 원본 57섹션 기획안 (원문 보존)

아래는 기존 파일 `AI_NOVEL_전체개발_인수인계_20261015.md`의 내용 그대로입니다. 일부 과거 기록(시간/브랜치 SHA/예약 상태)은 부록 당시 상황이므로 위 새 0–8절이 더 최신입니다.

---

# AI NOVEL FACTORY — 전체 요구·01~100개발단계·실검증·GUI 재설계 인수인계

**작성 기준:** 2026-10-15 / Asia-Seoul · **정식 출시 여부: 미승인(RELEASE_BLOCKED)**

**새 대화가 맨 먼저 해야 할 일:** 이 파일 전체를 읽는다. 이 파일 아래쪽에 사용자 원본 기획안 전문을 복사해 두었다. GitHub 저장소의 검증 브랜치 최신 소스와 실제 Actions 결과를 확인한 뒤 **화면 전체 사용자 중심 재설계 및 실제 Windows EXE 조작 검증**부터 개발을 이어간다.

## 1. 절대 불변: 사용자가 직접 지시한 내용

1. 원래 **AI Novel Factory** 기획안의 기능과 01–100 모든 개발단계를 겉모습만 만들지 말고 실제로 구현·연결한다. 사용자가 최초에 장르, 소재, 목표 회차·글자 수, 세계관/인물 설정, 분위기, 참고소설만 입력하면 **참고작 구조 분석 → 다중 참고 패턴/가중치 → Novel Bible/세계관/인물/관계/시간선/복선/스타일 → 전체 Arc·회차·장면 플롯 → 실제 AI 장편 집필 → Continuity/Logic/Character Knowledge/Timeline/Foreshadow/Style/Repetition/Reference Similarity/Reader 검수 → 위험 장면 자동 재작성 및 재검사 → 장기 기억 업데이트 → 다음 회차 → 완결 검수 → EPUB/표지/출판 준비 → 사용자 승인 후 지원 플랫폼 출판**까지 실제 동작해야 한다.
2. **`main` 브랜치 절대로 수정하지 말 것, PR 병합하지 말 것.** 오직 `validation/gui-authoring-e2e-20261014` 같은 별도 검증 브랜치에서만 작업. 기존 원고/사용자 DB/각종 설정/접속 키/연동 앱/사용자가 꺼 둔 자동화는 그대로 보존. 기존 키 재설정·삭제·비활성 자동화 재활성화 금지. 외부 플랫폼 게시·실계정 전송은 명시 승인 없이는 불가.
3. 사용자는 **“실사용자가 코드로 실행하니? 프로그램 키고 누르고 기다리고 누르고 하는 방식으로 확인해야지”**라며 내부 Qt 테스트를 실제 인수 검증으로 부르지 말라고 지시. 반드시 Windows 10/11에서 **실제 EXE 실행 → 눈에 보이는 프로그램 입력/클릭 → AI 작업 대기 → 초고 확인·수정 → 저장 → 종료/재실행 → 복원 → EPUB/출판 준비**를 확인. Qt offscreen이나 내부 코드 직접 호출은 보조 검증일 뿐. 화면과 사용자 흐름의 실제 결함을 직접 찾아 고친다.
4. **사용자가 최신 실제 화면 캡처를 보고 “저게 맞다고 생각해? 누가 봐도 이상한데 한두 개가 아니고”라고 지적**. 이전 답변에서도 완제품 GUI로 **전면 불합격** 판정. 12개 기본 Qt 사이드바/폼을 다채롭게 칠하는 수준이 아니라 정보구조·화면 배치·작업 흐름 자체를 완전히 재설계해 실동작하게 한다.
5. 참고소설 원문·고유명사·캐릭터·세계관·구체적 문장을 복제하지 말 것. 참고작 **구조 통계와 성공 패턴**만 활용. 새 작품 Novel Bible이 참고작보다 절대 우선. 전체 등록 참고작 유사성 검사를 실제로 실행해야 하고, 실행하지 못한 항목을 거짓 `PASS`로 표시하지 말고 `NOT_RUN`을 유지한다.
6. 250화 × 약 5000자, 30화/100화 이상 실제 연속 집필·품질/기억 검증이 목표. 250개 회차 계획 슬롯 생성이나 한두 화 짧은 모델 샘플 생성은 달성과 전혀 다르다. 가벼운 SmolLM2 135M 모델은 한국어 장편 품질을 보장할 수 없다. 테스트 합격 범위를 과장하지 말 것.
7. 사용자가 **“하라고”, “별도 검증도 니가 하라고”, “윈도우 11 없어?”**라고 직접 지시함. 설명/리스트/테스트 코드만 남기고 실제 구현·GUI 검사·재시험을 회피하지 말 것. 잘못된 성공 선언은 금지.
8. 대화 길이 문제로 사용자에게 **“메시지 전송 시간이 초과되었습니다. 다시 시도하세요.”** 발생. 장시간 폴링/반복 상태 메시지로 대화 비대하게 만들지 말고, 결과를 짧게 전달하고 근거는 이 파일/GitHub에 보관한다. 사용자가 이미 답한 질문 반복 금지.
9. 사용자가 2026-10-15에 **“5분 뒤 예약 걸어, 지금까지 한 것, 기획안 전 개발단계 전부, 뭘 하고 있었는지, 내가 말한 내용/지킬 내용 모두 다음 대화로 넘겨”**라고 지시. `AI NOVEL 개발 인수인계` **일회성 예약 생성 성공**, Asia/Seoul 약 2026-10-15 13:29 실행 예정. 다른 자동화에는 손대지 않기. 예약이 다른 대화에서 이전 파일을 자동으로 보장한다고 과장하지 말고 본 문서를 새 대화에 첨부하거나 GitHub 문서 링크에서 불러오도록 한다.

## 2. 저장소 및 현재 작업 브랜치

- 원격 저장소: https://github.com/junggyeol4444/AI-NOVEL
- **검증 브랜치 전용:** https://github.com/junggyeol4444/AI-NOVEL/tree/validation/gui-authoring-e2e-20261014
- **`main`: 무조건 보존. 수정/병합/강제푸시/삭제 금지.**
- 기존 단계 결함 감사: https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/validation_20261015_roadmap_gap_audit.md
- 이 인수인계의 GitHub 버전(확인 가능 시): https://github.com/junggyeol4444/AI-NOVEL/blob/validation/gui-authoring-e2e-20261014/docs/validation_20261015_full_handoff.md
- 원문 57섹션 전체는 이 파일 아래 별첨. 원문 `붙여넣은 마크다운(2).md` 43KB를 **한 글자도 바꾸지 않고** 복사.

## 3. 원본 기획안 핵심 사용자 경험

**사용자 입력:** 장르, 소재/아이디어, 회차 수/회차별 목표 글자 수(예: 250×5000자), 주요 설정/주인공, 원하는 분위기, 참고소설 A·B·C(TXT/EPUB/DOCX/PDF/Markdown), A에서는 전개, B에서는 복선, C에서는 관계 변화 등 개별 가중치.

**자동 전체 파이프라인:** 자료 파싱→회차 분리→Reference Profile(사건/전개/통계/인물/관계/감정/복선/클리프행어/문체)→다중 Pattern Library→독창적인 Novel Bible→Character Knowledge/세계관/Time/Relationship/Foreshadow/Style DB→전체 Story Arc→전체 Episode/Scene Plan→각 회차 관련 DB/패턴만 검색해 Writer 프롬프트 구성→실제 모델 장면 작성→Continuity/Logic/Knowledge/Timeline/Foreshadow/Repetition/Style/Similarity/Reader 검사→문제 장면 수정·재검사→미승인/최종본 분리→새 사실 Memory Delta→다음 화→30화·100화·250화 안정 운영/복구→전체 완결검수→표지·EPUB3·메타데이터→사용자 승인·실제 가능한 플랫폼에 출판. **저작권 보호와 Novel Bible 우선**.

**원본 기술:** Python/FastAPI, PostgreSQL, pgvector, Redis/Celery, PySide6 Windows EXE, SQLite 로컬 DB(검증 브랜치 현재 기본), Reference File parser, JSON/Markdown/EPUB3. 원문 Step 01~100과 Phase 1~7 참조.

## 4. 개발 01~100 단계 실제 파일/기능 대조

| 구간 | 해야 하는 일 | 현 상태/추가 과제 |
|---|---|---|
| **01–10** | 개발 기반·환경/설정·Windows GUI·로컬 API·스모크 | PySide6 EXE, FastAPI health 있음. Windows 10/11 x64 개인 PC 실사용·설치 **미완료**. GUI 전체 제품 인수 **불합격**. |
| **11–20** | 참고소설 파일 등록·TXT/MD/EPUB/DOCX/PDF 파싱·회차 분리·통계·카탈로그·통합 | 파서/GUI 부분 존재. 등록 참고작→Planner→Writer 전체 자동 연결 검증 부족. |
| **21–30** | 대사·서술·회차 구조·사건 위치/간격·클리프행어·인물/관계·복선/감정·Style·Reference Profile | 알고리즘 단위 모듈. 실제 여러 소설 품질+연계 검증 필요. |
| **31–40** | 다중 Profile·장르패턴·Pattern Library·참고 강도·요소 선택·패턴 검색/사용·비복제·유사도/통합 | 패턴 조회 UI 있음. 등록된 참고작 전체 자료에 대한 필수 Similarity 게이트와 Writer 자동 주입 **미완성**. |
| **41–50** | Novel Bible, Characters/Knowledge, World, Relationship, Timeline, Foreshadowing, Style Bible, Episodes, migration | 기존 SQLite CRUD 및 6개 사이드바 실제 저장 연결. 지식/문체 전체 GUI, 장편 자동 기억 업데이트 미완성. |
| **51–60** | Premise, Story Arcs, Episode/Scene Planner, context, pgvector/retrieval, Pattern 적용, Plot Editor, planning pipeline | 250개 계획 슬롯/미승인 AI 스토리 초안. 최초 입력만으로 인간이 쓸 수준의 **전체 자동 기획/Writer 주입 미완성**. |
| **61–70** | 로컬 모델, 비밀키, writer prompt, scene writer, episode assembly, orchestrator, queue/monitor, retry, 실제 1화 | Windows 번들 llama.cpp+SmolLM2-135M GGUF 오프라인 작동, GUI 클릭/초고/저장. 장편 모델 품질/완전 자동 스케줄은 미완성. |
| **71–80** | Continuity/Knowledge/Timeline/Foreshadow/Logic/Style/Repetition/Similarity/Reader/Scene Revision | 검사 개별 모듈. 배치 Runner는 실제 length/repetition 등 일부만, 6개 항목은 `NOT_RUN`, 실제 자동 재작성 전체 연결 미완성. |
| **81–90** | Memory delta/application, versions, continuation, scheduler, 30화, 장기 안정, 결말, 승인, 운영 모니터 | 체크포인트/이미 있는 회차 건너뛰기 일부, 실제 DB/큐 컨테이너 검증. **30/100화 실제 AI+메모리/품질 전체 시험 없음**. |
| **91–100** | 표지, metadata, EPUB, 업로드 초안, publisher adapter, 플랫폼 포맷, Windows 빌드/설치, 전체 회귀, 출시 | 로컬 TXT/EPUB, 검수 최종본, 실험용 unsigned EXE, WordPress 비공개 초안 API 계약 테스트. 실계정 게시·표지 일괄/배포 인수 **미완료**. |

**01~100의 상세 단계 문서 `docs/stageNN_*.md`와 실제 테스트를 다음 대화에서 반드시 전수 조회**한다. 01~07, 12, 14는 일반적인 명칭의 docs/stageNN_*.md 문서가 확인되지 않아 별도 정의를 확인해야 한다. 번호별 소스/테스트 존재가 제품 완료를 증명하지 않는다.

개별 Stage 문서명(확인된 08–100):

```
08 desktop_ui; 09 local_api; 10 smoke_tests;
11 reference_file_picker; 12 문서 확인 필요; 13 txt_markdown_parser; 14 문서 확인 필요;
15 docx_parser; 16 pdf_parser; 17 episode_splitter; 18 basic_statistics;
19 reference_catalog; 20 reference_import_integration;
21 dialogue_narration; 22 episode_structure; 23 event_timing; 24 event_pacing;
25 cliffhanger_types; 26 character_roles; 27 relationship_changes; 28 foreshadow_emotion;
29 style_statistics; 30 reference_profiles;
31 multi_reference_profiles; 32 genre_patterns; 33 pattern_library; 34 pattern_strength;
35 reference_element_selection; 36 related_pattern_search; 37 pattern_usage;
38 noncopy_protection; 39 similarity_baseline; 40 reference_analysis_integration;
41 novel_bible; 42 characters; 43 character_knowledge; 44 world_canon;
45 relationship_timeline; 46 event_timeline; 47 foreshadow; 48 style_bible;
49 episodes; 50 migrations;
51 planning; 52 story_arcs; 53 episode_planner; 54 scene_planner;
55 episode_context; 56 scene_vectors; 57 episode_retrieval;
58 pattern_application; 59 plot_editor; 60 planning_pipeline;
61 local_model_providers; 62 credentials; 63 writer_prompt; 64 scene_writer;
65 episode_assembly; 66 orchestrator; 67 local_queue; 68 task_monitor;
69 retry_checkpoint; 70 single_episode_integration;
71 continuity_checker; 72 knowledge_checker; 73 timeline_checker;
74 foreshadow_checker; 75 logic_checker; 76 style_checker;
77 repetition_checker; 78 reference_similarity_checker;
79 reader_simulation; 80 scene_revision;
81 memory_delta; 82 memory_application; 83 manuscript_versions;
84 episode_continuation; 85 writing_scheduler; 86 thirty_episode_integration;
87 long_memory_stability; 88 ending_audit; 89 publication_approval;
90 operations_monitor;
91 cover_art; 92 publication_metadata; 93 epub3; 94 upload_drafts;
95 publisher_adapter (+ continuation_asset_review); 96 platform_format_audit;
97 windows_exe_build; 98 installation_and_connection_guide;
99 windows_integrated_regression; 100 release_and_acceptance (+ user_manual).
```

## 5. 실제 구현된 코드와 시험 근거(완성 아님)

**기본 GUI** `src/ai_novel_factory/desktop/app.py`, `authoring_controls.py`, `authoring_workflow.py`, `authoring_session.py`, `canon_workspace.py`, `additional_workspaces.py`, `auto_batch_panel.py`.

**배치** `src/ai_novel_factory/auto_novel_run.py`: 실제 로컬 모델로 미승인 전체 스토리 preview, 각 화 플롯·장면 초고, SQLite 저장; 길이·반복 일부 검사, continuity/logic/reference_similarity/timeline/foreshadowing/reader_simulation은 `NOT_RUN`, 중단/기존 화 건너뛰기. **완전한 자동 장편 검수/승인 아님**.

**Windows 로컬 모델** `packaging/windows/local_model_bridge.py`, `scripts/build_portable_ai_bundle.py`, `scripts/ci_portable_model_e2e.py`: 공개 GGUF CPU 135M 가중치와 llama.cpp 런타임을 EXE와 같이 제공, 추가 사용자 선택 GGUF 지원. 번들 모델의 한국어 장편소설 품질은 심각하게 별도 검증 필요.

**서비스** `src/ai_novel_factory/service_integration_ci.py`, `.github/workflows/anf-live-services-ci.yml`: 실제 일회용 Postgres/pgvector/Redis/Celery INSERT, 벡터 작품 격리 검색, 큐 전달·결과 수신 PASS; 일반 Windows 앱에서 운영/설치 자동 구성 미검증.

**사용자 검수/출판** `authoring_session.save_final_text`와 `export_final`: 2회 확인 후 최종 원고, 덮어쓰기 금지, private EPUB. `wordpress_draft_api.py`: HTTPS 공식 REST API의 **비공개 초안만**, 실제 계정 미검증. 4개 no-network 계약 테스트. 원고 공개 게시/실출판 완료로 표현하지 말 것.

**실험용 Windows EXE / 보안:** PyInstaller Windows unsigned QA 빌드, 인스톨러/서명/업데이트·정식 PC 검수 미완성. 복제권 침해 방지를 위해 참고작 원문 Writer 직접 전달 금지. 합성 테스트만 업로드.

### 2026-10-15 최종 확인된 주요 Actions (반드시 최신 재확인)

- **https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175901 — SUCCESS**: 실제 Windows x64 컴파일 EXE/CPU GGUF AI 집필/GUI Qt 클릭/저장/검수 최종본/TXT·EPUB/독립 EXE 재실행. 입력은 부분적으로 테스트 코드로 주입 → **실물 사람 전체 클릭 증거는 아님**.
- **https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175892 — SUCCESS**: 실제 disposable PostgreSQL/pgvector/Redis/Celery 컨테이너 실연동.
- **https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175938 — 전체 FAIL**: 실제 Windows 11 ARM64에서 x64 EXE 에뮬레이션, 외부 PowerShell UIAutomation이 제목·장르·설정 등 9개 입력칸을 채움→`새 작품 생성` 버튼을 실제 누름→SQLite DB 확인→Bible 입력/저장→DB 포맷 검증→WM_CLOSE로 종료→독립 EXE 다시 실행→`기존 작품 열기` 클릭→제목·장르·Bible 복원 등 **모두 PASS**. 이어 다른 외부 Windows 테스트에서 12개 메뉴 UIA 선택 PASS, 실제 `Publication` 페이지 열림(`PublicationPageActionsVisibleViaUIA=3`), Win32 직접 앱 창 캡처 PASS. 그런데 Windows 11 러너의 OS 초기 설정/OOBE 화면이 앱 전면을 가려 `QtForeground=False`: **전체 검증은 FAIL**. 프로그램이 실사용자 눈앞에 제대로 보인다고 승인할 수 없음.
- https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38669951971 — Windows x64 모델 포함 EXE의 GUI 조작·작성·재시작 PASS.
- https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38671177873 — Windows 11 ARM x64 에뮬레이션+offscreen Qt GUI+GGUF 원고 저장·독립 EXE 복원 PASS.
- https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38669105086 — WordPress private DRAFT 계약 테스트 4개 PASS (실계정 업로드 아님).
- 메모 당시 검증 브랜치 기존 최신 커밋: `5028a75e3c0a7c1819a941af689c034915ca0c7b` (인수인계 파일 새 커밋/다른 최신 작업은 변경 가능). **`main` 미변경**.

**실제 화면 파일(사용자 직접 확인/제품 불합격 지적):** `AI_Novel_Windows11_12_screens.png`, `AI_Novel_Windows11_actual_screenshots.zip`, `ai_novel_actual_windows_screens/native_app_window.png`, `ui_01_novels.png`, `ui_10_episodes.png`, `ui_12_publication.png`. 이전 대화에서 다운로드 제공. 다른 대화에서는 다시 파일 첨부 또는 GitHub Actions artifacts에서 내려받기.

## 6. 사용자에게 보여 준 GUI 화면 — 심각한 문제와 불합격 판정

사용자는 “저 화면이 맞다고 생각하냐, 누가 봐도 이상하고 한두 개가 아니야”라고 항의. 이전 응답이 **GUI 전체 제품 불합격**을 인정함.

1. 왼쪽 메뉴가 한국어·영어 혼용(`Novel Bible`, `World`, `Publication`, ...), 사용자 언어 통일 안 됨.
2. 첫 화면에 `SQLite DB 경로`를 제일 먼저 요구하며 SQL 도구처럼 보임. 일반 사용자는 제목·장르·소재를 입력해야지 DB 경로를 관리할 이유가 없음.
3. 12개 메뉴가 독립적인 폼 모음. 사용자 선택한 작품/현재 화가 모든 메뉴에 공유되지 않음. 일부 화면에서 DB를 반복해서 열어야 함.
4. 빈 공간이 심한 메뉴와 폼/버튼이 빽빽한 긴 스크롤. 회차/장면 플롯과 원고 입력칸이 너무 좁음. **소설 원고 중심의 넓은 문서 편집기 없음**.
5. 책의 진행상황·선택한 회차·AI 진행률·다음 작업·에러 원인·수정 항목/저장 상태가 일반 사용자가 알아보기 어려움.
6. `API 미연결`, `로컬 UI 준비됨` 등 개발용 로그가 UI 전면 상태 메시지로 노출.
7. Novel Bible/Characters/World/Relationships/Foreshadowing이 Writer·장기기억과 연동되는 UI로 보이지 않고 DB 폼처럼 고립됨.
8. `Publication`에 DB 폴더·가격·WordPress 계정·비밀번호가 앞세워져, **승인된 최종 원고와 검수 상태**를 먼저 보여주지 않음.
9. 레퍼런스 파일 분석과 패턴의 선택/가중치·AI 집필에 적용되는 근거가 안 보임.
10. 기능 버튼 12개가 보이거나 눌리는 것 ≠ 사용 가능한 장편소설 자동 제작 프로그램. **테스트 PASS보다 사람이 처음 실행한 화면/사용 경로 직접 확인이 우선**.

### 실제 구현해야 할 GUI 화면 재설계 (기존 코드를 버리지 말고 연결)

- **작품 홈:** 최근 작품 카드/선택한 작품·회차·진행률·저장 상태. 새 작품 만들기/기존 작품 열기, 내부 SQLite 파일은 고급 설정으로 숨기고 안전한 기본 로컬 저장.
- **새 작품 마법사:** 장르·소재·주인공·설정·분량/분위기·참고소설(파일 드롭/목록)→분석 진행/Reference Profile 보기→작품/기능별 참고 강도 선택→AI 전체 Story Arc·Bible 생성·사용자 수정·승인.
- **스토리 기획실:** Arc→회차→장면, 인물·사건·감정·복선·패턴 활용 이유를 카드/타임라인으로. 중간중간 수정/승인·저장.
- **집필 작업실 핵심 화면:** 왼쪽 전체 회차·장면 목록 / 중앙 넓고 편집하기 좋은 실제 소설 원고 / 오른쪽 인물·관계·세계관·시간선·복선·참고 구조 패널. AI 생성, 진행/취소, 장면 편집, 검사 결과, 재작성, 최종 승인 동작 연결.
- **검수 대시보드:** 회차별 Continuity/Logic/Character Knowledge/Timeline/Foreshadow/Repetition/Style/Reference Similarity/Reader 평가, 근거가 보이는 문제 장면, 자동 재작성→재검증, 실패/NOT_RUN 차단.
- **내보내기/출판:** 어떤 작품/원고를 내보내는지 미리보기, 저작권·검수·사용자 승인/EPUB·표지·가격 메타데이터, 명시 승인한 공식 API만 업로드. 숨은 개발 상태는 설정 창으로.
- **화면 전역:** 하나의 작품·세션 공유, 사람 눈에 맞는 한국어 문구, 접근성/단축키/Undo/Redo/저장 상태, 화면 크기 대응, 실제 오류 설명, 버튼 실동작.

## 7. **바로 다음 대화에서 실행해야 할 일 — 우선순위**

1. 이 문서와 원문 전문 및 GitHub `docs/stageNN_*.md`/최신 코드/Actions를 읽는다. 이미 알려 준 브랜치·요구를 반복 질문하지 않는다. 추가 작업은 검증 브랜치만.
2. 실제 기존 `app.py`, `authoring_session.py`, ReferencePicker/PlotEditor/Bible GUI DB 연결을 확인하고, **작품 홈+생성 마법사+집필실의 새 PySide6 사용자 중심 구조**를 구현. GUI가 원고 중심이도록 스크린샷을 실제 생성·육안 검사. 플레이스홀더, 겉만 꾸미는 목업 금지.
3. **하나의 선택한 작품을 전체 메뉴가 공유**하도록 DB 세션 연결. 기존 데이터/리비전 관리/수정사항 보호. 파일 경로를 반복 묻지 않음.
4. 실제 Windows x64 EXE 빌드+**외부 Win32 UIAutomation/마우스 클릭/키보드**로 첫 시작→참고소설 등록→계획→장면 집필→검사→최종 원고→EPUB→종료·재실행→복원 전 구간 테스트. 사용자가 보는 화면을 직접 캡처해서 문제를 발견하면 고침.
5. 위 기존 외부 Windows 테스트가 **이미 작품 생성/Bible/종료·재시작/복원 PASS임을 활용**하되, GUI 품질/Windows OOBE foreground 불합격을 별도 인수 차단으로 유지. Windows 10/11 물리 x64 기기 및 실제 사람 입력/설치/스케일링/키보드 포커스 검증은 확인 전까지 미검증.
6. Reference Pattern → Writer Context → Continuity/Logic/Timeline/Foreshadow/Reference Similarity 전체 실제 검수·재작성/재검사·Memory Delta 업데이트 연결. 외부 비교 원문을 무단 복사/전송하지 않기.
7. 실제 AI로 30화/100화 장기 작성·품질/메모리 안정·강제 종료 복구 확인. 250화는 실제 작성 전 PASS 금지.
8. 정식 모델·설치/업데이트/백업·선택적 PG/Redis 서비스 UX, 출판 API 승인·실업로드 검증, 표지·EPUB 호환 검수. 100단계 최종 인수표를 실제 근거로 갱신.
9. 사용자에게 채팅 타임아웃 방지 위해 **짧은 검증 요약+실제 화면+근거 링크**만 전달. 모두 완료될 때까지 완성 선언 금지.

## 8. 새 대화용 최초 프롬프트

> AI Novel Factory 이전 작업을 이어가라. 이 첨부의 원본 기획안 전체(01~100단계)와 인수인계/검증 링크를 읽어라. `junggyeol4444/AI-NOVEL`의 `validation/gui-authoring-e2e-20261014` 브랜치에서만 개발하고 **main은 건드리지 마라**. 사용자 데이터·키·비활성 자동화 보존. 사용자에게 보여 준 실제 Windows 캡처는 GUI가 전체적으로 이상하고 제품 UX **불합격**으로 확인됐다. 우선 **사용자 중심의 작품 홈/새 작품/기획실/큰 원고 집필실/검수/출판**으로 GUI를 전면 재구성해 실제 데이터/모델에 연결한다. 코드 모듈 존재/Qt offscreen 테스트만을 실사용 검증이라고 부르지 말고, Windows에서 EXE를 켜서 외부 마우스/키보드/접근성 입력과 버튼 클릭, AI 집필, 저장, 종료·재실행, 화면 캡처 육안 확인으로 검증해 결함을 고쳐라. 기존 Windows 11 외부 UIA가 실제 작품 생성·저장·종료·재실행·복원 PASS라는 점과 OS 초기 화면으로 전면 표시가 FAIL이라는 점을 분리하라. Reference→Writer→검수→재작성→Memory→장편→출판까지 전체 실제 통합을 목표로 한다. 근거 없이 모두 완료했다 하지 마라. 장황한 폴링/메시지 전송 타임아웃 방지하고 짧게 결과 보고하라.


## 9. 예약 인수인계 실행 시점 최신 확인 (2026-10-15 13:30 KST)

- 인수인계 GitHub 문서 `docs/validation_20261015_full_handoff.md`는 **검증 브랜치에서 실제 존재 확인**. 커밋 `2ac4d21bef6d3650d1a61ac6c04e59bcf6d9bfaf`는 인수인계 문서만 추가한 커밋. `main` 수정/병합 없음(이 작업에서 수행하지 않음).
- 최신 Actions: PostgreSQL/pgvector/Redis/Celery 통합 `38681732308` **SUCCESS**. Windows 11 실제 데스크톱 QA `38681732410`과 Windows x64 EXE 전체 집필 여정 `38681732387`은 **이 시점 `in_progress`이며 성공/실패 미확정**. 새 대화에서 반드시 최종 상태를 다시 확인할 것.
- 기존 확정 Windows 11 QA `38680175938`은 **FAIL**. 일부 외부 UIA 작품 생성/저장/재실행 복원 성공과 Windows 전경 노출 실패는 별개이며, GUI 사용자 경험은 전면 불합격 판정 유지.
- 예약 실행은 개발 완료를 뜻하지 않는다. **새 대화에 이 파일을 첨부**하고 GitHub 인수인계 문서와 대조할 것. 원본 57섹션/01~100단계는 이 파일에 수록되어 있다.

---

# 별첨 A. 사용자가 제공한 개발 기획안 원문 전체 (변경 없이 보존)

**아래부터 파일 끝까지 `/mnt/data/붙여넣은 마크다운(2).md`의 원문을 그대로 복사했다.** 중복되거나 역슬래시가 포함된 문장도 원본 그대로 유지하였다.

# AI 장편소설 자동 제작·출판 시스템 개발 기획안

## 1. 프로젝트명

**AI Novel Factory**

AI가 단순히 한 편의 글을 생성하는 것이 아니라, 장편소설 전체의 설정·등장인물·사건·복선·시간선·문체를 지속적으로 관리하면서 장기간 자동 집필하고, 참고 작품의 구조적 특징까지 분석하여 새로운 작품 제작에 활용하는 시스템.

최종적으로 작품 기획부터 집필, 교정, 표지 제작, EPUB 제작 및 가능한 플랫폼의 자동 출판까지 연결한다.

---

# 2. 프로젝트 최종 목표

사용자는 최초에 다음 정보만 입력한다.

```
장르
소재
목표 분량
주요 설정
원하는 분위기
참고하고 싶은 소설
```

예:

```
장르: 현대판타지
분량: 250화
회차당: 약 5,000자
주인공: 30대 남성
핵심 소재: 회귀 + 기업경영

참고 작품:
소설 A
소설 B
소설 C
```

이후 시스템이 자동으로 다음 과정을 수행한다.

```
참고소설 분석
↓
작품 기획
↓
세계관 생성
↓
캐릭터 생성
↓
전체 스토리 설계
↓
회차별 플롯 생성
↓
소설 집필
↓
설정 오류 검사
↓
인물 행동 검사
↓
시간선 검사
↓
복선 검사
↓
반복 표현 검사
↓
참고작품 과도 유사성 검사
↓
자동 수정
↓
다음 화 생성
↓
완결
↓
전체 검수
↓
EPUB 제작
↓
표지 제작
↓
출판
```

핵심 목표는 세 가지다.

```
1. 장편소설의 장기 기억 유지
2. 참고 작품의 장점을 구조적으로 분석하여 활용
3. 기존 작품을 복제하지 않고 새로운 작품 생성
```

---

# 3. 핵심 설계 원칙

장편소설 전체를 하나의 프롬프트에 넣지 않는다.

정보를 각각 분리하여 관리한다.

```
Novel Bible
Character DB
World DB
Timeline DB
Relationship DB
Foreshadowing DB
Episode DB
Style Bible
Memory DB
Reference Novel DB
Reference Pattern DB
Similarity DB
```

AI는 다음 화를 작성하기 전에 필요한 정보만 검색하여 사용한다.

---

# 4. 전체 시스템 구조

```
참고소설 업로드
↓
참고소설 분석
↓
Reference Profile 생성
↓
작품 아이디어 생성
↓
Novel Bible 생성
↓
전체 Story Arc 생성
↓
회차 계획
↓
관련 설정 검색
↓
관련 Reference Pattern 검색
↓
이번 화 상세 플롯
↓
초고 작성
↓
Continuity 검사
↓
Logic 검사
↓
Style 검사
↓
Reference Similarity 검사
↓
자동 수정
↓
최종 원고 저장
↓
새로운 사실 추출
↓
Memory DB 업데이트
↓
다음 화
```

---

# 5. 참고소설 분석 기능

## 5.1 목적

사용자가 가지고 있는 소설 파일을 시스템에 넣으면 AI가 해당 작품을 분석한다.

지원 입력 형식:

```
TXT
EPUB
DOCX
PDF
Markdown
```

분석 결과는 원문 자체가 아니라 **작품의 구조와 특징을 데이터화한 Reference Profile**로 저장한다.

---

# 6. Reference Novel Analyzer

참고소설 업로드 후 다음 과정을 자동 수행한다.

```
파일 업로드
↓
텍스트 추출
↓
챕터/회차 분리
↓
문장 분석
↓
스토리 구조 분석
↓
캐릭터 분석
↓
전개 속도 분석
↓
대사 비율 분석
↓
사건 빈도 분석
↓
복선 구조 분석
↓
클리프행어 분석
↓
문체 통계 분석
↓
Reference Profile 생성
```

---

# 7. 참고소설에서 추출할 정보

## 기본 통계

```
전체 분량
회차 수
평균 회차 길이
평균 문장 길이
평균 문단 길이
대사 비율
서술 비율
행동 묘사 비율
내면 묘사 비율
```

---

## 전개 분석

```
첫 사건 발생 위치
첫 갈등 발생 위치
첫 보상 시점
첫 반전 시점
주요 사건 발생 주기
대형 사건 발생 주기
휴식 회차 빈도
클라이맥스 위치
```

예:

```
첫 사건: 1화 20% 지점
첫 보상: 2화
중형 사건: 평균 4.2화마다
대형 사건: 평균 24화마다
```

---

## 회차 구조 분석

각 회차를 다음 구조로 분석한다.

```
도입
상황 설명
갈등
전개
보상
반전
클리프행어
```

예:

```
도입: 10%
전개: 45%
갈등: 20%
보상: 15%
클리프행어: 10%
```

---

# 8. 클리프행어 분석

각 회차 마지막 부분을 분석한다.

유형:

```
정보 공개
위기 발생
새로운 적 등장
반전
약속
미스터리
보상 직전 종료
전투 직전 종료
```

Reference Profile에 다음과 같이 저장한다.

```
회차말 클리프행어 사용률: 82%

주요 유형:
정보 공개 31%
위기 발생 27%
반전 18%
기타 24%
```

---

# 9. 캐릭터 구조 분석

참고 작품의 등장인물을 분석한다.

```
주인공 수
조연 수
악역 수
등장인물 등장 간격
캐릭터 재등장 빈도
캐릭터별 대사 비율
관계 변화 속도
캐릭터 퇴장 방식
```

특정 이름이나 설정을 복제하지 않고 구조만 저장한다.

예:

```
주인공
↓
라이벌
↓
초기 동료
↓
멘토
↓
중간 배신자
↓
최종 적대자
```

---

# 10. 관계 변화 분석

참고작에서 관계 변화 속도를 분석한다.

예:

```
첫 만남
↓
경계
↓
협력
↓
신뢰
↓
갈등
↓
재결합
```

변화에 걸린 회차도 기록한다.

---

# 11. 복선 패턴 분석

다음 요소를 추출한다.

```
복선 설치 위치
복선 회수 위치
평균 회수 기간
복선 유형
복선 재언급 횟수
```

예:

```
복선 설치: 12화
중간 암시: 31화
추가 암시: 54화
회수: 79화
```

---

# 12. 감정곡선 분석

회차 또는 Arc 단위 감정 변화를 분석한다.

예:

```
안정
↓
불안
↓
위기
↓
절망
↓
반격
↓
보상
```

또는 수치화한다.

```
Episode 1: 0.3
Episode 2: 0.5
Episode 3: -0.2
Episode 4: -0.7
Episode 5: 0.8
```

---

# 13. 장르 공식 분석

여러 참고소설을 넣으면 공통 패턴을 추출한다.

예:

```
현대판타지 인기작 30편
↓
공통 구조 분석
↓
Genre Pattern 생성
```

결과 예:

```
1~3화:
능력 또는 특수상황 공개

4~10화:
첫 성공

10~30화:
능력 검증

30~50화:
첫 대형 경쟁자

50~100화:
세계 확장
```

이 정보는 새로운 작품의 Story Arc 생성에 사용할 수 있다.

---

# 14. Reference Profile

한 작품 분석 결과를 다음과 같이 저장한다.

```
{
  "reference_id": "REF001",
  "genre": "현대판타지",
  "avg_episode_length": 4800,
  "dialogue_ratio": 0.41,
  "description_ratio": 0.29,
  "first_major_event": 2,
  "minor_event_interval": 4.3,
  "major_event_interval": 23.5,
  "cliffhanger_rate": 0.84,
  "avg_sentence_length": 19,
  "plot_speed": "fast"
}
```

---

# 15. 다중 참고소설 분석

사용자는 여러 작품을 동시에 등록할 수 있다.

```
소설 A
소설 B
소설 C
소설 D
```

시스템은 각각의 Profile을 만든다.

그 후:

```
Reference A
+
Reference B
+
Reference C
+
Reference D
↓
Pattern Aggregator
↓
Genre / Style Profile
```

공통적인 특징과 작품별 고유 특징을 분리한다.

---

# 16. 참고 강도 설정

사용자가 작품마다 참고 강도를 지정할 수 있다.

```
소설 A: 50%
소설 B: 30%
소설 C: 20%
```

또는 기능별로 지정한다.

```
소설 A
전개 방식: 강하게
캐릭터 구조: 보통
문체: 사용 안 함

소설 B
복선 구조: 강하게
전개 방식: 약하게
```

---

# 17. 참고 항목 선택

사용자 UI:

```
[참고할 요소]

☑ 전개 속도
☑ 회차 구조
☑ 클리프행어
☑ 복선
☑ 캐릭터 관계 변화
☑ 사건 발생 주기
☑ 감정곡선
☑ 대사 비율
☐ 문체
```

특정 항목만 선택할 수 있다.

---

# 18. Style Analysis

문체도 분석할 수 있다.

단, 특정 작가의 문장을 그대로 재현하는 방식이 아니라 다음 특징을 수치화한다.

```
평균 문장 길이
짧은 문장 비율
대화 비율
서술 비율
1인칭/3인칭
문단 길이
행동 중심도
심리 묘사 비율
비유 사용 빈도
의성어 사용 빈도
```

새 작품에서는 이 통계만 참고한다.

---

# 19. Reference Pattern Library

여러 작품에서 발견한 패턴을 재사용 가능한 형태로 저장한다.

예:

```
PATTERN_001

장르:
회귀물

패턴:
초반 3화 안에 주인공이 미래정보를 이용해 첫 성공

효과:
주인공 능력 증명

추천 위치:
1~5화
```

---

# 20. 유사성 방지 시스템

참고 작품을 사용하는 경우 반드시 Similarity Checker를 실행한다.

검사 대상:

```
문장 유사도
장면 유사도
캐릭터 설정 유사도
사건 순서 유사도
고유명사 유사도
대사 유사도
```

특정 작품과 지나치게 유사한 경우 자동 재작성한다.

```
SIMILARITY TOO HIGH
↓
문제 Scene 식별
↓
Plot Variation 생성
↓
Rewrite
↓
재검사
```

---

# 21. Novel Bible

Novel Bible은 새 작품 자체의 절대 기준이다.

```
제목
장르
로그라인
핵심 소재
전체 분위기
시점
문체
타깃 독자
예상 총 회차
세계관
주요 갈등
최종 결말
```

Reference Profile은 Novel Bible보다 우선하지 않는다.

즉:

```
Novel Bible
>
Reference Profile
```

작품 고유 설정이 항상 우선한다.

---

# 22. Character Database

각 등장인물을 독립 객체로 관리한다.

```
{
  "character_id": "C001",
  "name": "김도윤",
  "age": 34,
  "job": "기업 인수 전문가",
  "personality": [
    "냉정함",
    "계산적"
  ],
  "speech_style": "짧고 단정함",
  "knowledge": [],
  "relationships": {},
  "goals": [],
  "secrets": []
}
```

---

# 23. Character Knowledge

각 인물이 알고 있는 정보를 따로 관리한다.

예:

```
김도윤:
회귀 사실 알고 있음

박서연:
회귀 사실 모름

최민석:
김도윤이 투자자라는 것만 알고 있음
```

이 시스템으로 등장인물이 알 수 없는 정보를 말하는 오류를 방지한다.

---

# 24. Relationship Database

인물 관계를 시간에 따라 관리한다.

```
김도윤 → 박서연

1화:
경계

30화:
협력

65화:
신뢰

110화:
연애감정
```

---

# 25. World Database

세계관 정보를 저장한다.

```
회사
학교
국가
길드
마법
경제
화폐
기술
지역
아이템
능력
조직
```

---

# 26. Timeline Database

모든 주요 사건에 날짜 또는 상대시간을 기록한다.

```
2026-03-01 : 회귀
2026-03-03 : 첫 투자
2026-03-15 : 박서연 등장
2026-04-02 : 세광전자 인수
```

---

# 27. Foreshadowing Database

복선을 데이터로 관리한다.

```
{
  "id": "F013",
  "setup_episode": 12,
  "description": "회장의 검은 수첩",
  "planned_payoff": 87,
  "status": "OPEN"
}
```

상태:

```
OPEN
DEVELOPING
RESOLVED
ABANDONED
```

---

# 28. 전체 Story Arc

작품 전체를 Arc 단위로 설계한다.

```
ARC 1
1~30화

ARC 2
31~70화

ARC 3
71~120화

ARC 4
121~180화

ARC 5
181~230화

FINAL ARC
231~250화
```

Reference Pattern은 이 단계에서 활용한다.

예:

```
참고 작품들의 평균 대형 사건 간격:
약 25화

새 작품:
약 20~30화마다 대형 사건 배치
```

그대로 복사하지 않고 통계적 구조만 사용한다.

---

# 29. Episode Planner

각 회차 전에 다음 정보를 생성한다.

```
Episode
목적
필수 사건
등장인물
감정 흐름
사용할 복선
새로운 복선
보상
갈등
마지막 Hook
```

Reference Profile에서 관련 패턴도 가져온다.

---

# 30. Scene Planner

한 회를 여러 Scene으로 분리한다.

```
Scene 1
목적
등장인물
장소
갈등
감정

Scene 2
...

Scene 3
...
```

---

# 31. Writer Engine

Writer에게 전달하는 Context:

```
Novel Bible
현재 Arc
현재 Episode Plan
현재 Scene
관련 Character DB
Relationship DB
Timeline
Foreshadowing
최근 회차 요약
Style Bible
관련 Reference Pattern
```

전체 참고소설 원문을 Writer에게 그대로 제공하지 않는다.

---

# 32. Style Bible

작품 자체 문체를 저장한다.

예:

```
문장 길이: 짧음
대화 비율: 45%
설명 비율: 30%
행동 비율: 25%

시점:
3인칭 제한

금지:
과도한 비유
같은 감정 반복

선호:
빠른 전개
짧은 문단
강한 회차 Hook
```

---

# 33. 반복 표현 감지

AI 특유의 반복을 추적한다.

예:

```
피식 웃었다.
눈빛이 가라앉았다.
입꼬리가 올라갔다.
말없이 바라보았다.
```

최근 N화에서 일정 횟수 이상 사용된 표현은 자동 제한한다.

---

# 34. Continuity Checker

검사:

```
이름
나이
성별
직업
외모
능력
장소
날짜
시간
관계
사망 여부
보유 아이템
지식 범위
복선
```

---

# 35. Logic Checker

검사:

```
행동에 동기가 있는가
우연에 과도하게 의존하는가
갑작스러운 능력이 등장하는가
인물이 모르는 정보를 사용하는가
이전 설정과 충돌하는가
사건 해결이 지나치게 편리한가
```

---

# 36. Reference Similarity Checker

참고 작품을 등록한 경우 추가로 실행한다.

검사:

```
특정 문장 유사
장면 진행 순서 유사
고유 설정 유사
캐릭터 조합 유사
사건 해결 방식 유사
```

위험도가 높으면 다시 생성한다.

---

# 37. Reader Simulation

가상의 독자 AI를 사용한다.

예:

```
웹소설 독자
판타지 독자
로맨스 독자
까다로운 독자
```

평가:

```
몰입도
전개속도
캐릭터 매력
갈등
보상
클리프행어
지루한 구간
```

---

# 38. 자동 수정

예:

```
Continuity: PASS
Logic: PASS
Similarity: FAIL
Hook: PASS
```

이면 전체 회차가 아니라 문제 Scene만 다시 생성한다.

---

# 39. Memory Update

최종 회차 확정 후 새로운 정보를 추출한다.

```
새 캐릭터
새 장소
새 사건
관계 변화
새로운 정보
획득 아이템
새 복선
회수된 복선
```

이후 DB를 업데이트한다.

---

# 40. 회차 저장 구조

```
episode_001/

outline.json
scenes.json
draft.md
final.md
summary.json
memory_delta.json
reference_usage.json
similarity_report.json
```

---

# 41. 장편 기억 구조

```
PostgreSQL
↓
정확한 설정 데이터

Vector DB
↓
과거 장면 의미검색

Episode Summary
↓
과거 줄거리

Raw Manuscript
↓
원문 확인

Reference DB
↓
참고 작품 분석 정보
```

---

# 42. 자동 집필 Scheduler

```
매일 03:00

Episode Planner
↓
Reference Pattern Retrieval
↓
Context Retrieval
↓
Scene Planning
↓
Draft
↓
Continuity Check
↓
Logic Check
↓
Similarity Check
↓
Style Check
↓
Rewrite
↓
Final
↓
Memory Update
↓
Publishing Queue
```

---

# 43. 표지 자동 생성

입력:

```
장르
주인공
세계관
분위기
제목
```

출력:

```
cover.jpg
thumbnail.jpg
```

참고소설의 표지를 복제하지 않는다.

---

# 44. EPUB 자동 제작

완결 또는 지정 분량마다:

```
book.epub
cover.jpg
metadata.xml
```

을 생성한다.

---

# 45. 출판 방식

## 웹소설

플랫폼별 Publisher Adapter를 만든다.

공식 API가 있는 경우:

```
자동 업로드
```

공식 API가 없는 경우:

```
episode_title.txt
episode_body.txt
author_note.txt
thumbnail.jpg
```

까지 자동 생성한다.

---

# 46. 전자책

다음 자료를 자동 생성한다.

```
EPUB
Cover
Metadata
가격정보
작품설명
키워드
카테고리
```

---

# 47. 완결 검사

마지막 화 이후 전체 작품을 검사한다.

```
미회수 복선
사라진 등장인물
미해결 갈등
Timeline 오류
설정 충돌
결말 불일치
```

모든 문제가 해결되어야 완결 처리한다.

---

# 48. 관리자 화면

```
[작품]

[Novel Bible]

[Characters]

[World]

[Timeline]

[Relationships]

[Foreshadowing]

[Reference Novels]

[Reference Patterns]

[Episodes]

[Similarity Reports]

[Publication]
```

---

# 49. 참고소설 관리 화면

```
[참고소설 추가]

파일 업로드

소설 A
소설 B
소설 C

[분석 시작]
```

분석 완료 후:

```
전개 속도
문장 통계
대사 비율
복선 패턴
클리프행어 패턴
캐릭터 구조
사건 간격
감정곡선
```

을 확인할 수 있다.

---

# 50. 참고 설정 화면

예:

```
소설 A

전개 속도        80%
회차 구조        60%
클리프행어       70%
복선 방식        30%
캐릭터 구조      20%
문체             0%
```

사용자는 참고하고 싶은 부분만 지정한다.

---

# 51. 백엔드 구조

```
novel-factory/

app/
    orchestrator/
    planner/
    writer/
    editor/
    continuity/
    memory/
    publishing/

reference/
    importer/
    parser/
    analyzer/
    structure/
    character/
    pacing/
    style/
    pattern/
    similarity/

database/
    characters/
    worlds/
    timeline/
    relationships/
    foreshadowing/
    references/
    episodes/

generation/
    premise/
    outline/
    episode/
    scene/

quality/
    continuity_checker/
    logic_checker/
    style_checker/
    repetition_checker/
    similarity_checker/
    reader_simulator/

publishing/
    epub/
    metadata/
    webnovel_adapters/

assets/
    covers/
```

---

# 52. 기술 스택

Backend:

```
Python
FastAPI
```

Database:

```
PostgreSQL
```

Vector Search:

```
pgvector
```

Queue:

```
Redis
Celery
```

Document Parser:

```
EPUB Parser
PDF Parser
DOCX Parser
TXT Parser
```

문서:

```
Markdown
JSON
EPUB3
```

---

# 53. API

참고소설 등록:

```
POST /references
```

참고소설 분석:

```
POST /references/{reference_id}/analyze
```

작품과 참고소설 연결:

```
POST /novels/{novel_id}/references
```

예:

```
{
  "reference_id": "REF001",
  "weights": {
    "pacing": 0.8,
    "cliffhanger": 0.7,
    "character_structure": 0.3,
    "style": 0
  }
}
```

---

# 54. 작품 생성 API

```
POST /novels
```

예:

```
{
  "genre": "현대판타지",
  "episodes": 250,
  "characters_per_episode": 5000,
  "reference_ids": [
    "REF001",
    "REF002"
  ],
  "publishing_mode": "automatic"
}
```

---

# 55. 개발 우선순위

## Phase 1

**Reference Analyzer 개발**

```
TXT
EPUB
PDF
↓
회차 분리
↓
구조 분석
↓
Reference Profile
```

---

## Phase 2

**장편 Memory 시스템**

```
Novel Bible
Character DB
Timeline
Relationship DB
Foreshadowing DB
```

---

## Phase 3

**Writer + Reference Pattern 연동**

참고소설의 패턴을 새 작품 계획에 사용한다.

---

## Phase 4

**Similarity Checker**

참고 작품과 지나치게 비슷해지는 것을 방지한다.

---

## Phase 5

**30화 연속 생성**

설정 오류와 Reference Pattern 적용을 평가한다.

---

## Phase 6

**100화 이상 장기 테스트**

장기 기억과 복선 회수 성능을 검증한다.

---

## Phase 7

**EPUB / 출판 자동화**

최종 파일 생성 및 출판 Adapter 구축.

---

# 56. 시스템 핵심 규칙

첫째, 참고소설 원문을 그대로 새 작품에 복사하지 않는다.

둘째, 참고소설은 **구조 분석 데이터**로 사용한다.

셋째, 특정 작품의 고유명사·세계관·캐릭터를 자동으로 가져오지 않는다.

넷째, 참고작품보다 새 작품의 Novel Bible이 항상 우선한다.

다섯째, Reference Similarity Checker를 항상 실행한다.

여섯째, 여러 참고작품의 공통적인 성공 패턴을 추출할 수 있어야 한다.

일곱째, 장르별 Reference Library를 축적할 수 있어야 한다.

---

# 57. 최종 목표

사용자는 다음처럼 요청할 수 있다.

```
현대판타지 소설을 만들어줘.

참고소설:
A
B
C

A에서는 빠른 전개만 참고.
B에서는 복선 구조 참고.
C에서는 캐릭터 관계 변화 참고.

250화.
회차당 약 5,000자.
```

시스템은 자동으로:

```
참고소설 분석
↓
공통 패턴 추출
↓
새로운 세계관 생성
↓
새로운 캐릭터 생성
↓
새로운 전체 스토리 생성
↓
250화 집필
↓
설정 검수
↓
복선 관리
↓
유사성 검사
↓
수정
↓
완결
↓
EPUB
↓
표지
↓
출판
```

을 수행한다.

최종 사용자 경험은 다음을 목표로 한다.

**“내가 좋아하는 여러 소설을 넣으면, 그 작품들을 복사하는 것이 아니라 왜 재미있는지 구조적으로 분석하고 그 장점을 이용해 완전히 새로운 장편소설을 자동으로 만들어주는 시스템.”# AI 장편소설 자동 제작·출판 시스템 개발 기획안\n**\
\n## 1. 프로젝트명\n\n\*\*AI Novel Factory\*\*\n\nAI가 단순히 한 편의 글을 생성하는 것이 아니라, 장편소설 전체의 설정·등장인물·사건·복선·시간선·문체를 지속적으로 관리하면서 장기간 자동 집필하고, 참고 작품의 구조적 특징까지 분석하여 새로운 작품 제작에 활용하는 시스템.\n\n최종적으로 작품 기획부터 집필, 교정, 표지 제작, EPUB 제작 및 가능한 플랫폼의 자동 출판까지 연결한다.\n\n---\n\n# 2. 프로젝트 최종 목표\n\n사용자는 최초에 다음 정보만 입력한다.\n\n\`\`\`text\n장르\n소재\n목표 분량\n주요 설정\n원하는 분위기\n참고하고 싶은 소설\n\`\`\`\n\n예:\n\n\`\`\`text\n장르: 현대판타지\n분량: 250화\n회차당: 약 5,000자\n주인공: 30대 남성\n핵심 소재: 회귀 + 기업경영\n\n참고 작품:\n소설 A\n소설 B\n소설 C\n\`\`\`\n\n이후 시스템이 자동으로 다음 과정을 수행한다.\n\n\`\`\`text\n참고소설 분석\n↓\n작품 기획\n↓\n세계관 생성\n↓\n캐릭터 생성\n↓\n전체 스토리 설계\n↓\n회차별 플롯 생성\n↓\n소설 집필\n↓\n설정 오류 검사\n↓\n인물 행동 검사\n↓\n시간선 검사\n↓\n복선 검사\n↓\n반복 표현 검사\n↓\n참고작품 과도 유사성 검사\n↓\n자동 수정\n↓\n다음 화 생성\n↓\n완결\n↓\n전체 검수\n↓\nEPUB 제작\n↓\n표지 제작\n↓\n출판\n\`\`\`\n\n핵심 목표는 세 가지다.\n\n\`\`\`text\n1. 장편소설의 장기 기억 유지\n2. 참고 작품의 장점을 구조적으로 분석하여 활용\n3. 기존 작품을 복제하지 않고 새로운 작품 생성\n\`\`\`\n\n---\n\n# 3. 핵심 설계 원칙\n\n장편소설 전체를 하나의 프롬프트에 넣지 않는다.\n\n정보를 각각 분리하여 관리한다.\n\n\`\`\`text\nNovel Bible\nCharacter DB\nWorld DB\nTimeline DB\nRelationship DB\nForeshadowing DB\nEpisode DB\nStyle Bible\nMemory DB\nReference Novel DB\nReference Pattern DB\nSimilarity DB\n\`\`\`\n\nAI는 다음 화를 작성하기 전에 필요한 정보만 검색하여 사용한다.\n\n---\n\n# 4. 전체 시스템 구조\n\n\`\`\`text\n참고소설 업로드\n↓\n참고소설 분석\n↓\nReference Profile 생성\n↓\n작품 아이디어 생성\n↓\nNovel Bible 생성\n↓\n전체 Story Arc 생성\n↓\n회차 계획\n↓\n관련 설정 검색\n↓\n관련 Reference Pattern 검색\n↓\n이번 화 상세 플롯\n↓\n초고 작성\n↓\nContinuity 검사\n↓\nLogic 검사\n↓\nStyle 검사\n↓\nReference Similarity 검사\n↓\n자동 수정\n↓\n최종 원고 저장\n↓\n새로운 사실 추출\n↓\nMemory DB 업데이트\n↓\n다음 화\n\`\`\`\n\n---\n\n# 5. 참고소설 분석 기능\n\n## 5.1 목적\n\n사용자가 가지고 있는 소설 파일을 시스템에 넣으면 AI가 해당 작품을 분석한다.\n\n지원 입력 형식:\n\n\`\`\`text\nTXT\nEPUB\nDOCX\nPDF\nMarkdown\n\`\`\`\n\n분석 결과는 원문 자체가 아니라 \*\*작품의 구조와 특징을 데이터화한 Reference Profile\*\*로 저장한다.\n\n---\n\n# 6. Reference Novel Analyzer\n\n참고소설 업로드 후 다음 과정을 자동 수행한다.\n\n\`\`\`text\n파일 업로드\n↓\n텍스트 추출\n↓\n챕터/회차 분리\n↓\n문장 분석\n↓\n스토리 구조 분석\n↓\n캐릭터 분석\n↓\n전개 속도 분석\n↓\n대사 비율 분석\n↓\n사건 빈도 분석\n↓\n복선 구조 분석\n↓\n클리프행어 분석\n↓\n문체 통계 분석\n↓\nReference Profile 생성\n\`\`\`\n\n---\n\n# 7. 참고소설에서 추출할 정보\n\n## 기본 통계\n\n\`\`\`text\n전체 분량\n회차 수\n평균 회차 길이\n평균 문장 길이\n평균 문단 길이\n대사 비율\n서술 비율\n행동 묘사 비율\n내면 묘사 비율\n\`\`\`\n\n---\n\n## 전개 분석\n\n\`\`\`text\n첫 사건 발생 위치\n첫 갈등 발생 위치\n첫 보상 시점\n첫 반전 시점\n주요 사건 발생 주기\n대형 사건 발생 주기\n휴식 회차 빈도\n클라이맥스 위치\n\`\`\`\n\n예:\n\n\`\`\`text\n첫 사건: 1화 20% 지점\n첫 보상: 2화\n중형 사건: 평균 4.2화마다\n대형 사건: 평균 24화마다\n\`\`\`\n\n---\n\n## 회차 구조 분석\n\n각 회차를 다음 구조로 분석한다.\n\n\`\`\`text\n도입\n상황 설명\n갈등\n전개\n보상\n반전\n클리프행어\n\`\`\`\n\n예:\n\n\`\`\`text\n도입: 10%\n전개: 45%\n갈등: 20%\n보상: 15%\n클리프행어: 10%\n\`\`\`\n\n---\n\n# 8. 클리프행어 분석\n\n각 회차 마지막 부분을 분석한다.\n\n유형:\n\n\`\`\`text\n정보 공개\n위기 발생\n새로운 적 등장\n반전\n약속\n미스터리\n보상 직전 종료\n전투 직전 종료\n\`\`\`\n\nReference Profile에 다음과 같이 저장한다.\n\n\`\`\`text\n회차말 클리프행어 사용률: 82%\n\n주요 유형:\n정보 공개 31%\n위기 발생 27%\n반전 18%\n기타 24%\n\`\`\`\n\n---\n\n# 9. 캐릭터 구조 분석\n\n참고 작품의 등장인물을 분석한다.\n\n\`\`\`text\n주인공 수\n조연 수\n악역 수\n등장인물 등장 간격\n캐릭터 재등장 빈도\n캐릭터별 대사 비율\n관계 변화 속도\n캐릭터 퇴장 방식\n\`\`\`\n\n특정 이름이나 설정을 복제하지 않고 구조만 저장한다.\n\n예:\n\n\`\`\`text\n주인공\n↓\n라이벌\n↓\n초기 동료\n↓\n멘토\n↓\n중간 배신자\n↓\n최종 적대자\n\`\`\`\n\n---\n\n# 10. 관계 변화 분석\n\n참고작에서 관계 변화 속도를 분석한다.\n\n예:\n\n\`\`\`text\n첫 만남\n↓\n경계\n↓\n협력\n↓\n신뢰\n↓\n갈등\n↓\n재결합\n\`\`\`\n\n변화에 걸린 회차도 기록한다.\n\n---\n\n# 11. 복선 패턴 분석\n\n다음 요소를 추출한다.\n\n\`\`\`text\n복선 설치 위치\n복선 회수 위치\n평균 회수 기간\n복선 유형\n복선 재언급 횟수\n\`\`\`\n\n예:\n\n\`\`\`text\n복선 설치: 12화\n중간 암시: 31화\n추가 암시: 54화\n회수: 79화\n\`\`\`\n\n---\n\n# 12. 감정곡선 분석\n\n회차 또는 Arc 단위 감정 변화를 분석한다.\n\n예:\n\n\`\`\`text\n안정\n↓\n불안\n↓\n위기\n↓\n절망\n↓\n반격\n↓\n보상\n\`\`\`\n\n또는 수치화한다.\n\n\`\`\`text\nEpisode 1: 0.3\nEpisode 2: 0.5\nEpisode 3: -0.2\nEpisode 4: -0.7\nEpisode 5: 0.8\n\`\`\`\n\n---\n\n# 13. 장르 공식 분석\n\n여러 참고소설을 넣으면 공통 패턴을 추출한다.\n\n예:\n\n\`\`\`text\n현대판타지 인기작 30편\n↓\n공통 구조 분석\n↓\nGenre Pattern 생성\n\`\`\`\n\n결과 예:\n\n\`\`\`text\n1\~3화:\n능력 또는 특수상황 공개\n\n4\~10화:\n첫 성공\n\n10\~30화:\n능력 검증\n\n30\~50화:\n첫 대형 경쟁자\n\n50\~100화:\n세계 확장\n\`\`\`\n\n이 정보는 새로운 작품의 Story Arc 생성에 사용할 수 있다.\n\n---\n\n# 14. Reference Profile\n\n한 작품 분석 결과를 다음과 같이 저장한다.\n\n\`\`\`json\n{\n  "reference_id": "REF001",\n  "genre": "현대판타지",\n  "avg_episode_length": 4800,\n  "dialogue_ratio": 0.41,\n  "description_ratio": 0.29,\n  "first_major_event": 2,\n  "minor_event_interval": 4.3,\n  "major_event_interval": 23.5,\n  "cliffhanger_rate": 0.84,\n  "avg_sentence_length": 19,\n  "plot_speed": "fast"\n}\n\`\`\`\n\n---\n\n# 15. 다중 참고소설 분석\n\n사용자는 여러 작품을 동시에 등록할 수 있다.\n\n\`\`\`text\n소설 A\n소설 B\n소설 C\n소설 D\n\`\`\`\n\n시스템은 각각의 Profile을 만든다.\n\n그 후:\n\n\`\`\`text\nReference A\n+\nReference B\n+\nReference C\n+\nReference D\n↓\nPattern Aggregator\n↓\nGenre / Style Profile\n\`\`\`\n\n공통적인 특징과 작품별 고유 특징을 분리한다.\n\n---\n\n# 16. 참고 강도 설정\n\n사용자가 작품마다 참고 강도를 지정할 수 있다.\n\n\`\`\`text\n소설 A: 50%\n소설 B: 30%\n소설 C: 20%\n\`\`\`\n\n또는 기능별로 지정한다.\n\n\`\`\`text\n소설 A\n전개 방식: 강하게\n캐릭터 구조: 보통\n문체: 사용 안 함\n\n소설 B\n복선 구조: 강하게\n전개 방식: 약하게\n\`\`\`\n\n---\n\n# 17. 참고 항목 선택\n\n사용자 UI:\n\n\`\`\`text\n[참고할 요소]\n\n☑ 전개 속도\n☑ 회차 구조\n☑ 클리프행어\n☑ 복선\n☑ 캐릭터 관계 변화\n☑ 사건 발생 주기\n☑ 감정곡선\n☑ 대사 비율\n☐ 문체\n\`\`\`\n\n특정 항목만 선택할 수 있다.\n\n---\n\n# 18. Style Analysis\n\n문체도 분석할 수 있다.\n\n단, 특정 작가의 문장을 그대로 재현하는 방식이 아니라 다음 특징을 수치화한다.\n\n\`\`\`text\n평균 문장 길이\n짧은 문장 비율\n대화 비율\n서술 비율\n1인칭/3인칭\n문단 길이\n행동 중심도\n심리 묘사 비율\n비유 사용 빈도\n의성어 사용 빈도\n\`\`\`\n\n새 작품에서는 이 통계만 참고한다.\n\n---\n\n# 19. Reference Pattern Library\n\n여러 작품에서 발견한 패턴을 재사용 가능한 형태로 저장한다.\n\n예:\n\n\`\`\`text\nPATTERN_001\n\n장르:\n회귀물\n\n패턴:\n초반 3화 안에 주인공이 미래정보를 이용해 첫 성공\n\n효과:\n주인공 능력 증명\n\n추천 위치:\n1\~5화\n\`\`\`\n\n---\n\n# 20. 유사성 방지 시스템\n\n참고 작품을 사용하는 경우 반드시 Similarity Checker를 실행한다.\n\n검사 대상:\n\n\`\`\`text\n문장 유사도\n장면 유사도\n캐릭터 설정 유사도\n사건 순서 유사도\n고유명사 유사도\n대사 유사도\n\`\`\`\n\n특정 작품과 지나치게 유사한 경우 자동 재작성한다.\n\n\`\`\`text\nSIMILARITY TOO HIGH\n↓\n문제 Scene 식별\n↓\nPlot Variation 생성\n↓\nRewrite\n↓\n재검사\n\`\`\`\n\n---\n\n# 21. Novel Bible\n\nNovel Bible은 새 작품 자체의 절대 기준이다.\n\n\`\`\`text\n제목\n장르\n로그라인\n핵심 소재\n전체 분위기\n시점\n문체\n타깃 독자\n예상 총 회차\n세계관\n주요 갈등\n최종 결말\n\`\`\`\n\nReference Profile은 Novel Bible보다 우선하지 않는다.\n\n즉:\n\n\`\`\`text\nNovel Bible\n>\nReference Profile\n\`\`\`\n\n작품 고유 설정이 항상 우선한다.\n\n---\n\n# 22. Character Database\n\n각 등장인물을 독립 객체로 관리한다.\n\n\`\`\`json\n{\n  "character_id": "C001",\n  "name": "김도윤",\n  "age": 34,\n  "job": "기업 인수 전문가",\n  "personality": [\n    "냉정함",\n    "계산적"\n  ],\n  "speech_style": "짧고 단정함",\n  "knowledge": [],\n  "relationships": {},\n  "goals": [],\n  "secrets": []\n}\n\`\`\`\n\n---\n\n# 23. Character Knowledge\n\n각 인물이 알고 있는 정보를 따로 관리한다.\n\n예:\n\n\`\`\`text\n김도윤:\n회귀 사실 알고 있음\n\n박서연:\n회귀 사실 모름\n\n최민석:\n김도윤이 투자자라는 것만 알고 있음\n\`\`\`\n\n이 시스템으로 등장인물이 알 수 없는 정보를 말하는 오류를 방지한다.\n\n---\n\n# 24. Relationship Database\n\n인물 관계를 시간에 따라 관리한다.\n\n\`\`\`text\n김도윤 → 박서연\n\n1화:\n경계\n\n30화:\n협력\n\n65화:\n신뢰\n\n110화:\n연애감정\n\`\`\`\n\n---\n\n# 25. World Database\n\n세계관 정보를 저장한다.\n\n\`\`\`text\n회사\n학교\n국가\n길드\n마법\n경제\n화폐\n기술\n지역\n아이템\n능력\n조직\n\`\`\`\n\n---\n\n# 26. Timeline Database\n\n모든 주요 사건에 날짜 또는 상대시간을 기록한다.\n\n\`\`\`text\n2026-03-01 : 회귀\n2026-03-03 : 첫 투자\n2026-03-15 : 박서연 등장\n2026-04-02 : 세광전자 인수\n\`\`\`\n\n---\n\n# 27. Foreshadowing Database\n\n복선을 데이터로 관리한다.\n\n\`\`\`json\n{\n  "id": "F013",\n  "setup_episode": 12,\n  "description": "회장의 검은 수첩",\n  "planned_payoff": 87,\n  "status": "OPEN"\n}\n\`\`\`\n\n상태:\n\n\`\`\`text\nOPEN\nDEVELOPING\nRESOLVED\nABANDONED\n\`\`\`\n\n---\n\n# 28. 전체 Story Arc\n\n작품 전체를 Arc 단위로 설계한다.\n\n\`\`\`text\nARC 1\n1\~30화\n\nARC 2\n31\~70화\n\nARC 3\n71\~120화\n\nARC 4\n121\~180화\n\nARC 5\n181\~230화\n\nFINAL ARC\n231\~250화\n\`\`\`\n\nReference Pattern은 이 단계에서 활용한다.\n\n예:\n\n\`\`\`text\n참고 작품들의 평균 대형 사건 간격:\n약 25화\n\n새 작품:\n약 20\~30화마다 대형 사건 배치\n\`\`\`\n\n그대로 복사하지 않고 통계적 구조만 사용한다.\n\n---\n\n# 29. Episode Planner\n\n각 회차 전에 다음 정보를 생성한다.\n\n\`\`\`text\nEpisode\n목적\n필수 사건\n등장인물\n감정 흐름\n사용할 복선\n새로운 복선\n보상\n갈등\n마지막 Hook\n\`\`\`\n\nReference Profile에서 관련 패턴도 가져온다.\n\n---\n\n# 30. Scene Planner\n\n한 회를 여러 Scene으로 분리한다.\n\n\`\`\`text\nScene 1\n목적\n등장인물\n장소\n갈등\n감정\n\nScene 2\n...\n\nScene 3\n...\n\`\`\`\n\n---\n\n# 31. Writer Engine\n\nWriter에게 전달하는 Context:\n\n\`\`\`text\nNovel Bible\n현재 Arc\n현재 Episode Plan\n현재 Scene\n관련 Character DB\nRelationship DB\nTimeline\nForeshadowing\n최근 회차 요약\nStyle Bible\n관련 Reference Pattern\n\`\`\`\n\n전체 참고소설 원문을 Writer에게 그대로 제공하지 않는다.\n\n---\n\n# 32. Style Bible\n\n작품 자체 문체를 저장한다.\n\n예:\n\n\`\`\`text\n문장 길이: 짧음\n대화 비율: 45%\n설명 비율: 30%\n행동 비율: 25%\n\n시점:\n3인칭 제한\n\n금지:\n과도한 비유\n같은 감정 반복\n\n선호:\n빠른 전개\n짧은 문단\n강한 회차 Hook\n\`\`\`\n\n---\n\n# 33. 반복 표현 감지\n\nAI 특유의 반복을 추적한다.\n\n예:\n\n\`\`\`text\n피식 웃었다.\n눈빛이 가라앉았다.\n입꼬리가 올라갔다.\n말없이 바라보았다.\n\`\`\`\n\n최근 N화에서 일정 횟수 이상 사용된 표현은 자동 제한한다.\n\n---\n\n# 34. Continuity Checker\n\n검사:\n\n\`\`\`text\n이름\n나이\n성별\n직업\n외모\n능력\n장소\n날짜\n시간\n관계\n사망 여부\n보유 아이템\n지식 범위\n복선\n\`\`\`\n\n---\n\n# 35. Logic Checker\n\n검사:\n\n\`\`\`text\n행동에 동기가 있는가\n우연에 과도하게 의존하는가\n갑작스러운 능력이 등장하는가\n인물이 모르는 정보를 사용하는가\n이전 설정과 충돌하는가\n사건 해결이 지나치게 편리한가\n\`\`\`\n\n---\n\n# 36. Reference Similarity Checker\n\n참고 작품을 등록한 경우 추가로 실행한다.\n\n검사:\n\n\`\`\`text\n특정 문장 유사\n장면 진행 순서 유사\n고유 설정 유사\n캐릭터 조합 유사\n사건 해결 방식 유사\n\`\`\`\n\n위험도가 높으면 다시 생성한다.\n\n---\n\n# 37. Reader Simulation\n\n가상의 독자 AI를 사용한다.\n\n예:\n\n\`\`\`text\n웹소설 독자\n판타지 독자\n로맨스 독자\n까다로운 독자\n\`\`\`\n\n평가:\n\n\`\`\`text\n몰입도\n전개속도\n캐릭터 매력\n갈등\n보상\n클리프행어\n지루한 구간\n\`\`\`\n\n---\n\n# 38. 자동 수정\n\n예:\n\n\`\`\`text\nContinuity: PASS\nLogic: PASS\nSimilarity: FAIL\nHook: PASS\n\`\`\`\n\n이면 전체 회차가 아니라 문제 Scene만 다시 생성한다.\n\n---\n\n# 39. Memory Update\n\n최종 회차 확정 후 새로운 정보를 추출한다.\n\n\`\`\`text\n새 캐릭터\n새 장소\n새 사건\n관계 변화\n새로운 정보\n획득 아이템\n새 복선\n회수된 복선\n\`\`\`\n\n이후 DB를 업데이트한다.\n\n---\n\n# 40. 회차 저장 구조\n\n\`\`\`text\nepisode_001/\n\noutline.json\nscenes.json\ndraft.md\nfinal.md\nsummary.json\nmemory_delta.json\nreference_usage.json\nsimilarity_report.json\n\`\`\`\n\n---\n\n# 41. 장편 기억 구조\n\n\`\`\`text\nPostgreSQL\n↓\n정확한 설정 데이터\n\nVector DB\n↓\n과거 장면 의미검색\n\nEpisode Summary\n↓\n과거 줄거리\n\nRaw Manuscript\n↓\n원문 확인\n\nReference DB\n↓\n참고 작품 분석 정보\n\`\`\`\n\n---\n\n# 42. 자동 집필 Scheduler\n\n\`\`\`text\n매일 03:00\n\nEpisode Planner\n↓\nReference Pattern Retrieval\n↓\nContext Retrieval\n↓\nScene Planning\n↓\nDraft\n↓\nContinuity Check\n↓\nLogic Check\n↓\nSimilarity Check\n↓\nStyle Check\n↓\nRewrite\n↓\nFinal\n↓\nMemory Update\n↓\nPublishing Queue\n\`\`\`\n\n---\n\n# 43. 표지 자동 생성\n\n입력:\n\n\`\`\`text\n장르\n주인공\n세계관\n분위기\n제목\n\`\`\`\n\n출력:\n\n\`\`\`text\ncover.jpg\nthumbnail.jpg\n\`\`\`\n\n참고소설의 표지를 복제하지 않는다.\n\n---\n\n# 44. EPUB 자동 제작\n\n완결 또는 지정 분량마다:\n\n\`\`\`text\nbook.epub\ncover.jpg\nmetadata.xml\n\`\`\`\n\n을 생성한다.\n\n---\n\n# 45. 출판 방식\n\n## 웹소설\n\n플랫폼별 Publisher Adapter를 만든다.\n\n공식 API가 있는 경우:\n\n\`\`\`text\n자동 업로드\n\`\`\`\n\n공식 API가 없는 경우:\n\n\`\`\`text\nepisode_title.txt\nepisode_body.txt\nauthor_note.txt\nthumbnail.jpg\n\`\`\`\n\n까지 자동 생성한다.\n\n---\n\n# 46. 전자책\n\n다음 자료를 자동 생성한다.\n\n\`\`\`text\nEPUB\nCover\nMetadata\n가격정보\n작품설명\n키워드\n카테고리\n\`\`\`\n\n---\n\n# 47. 완결 검사\n\n마지막 화 이후 전체 작품을 검사한다.\n\n\`\`\`text\n미회수 복선\n사라진 등장인물\n미해결 갈등\nTimeline 오류\n설정 충돌\n결말 불일치\n\`\`\`\n\n모든 문제가 해결되어야 완결 처리한다.\n\n---\n\n# 48. 관리자 화면\n\n\`\`\`text\n[작품]\n\n[Novel Bible]\n\n[Characters]\n\n[World]\n\n[Timeline]\n\n[Relationships]\n\n[Foreshadowing]\n\n[Reference Novels]\n\n[Reference Patterns]\n\n[Episodes]\n\n[Similarity Reports]\n\n[Publication]\n\`\`\`\n\n---\n\n# 49. 참고소설 관리 화면\n\n\`\`\`text\n[참고소설 추가]\n\n파일 업로드\n\n소설 A\n소설 B\n소설 C\n\n[분석 시작]\n\`\`\`\n\n분석 완료 후:\n\n\`\`\`text\n전개 속도\n문장 통계\n대사 비율\n복선 패턴\n클리프행어 패턴\n캐릭터 구조\n사건 간격\n감정곡선\n\`\`\`\n\n을 확인할 수 있다.\n\n---\n\n# 50. 참고 설정 화면\n\n예:\n\n\`\`\`text\n소설 A\n\n전개 속도        80%\n회차 구조        60%\n클리프행어       70%\n복선 방식        30%\n캐릭터 구조      20%\n문체             0%\n\`\`\`\n\n사용자는 참고하고 싶은 부분만 지정한다.\n\n---\n\n# 51. 백엔드 구조\n\n\`\`\`text\nnovel-factory/\n\napp/\n    orchestrator/\n    planner/\n    writer/\n    editor/\n    continuity/\n    memory/\n    publishing/\n\nreference/\n    importer/\n    parser/\n    analyzer/\n    structure/\n    character/\n    pacing/\n    style/\n    pattern/\n    similarity/\n\ndatabase/\n    characters/\n    worlds/\n    timeline/\n    relationships/\n    foreshadowing/\n    references/\n    episodes/\n\ngeneration/\n    premise/\n    outline/\n    episode/\n    scene/\n\nquality/\n    continuity_checker/\n    logic_checker/\n    style_checker/\n    repetition_checker/\n    similarity_checker/\n    reader_simulator/\n\npublishing/\n    epub/\n    metadata/\n    webnovel_adapters/\n\nassets/\n    covers/\n\`\`\`\n\n---\n\n# 52. 기술 스택\n\nBackend:\n\n\`\`\`text\nPython\nFastAPI\n\`\`\`\n\nDatabase:\n\n\`\`\`text\nPostgreSQL\n\`\`\`\n\nVector Search:\n\n\`\`\`text\npgvector\n\`\`\`\n\nQueue:\n\n\`\`\`text\nRedis\nCelery\n\`\`\`\n\nDocument Parser:\n\n\`\`\`text\nEPUB Parser\nPDF Parser\nDOCX Parser\nTXT Parser\n\`\`\`\n\n문서:\n\n\`\`\`text\nMarkdown\nJSON\nEPUB3\n\`\`\`\n\n---\n\n# 53. API\n\n참고소설 등록:\n\n\`\`\`text\nPOST /references\n\`\`\`\n\n참고소설 분석:\n\n\`\`\`text\nPOST /references/{reference_id}/analyze\n\`\`\`\n\n작품과 참고소설 연결:\n\n\`\`\`text\nPOST /novels/{novel_id}/references\n\`\`\`\n\n예:\n\n\`\`\`json\n{\n  "reference_id": "REF001",\n  "weights": {\n    "pacing": 0.8,\n    "cliffhanger": 0.7,\n    "character_structure": 0.3,\n    "style": 0\n  }\n}\n\`\`\`\n\n---\n\n# 54. 작품 생성 API\n\n\`\`\`text\nPOST /novels\n\`\`\`\n\n예:\n\n\`\`\`json\n{\n  "genre": "현대판타지",\n  "episodes": 250,\n  "characters_per_episode": 5000,\n  "reference_ids": [\n    "REF001",\n    "REF002"\n  ],\n  "publishing_mode": "automatic"\n}\n\`\`\`\n\n---\n\n# 55. 개발 우선순위\n\n## Phase 1\n\n\*\*Reference Analyzer 개발\*\*\n\n\`\`\`text\nTXT\nEPUB\nPDF\n↓\n회차 분리\n↓\n구조 분석\n↓\nReference Profile\n\`\`\`\n\n---\n\n## Phase 2\n\n\*\*장편 Memory 시스템\*\*\n\n\`\`\`text\nNovel Bible\nCharacter DB\nTimeline\nRelationship DB\nForeshadowing DB\n\`\`\`\n\n---\n\n## Phase 3\n\n\*\*Writer + Reference Pattern 연동\*\*\n\n참고소설의 패턴을 새 작품 계획에 사용한다.\n\n---\n\n## Phase 4\n\n\*\*Similarity Checker\*\*\n\n참고 작품과 지나치게 비슷해지는 것을 방지한다.\n\n---\n\n## Phase 5\n\n\*\*30화 연속 생성\*\*\n\n설정 오류와 Reference Pattern 적용을 평가한다.\n\n---\n\n## Phase 6\n\n\*\*100화 이상 장기 테스트\*\*\n\n장기 기억과 복선 회수 성능을 검증한다.\n\n---\n\n## Phase 7\n\n\*\*EPUB / 출판 자동화\*\*\n\n최종 파일 생성 및 출판 Adapter 구축.\n\n---\n\n# 56. 시스템 핵심 규칙\n\n첫째, 참고소설 원문을 그대로 새 작품에 복사하지 않는다.\n\n둘째, 참고소설은 \*\*구조 분석 데이터\*\*로 사용한다.\n\n셋째, 특정 작품의 고유명사·세계관·캐릭터를 자동으로 가져오지 않는다.\n\n넷째, 참고작품보다 새 작품의 Novel Bible이 항상 우선한다.\n\n다섯째, Reference Similarity Checker를 항상 실행한다.\n\n여섯째, 여러 참고작품의 공통적인 성공 패턴을 추출할 수 있어야 한다.\n\n일곱째, 장르별 Reference Library를 축적할 수 있어야 한다.\n\n---\n\n# 57. 최종 목표\n\n사용자는 다음처럼 요청할 수 있다.\n\n\`\`\`text\n현대판타지 소설을 만들어줘.\n\n참고소설:\nA\nB\nC\n\nA에서는 빠른 전개만 참고.\nB에서는 복선 구조 참고.\nC에서는 캐릭터 관계 변화 참고.\n\n250화.\n회차당 약 5,000자.\n\`\`\`\n\n시스템은 자동으로:\n\n\`\`\`text\n참고소설 분석\n↓\n공통 패턴 추출\n↓\n새로운 세계관 생성\n↓\n새로운 캐릭터 생성\n↓\n새로운 전체 스토리 생성\n↓\n250화 집필\n↓\n설정 검수\n↓\n복선 관리\n↓\n유사성 검사\n↓\n수정\n↓\n완결\n↓\nEPUB\n↓\n표지\n↓\n출판\n\`\`\`\n\n을 수행한다.\n\n최종 사용자 경험은 다음을 목표로 한다.\n\n\*\*“내가 좋아하는 여러 소설을 넣으면, 그 작품들을 복사하는 것이 아니라 왜 재미있는지 구조적으로 분석하고 그 장점을 이용해 완전히 새로운 장편소설을 자동으로 만들어주는 시스템.”\*\*

만들어