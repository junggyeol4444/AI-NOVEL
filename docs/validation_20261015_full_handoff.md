# AI NOVEL FACTORY — 2026-10-15 사용자 요구/100단계/검증 인수인계

**제품 인수 판정: RELEASE_BLOCKED.** 이 파일은 새 대화가 맨 먼저 읽어야 할 기준 문서다. **절대 main을 수정하거나 병합하지 말 것.** 오직 검증 브랜치 validation/gui-authoring-e2e-20261014에서 개발한다.

## 원본을 보존한 인수인계 첨부
사용자에게 제공한 통합본 파일명: AI_NOVEL_전체개발_인수인계_20261015.md. 원래 제공된 붙여넣은 마크다운(2).md 43KB 전체 원문을 변경 없이 하단에 포함하여 총 67KB이다. 원본 기획안의 본문은 57개 섹션으로 구성되며 프로그램의 01~100단계 상세 docs/stageNN_*.md 및 이 저장소 구현을 함께 확인해야 한다. 원본을 이 요약으로 대체하지 않는다.

## 사용자의 필수 요구
1. 최초 입력(장르/소재/목표 화수·회차당 글자 수/주요 설정/분위기/참고소설)만으로 참고작 구조 분석, Reference Profile, 다중 가중치 Pattern, Novel Bible, World/Characters/Character Knowledge/Relationships/Timeline/Foreshadow/Style, 전체 Story Arc/회차/장면 플롯, 로컬 AI 실집필, Continuity/Logic/Timeline/Foreshadow/Repetition/Style/Reference Similarity/Reader 검사, 위험 장면 재작성+재검사, Memory Delta 업데이트, 장기간 다음 화, 완결 검사, EPUB/표지, 사용자 승인된 출판까지 **진짜 통합**해야 한다. 250화×약 5천자, 실제 모델 30/100화 이상 장기 검증 요구. 계획 슬롯 수와 몇 화 샘플 생성은 품질·완성 증거가 아니다.
2. 메인 브랜치 main 절대 불변. 기존 사용자의 문서/원고/SQLite DB/설정/비밀키/기존 연결/비활성화한 자동화·스케줄을 임의로 삭제·변경·재활성화하지 말 것. 실제 계정·원고 외부 전송/출판은 사용자 별도 명시 승인 없이는 절대 금지.
3. 참고작 문장·고유명사·캐릭터·세계관 복사 금지. 참고작은 장르·전개·복선·인물 관계 등의 구조·통계적 패턴만 사용하며 Novel Bible 우선. 전체 등록 참고작에 대한 실제 유사성 검사 필수; 수행하지 못했으면 NOT_RUN으로 표시하고 품질 합격/자동 출판 금지.
4. 사용자는 “실사용자가 코드로 실행하니? 프로그램 켜고 누르고 기다리고 누르는 방식으로 확인하라”고 명시. **실제 Windows 10/11 PC에서 EXE 열고 화면 마우스/키보드로 입력→버튼 클릭→대기→저장→종료→재실행→복원/EPUB까지 검수**해야 한다. 프로그램 내부 Qt offscreen QTest나 개별 단위 테스트만 PASS인 것은 실사용자 인수 검증이 아니다.
5. 화면 캡처를 보고 사용자는 “저 화면이 맞다고 생각해? 누가 봐도 이상한데, 한두개가 아니고”라고 반발. 조수도 **현재 GUI 전체가 제품 UX 불합격**을 인정했다. 초등 DB 폼 같은 12개 독립 메뉴/복잡한 경로/좁은 편집기/빈 여백/영한 혼용/작품 현재 상태 부재/앱 시작 시 DB 입력부터 요구/원고보다 설정폼 중심/출판 화면에 비밀번호부터 요구 등 **화면 전체를 사용자 작업 중심으로 재설계**해야 한다. 폰트나 색깔만 고치지 말 것.
6. "겉핥기·누락된 걸 다 구현해서 연결하라", "별도 검증도 니가 하라", "윈도우 11 없어? 테스트 안 할 뿐이지"라는 반복 지시를 존중하며 실제 수정/실행/캡처/결함 재수정으로 진행. 성공 범위를 과장하지 말 것.
7. 지난 대화가 매우 길어 사용자에게 "메시지 전송 시간이 초과되었습니다. 다시 시도하세요." 표시. 이후 짧은 진행/결과 답변으로 요약하고 매번 로그 전체 출력·불필요 폴링으로 대화를 늘리지 말 것.
8. 2026-10-15 사용자가 5분 뒤 단 1회 개발 인수인계를 예약하도록 요청함. "AI NOVEL 개발 인수인계" 예약이 생성되어 Asia/Seoul 약 13:29에 발송되도록 설정. 기존 다른 자동화는 조작하지 않음. 예약 알림만으로 파일/과거 대화가 새 대화에 자동 이전됐다고 보장하지 말고 통합본과 본 문서를 출처로 사용할 것.

## 원문 기획안 개발 구간 01~100
- 01–10 개발 기반, Windows GUI·EXE·FastAPI/로컬 서비스. PySide6 및 실행 파일은 있으나 정식 사용자 설치/UI 인수 **미검증**.
- 11–20 참고 파일 등록 TXT/EPUB/DOCX/PDF/Markdown, 파싱/회차 분리/카탈로그/기초통계. 모듈 있음, 분석→실제 Writer 연결 미완성.
- 21–30 참고 구조/대사·서술·사건/속도·클리프행어/캐릭터·관계·복선·감정·문체·Reference Profile. 부분 모듈과 문서 존재, 종단 검증 부족.
- 31–40 다중 참고/장르 Pattern Library/작품별·기능별 가중치·선택/유사성 방지. 저장 패턴 GUI 조회/수동 국소 검사, 전체 Writer·유사성 게이트 **미완성**.
- 41–50 Novel Bible·Characters·Knowledge·World·Relationships·Timeline·Foreshadow·Style Bible·Episode·Migration. SQLite CRUD, 6개 메뉴 연결; 전체 자동 기억 적용 및 UX 미완.
- 51–60 Premise/Story Arcs/Episode-Scene planning/context/pgvector retrieval/pattern application/plot editor. 250화 슬롯·간단 AI 줄거리 Preview는 존재, 최초 입력만으로 250화 품질 좋은 전체 기획 **아님**.
- 61–70 로컬 모델/Writer/assembly/orchestrator/Celery 로컬 큐/monitor/retry/단일 회차. CPU GGUF와 Windows EXE 실제 생성 PASS. 135M 품질 및 장편 자동화 미완.
- 71–80 Continuity/Knowledge/Timeline/Foreshadow/Logic/Style/Repetition/Reference Similarity/Reader/Rewrite. 단위 모듈 존재하지만 배치 Runner는 length/repetition 중심, 핵심 6종 NOT_RUN; 전 검사·재작성 자동화 미완.
- 81–90 Memory Delta/Application/versions/continuation/scheduler/30화/long-memory/ending/approval/operations. 일부 중단/재개·DB/큐 실서비스 연결 PASS; **실제 30화/100화 AI 품질·장기 기억 시험 없음**.
- 91–100 Cover/Metadata/EPUB3/Upload Drafts/Publisher/Platform Audit/Windows exe/install/regression/release. 로컬 TXT/EPUB, 검수 최종본, unsigned QA EXE, WordPress 비공개 초안 계약 테스트. **실계정 출판·물리 Win10/11 x64 설치/조작·정식 인수 미검증**.

스테이지 상세파일 예: docs/stage08_desktop_ui.md, docs/stage09_local_api.md, docs/stage10_smoke_tests.md, docs/stage11_reference_file_picker.md, docs/stage13_txt_markdown_parser.md, docs/stage15_docx_parser.md 등 docs/stageNN_*.md. 01~07/12/14는 동일 명칭의 단계 문서가 발견되지 않았으므로 원문/전체 소스에서 확인 필요. 명칭 지어내지 말 것. 원본 사용자 계획 57섹션과 개발 단계 01~100은 둘 다 확인할 것.

## 실제 소스 / 현재 브랜치
- 저장소 https://github.com/junggyeol4444/AI-NOVEL
- 검증 브랜치 https://github.com/junggyeol4444/AI-NOVEL/tree/validation/gui-authoring-e2e-20261014
- 기초 결함 감사 docs/validation_20261015_roadmap_gap_audit.md
- desktop/app.py, desktop/authoring_controls.py, authoring_workflow.py, authoring_session.py, canon_workspace.py, additional_workspaces.py, auto_batch_panel.py, desktop/ci_user_journey.py, ci_portable_gui.py, ci_win11_ui.py.
- auto_novel_run.py는 미승인 AI story-preview/회차·장면/SQLite 저장·중단/회차 건너뛰기; 완전 품질/기억 게이트가 아님.
- packaging/windows/local_model_bridge.py + scripts/build_portable_ai_bundle.py: llama.cpp CPU, 공개 SmolLM2 135M GGUF 가중치 포함, 오프라인 실제 추론, 선택한 로컬 GGUF도 사용; 장편 한국어 품질 인증 아님.
- service_integration_ci.py 및 .github/workflows/anf-live-services-ci.yml: disposable PostgreSQL, pgvector, Redis/Celery 실제 브로커/워커/작품 격리 검색 성공; 일반 사용자 PC 자동 설치/운영·동기화는 별개.
- wordpress_draft_api.py: 공식 WordPress REST의 Private DRAFT만 opt-in, 4개 no-network 계약 테스트 PASS. 실출판/실계정 없음.
- Windows external QA scripts/ci_windows11_external_authoring.ps1(진짜 외부 UI Automation으로 EXE 입력·사용·종료·재시작), ci_windows11_desktop.ps1(12메뉴 UIA·Win32 PrintWindow 직접 캡처/foreground 검증). 정식 Windows x64 물리 PC 인수는 아직 없음.
- Noto Sans KR 번들 Korean glyph 수정 완료; **한글 글꼴 개선 = 전면 GUI 제품 UX 개선 아님**.

## 2026-10-15 정확한 최근 Actions 근거
- https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175901 : Windows compiled EXE/실제 GGUF 로컬 생성/최종본 확인/TXT+EPUB/독립 EXE 재실행 **SUCCESS**. Qt 내부 GUI QTest + 사전 프로그램 입력 일부이므로 인간 최종 승인 아님.
- https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175892 : disposable PostgreSQL/pgvector/Redis/Celery live services **SUCCESS**.
- https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38680175938 : 실제 Windows 11 ARM64 runner의 x64 EXE **전체 FAIL**. 그러나 **외부 OS UIAutomation**으로 장르/제목/작가/소재/분량·분위기·설정 9개 실제 입력→새 작품 생성 클릭→SQLite 파일 확인→Novel Bible 입력/설정 저장→Windows 외부 WM_CLOSE→프로그램 다시 켜기→기존 작품 열기 버튼→제목·장르·Bible 복원까지 **개별 단계 전부 PASS**. 12개 메뉴 외부 UIA 선택과 Publication 페이지 버튼 3개 조회, Win32 앱 창 캡처도 PASS. 마지막 **Windows 11 초기 개인정보 설정 화면(OOBE)이 앱을 가려 foreground QtForeground=False**, 실제 OS 데스크톱 전면 검수는 FAIL. 물리 Windows 10/11 x64 개인 PC는 미검증.
- 이전 앱/모델 성공 https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38669951971 ; Windows11 ARM 번들 모델 https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38671177873 ; WordPress 계약 https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38669105086 .
- 기존 브랜치 확인한 HEAD 5028a75e3c0a7c1819a941af689c034915ca0c7b. 이 문서를 추가하면 HEAD는 달라짐. 모든 변경 **main에 금지**.
- 실제 캡처: AI_Novel_Windows11_12_screens.png, AI_Novel_Windows11_actual_screenshots.zip, ai_novel_actual_windows_screens/native_app_window.png, ui_01_novels.png, ui_10_episodes.png, ui_12_publication.png (이전 대화 첨부/Actions artifacts). 사용자가 직접 보고 제품 UX가 잘못됐다고 지적.

## 사용자가 본 실제 화면의 10대 결함
1. 한글·영어 사이드바 혼용.
2. 첫 화면에 SQLite DB 경로부터 요구.
3. 사용자가 열어 둔 현재 작품/진행/저장 상태가 전역에 없음.
4. 작업마다 작품 DB를 다시 여는 불연속 구조.
5. 장면/원고 편집칸이 매우 좁고 중앙 넓은 원고 편집기 없음.
6. 공백이 지나치게 크거나 작은 폼에 모든 버튼을 채운 화면.
7. API 미연결 등 개발용 상태문구의 UX 오염.
8. Novel Bible/관계/세계관/시간선/복선이 Writer와 연결되는 기능처럼 보이지 않고 DB CRUD처럼 보임.
9. Publication이 검수된 원고 미리보기보다 경로/가격/비밀번호 중심.
10. 전체 원고 기획→AI 집필→검수·재작성→기억 업데이트→출판이 한 작품의 일상 흐름으로 이어지지 않음.

## 다음 대화 우선순위 (반드시 실제 코드를 수정하고 Windows에서 검증)
1. 검증 브랜치의 최신 Actions를 확인하고 이 문서/원문·screenshots·기존 소스/단계 docs를 읽는다. 이미 답한 요구를 다시 묻지 않음.
2. **사용자 중심 PySide6 GUI 전면 재설계**: 작품 홈(최근 작품/선택 상태/안전 기본 저장), 새 작품 마법사(참고 파일 분석·가중치 선택), Story Arc/회차 기획실, **중앙 넓은 원고 편집기+왼쪽 회차/장면+오른쪽 인물·복선·세계관 참조**, 증거 기반 품질 검수 및 원고 수정, 최종 EPUB/표지/승인 후 출판. 전체 사용자 작업 흐름에서 실제 SQLite/로컬 AI/파일 분석 모듈 연결. 플레이스홀더·그림 목업만 만들지 말 것.
3. 실제 EXE를 켜고 **앱 외부 Windows 접근성/마우스/키보드**로 제목 입력·참고 파일 선택·AI 계획/집필 대기·검사/재작성·원고 저장·최종본/EPUB·종료·재실행·동일 작품 복원까지 테스트. 각 단계 실제 화면 캡처를 눈으로 검수해 심각한 레이아웃 문제를 고친다. ARM Windows 11 x64 앱 에뮬레이션과 물리 Windows 10/11 x64를 구분하고 외부 데스크톱 OOBE는 계속 blocker.
4. 작품 선택한 세션/경로/원고/메모리를 모든 메뉴/수정 화면에서 공유. 오래된 DB/유저 파일 삭제 금지.
5. 실제 등록 참고소설 패턴을 AI Story Planner/Writer에 전달하고, Continuity/Knowledge/Timeline/Foreshadow/Logic/Style/Repetition/Similarity/Reader 전체 품질 게이트→위험 장면 재작성/재검사→Memory Delta 자동 적용 기능 구현.
6. 실제 모델 30화/100화 연속·강제종료/재개/기억/복선회수/품질·비용 검사. Mock·슬롯 수만으로 완료 금지.
7. 사용자 PC용 패키징/서명/설치/서비스 선택적 연동·공식 플랫폼 출판 정책/실승인 UX 검증. 모두 완료 전 정식 출시 금지.
8. 메시지는 짧고 실결과/실패/화면·근거 링크 위주, 채팅 전송 시간초과 예방.

**새 대화용 자동 시작 지시**: '이 인수인계 파일과 원문 기획안 전문을 모두 읽고, validation/gui-authoring-e2e-20261014 브랜치에서 main은 절대로 손대지 말고, 제품 UX가 불합격이었던 실제 Windows 프로그램 화면을 사용자 중심으로 전면 재설계·구현·검증해라. 기존 DB·키·원고·비활성 자동화 보존, 01–100 원본 단계 모두 실동작으로 연결, 등록 참고작 복제 방지, 장기 AI 모델 집필/검사/Memory·EPUB/출판 목표. 실제 프로그램 바깥에서 화면을 조작·캡처하고 저장·종료·재실행해라. 이미 확인된 PASS/FAIL은 위 Actions 링크와 구분하고 거짓 완성 선언 금지. 짧게 결과 보고.'

## 2026-10-15 새 대화 개발 재개: GUI 첫 구간 구현 및 추가 QA

**제품 판정 계속 RELEASE_BLOCKED.** 아래는 신규 구현 사실이며 통합 제품/물리 Windows 사용자 검수 PASS를 뜻하지 않는다.

- 원본 57섹션/01~100개발 단계와 통합 인수인계 파일 대조. 검증 브랜치에서만 파일 수정. 확인 당시 main SHA `69225edeed0a09ded5f847dad9b9ea63bc45367c`; main 수정/병합/강제푸시 수행하지 않음.
- `src/ai_novel_factory/desktop/project_studio.py` 추가: 첫 화면 작품 홈(최근 열어본 작품), 장르/소재/주요 설정/회차수/분량 입력으로 기본 로컬 작품 새로 만들기, 현재 작품과 회차 표시, 넓은 편집기·읽기 전용 Canon/플롯·회차별 NOT_RUN 검수 상태, 버전 저장(기존 원고 첫 수정 시 `ManuscriptVersionStore.capture_current` 보존), 고급 기능 연결. 기존 사용자 작품을 자동 열거나 외부 호출하지 않음.
- `desktop/app.py`는 새 GUI를 기본 표시하고 기존 `AuthoringWorkflowWidget`를 상세 작업 탭에 유지. 기존 Canon/Publication 연동 및 플롯 에디터의 현재 작품 DB 연결 시도. 창 크기를 화면 가용 영역에 맞춤. `desktop/navigation.py` 12개 기존 기능 키는 보존하면서 한국어 작업 이름으로 통일. GUI 전면 완성 아님; 플롯/참고/검수/출판 독립 메뉴 통합은 남아 있음.
- 테스트: `desktop/ci_win11_ui.py`에 합성 데이터로 신규 홈/로컬 작품 생성, 사용자 원고 버전 저장, 화면 스냅샷 검증 추가. `scripts/ci_windows11_external_authoring.ps1`에 외부 Windows UIAutomation으로 신규 작품 마법사 클릭/필드 입력/작품 제목 확인 추가. `scripts/ci_windows11_desktop.ps1`은 12개 메뉴 선택 후 홈 화면으로 돌아와 실제 HWND를 캡처하도록 수정. 기존 GUI 계약 테스트 문구 변경. 신규 테스트의 PASS 여부는 해당 Actions 완료 전까지 미확정.
- 직전 확정된 `38681732387` Windows EXE 집필 연계 SUCCESS, `38681732308` 실 PG/벡터/Redis/Celery SUCCESS, `38681732410` Windows 11 실제 데스크톱 QA FAILURE. 실패 원인은 Windows OS 개인정보 OOBE 설정 화면이 앱 전면을 가린 상태(`QtForeground=False`). GitHub 아티팩트 `windows11-actual-desktop-probe` 원본 화면 직접 열어 확인; 캡처된 Qt HWND와 실제 데스크톱 전경은 서로 다르다.
- GUI 개편 후 검증 워크플로는 `validation/gui-authoring-e2e-20261014` 새 커밋들에서 자동 실행 중이며 **완료하지 않은 실행은 성공으로 작성하면 안 된다**. 최신 Actions `https://github.com/junggyeol4444/AI-NOVEL/actions?query=branch%3Avalidation%2Fgui-authoring-e2e-20261014`에서 최종 상태를 확인하라.
- 사용자 데이터/기존 키/연동 설정/비활성 자동화는 수정하지 않았고 실계정 업로드·게시·외부 참고소설 전송 없음. 물리 Windows 10/11 x64 PC/실사용자 마우스·키보드 전체 길찾기/화면 가독성 인수, Reference→Writer 자동 연결/전수 유사성·자동 재작성/30·100·250화 장기 실제 품질은 여전히 미달.


### 2026-10-15 개발 재개 추가 진행 (최신, GUI 저장/복원)

아래 항목은 **코드 반영 완료 / 최신 QA 판정 아직 미확정**이다.
- `project_studio.py`: 첫 회차 바로 시작 버튼(`studioFirstEpisodeButton`), 사용자 작성 원고 편집 및 명시적 버전 저장 버튼, `Ctrl+S` 단축키 추가. 기존 초고의 첫 버전 보존/수정본 추가, 최근 작품 목록에서 랜덤 DB 파일명 대신 저장된 작품명 표시. 기존 로컬 SQLite/설정은 삭제하거나 덮어쓰지 않는다.
- `app.py`: 기존 상세 작업 탭으로 이동할 때 저장하지 않은 원고 확인. 탭 클릭으로 인한 사용자 원고 변경 유실을 막는다.
- `scripts/ci_windows11_external_authoring.ps1`: 기존 Qt 내부 테스트와 독립적으로 Windows UIAutomation에서 기본 새 작품 GUI의 실제 입력/생성, 첫 회차 클릭, 원고 입력/버전 저장 클릭, 기존 DB 열기/종료/재실행을 순서대로 시험하도록 확대했다. 해당 신규 단계 PASS 여부는 최신 Windows 11 Actions 확인 전에는 미확정.
- `desktop/ci_win11_ui.py`: 실제 Qt 버튼 클릭으로 첫 회차/버전 저장 확인; 오프스크린 실험일 뿐 물리 Windows 사용자의 합격이 아니다.
- `tests/test_studio_gui_optional.py`: 합성 데이터로 GUI 작품 생성, 첫 회차, 두 번 저장 후 원본 버전 보존, 앱 재기동 시 최근 작품 제목/원고 복원, 미수행 검수 항목 NOT_RUN 보존 검증 추가.
- `.github/workflows/anf-studio-fast-ci.yml`: 무거운 AI 모델 Windows EXE 빌드와 별개로 Windows x64 runner에서 빠른 PySide6 클릭+로컬 SQLite 테스트를 실행. **실행 결과 확인 전 PASS 선언 금지**.
- 최신 코드 검증 시작점: 커밋 `3f8d96ee6b5a1e84e5361a0312f717260859ccc3`; `https://github.com/junggyeol4444/AI-NOVEL/actions?query=branch%3Avalidation%2Fgui-authoring-e2e-20261014`.
- 확인한 `main` head: `69225edeed0a09ded5f847dad9b9ea63bc45367c` (수정/병합 없음). 사용자 실계정/원고/키·기존 연결·비활성 자동화에 손대지 않음.
- 미해결: 새 GUI 정식 Windows 10/11 사용자 검수, 12개 독립 메뉴 전체를 통합한 UI 전면 개편, 등록 참고작→자동 기획/Writer→전수 검사/기억·재작성→30/100/250화 장편 실품질·출판까지 종단 연결. 기존 Windows 11 OOBE 화면 전경 가림 문제도 FAIL로 보존.



### 2026-10-15 새 대화 추가 진행: 원고 유실 방지·작업 중심 내비게이션·QA 대기

제품은 여전히 **RELEASE_BLOCKED**이며, 다음은 신규 코드 반영 사실이다. 실행 테스트 PASS나 물리 Windows 사용자 인수를 의미하지 않는다.

- `project_studio.py`: 편집기에서 회차·작품·탭을 전환할 때 **저장되지 않은 입력이 있을 경우** 변경 폐기 확인. 거절하면 내용과 위치 유지, 승인하면 마지막 저장본으로 에디터 복구. 단축키 `Ctrl+S` 명시적 `QKeySequence` 구성. 코드와 테스트 수정 완료, 실제 Win11 Qt 테스트 결과는 미확정.
- `app.py`: 시작 작품 화면의 중복 기술적 안내문을 줄이고, 기본 좌측 메뉴를 **작품 홈 / 원고 집필 / 참고작 분석 / 검수 현황 / 내보내기** 다섯 사용자 작업으로 변경. 12개 기존 기능은 삭제하지 않고 사용자가 클릭하여 펼치는 `세부 도구` 아래 유지. 첫 사용자가 `원고 집필`을 누르고 작품이 없으면 빈 원고 에디터 대신 작품 생성 화면으로 안내.
- `ci_user_journey.py`, `ci_win11_ui.py`, `ci_windows11_desktop.ps1`: 새 구조에서 전문 도구를 명시적으로 펼쳐 테스트하고 작은 창에서는 스크롤 후 각 메뉴를 클릭하도록 수정. Windows 실제 HWND 화면 캡처 전 좌측 전문 도구를 접어 기본 UX를 검수하도록 수정. `ci_win11_ui.py`에 원래 첫 화면 `ui_00_primary_home.png` 신규 캡처 단계 추가. 실제 스크린샷 리뷰는 **새로운 Actions 실행 완료/아티팩트 확인 후** 진행해야 한다.
- `tests/test_studio_gui_optional.py`: 첫 GUI 생성→원고 두 번 저장/이전 버전 보존→창 종료→재실행·최근 작품 열기 검증과, 저장하지 않은 원고를 두고 이동/폐기를 시도하는 회귀 테스트를 포함. `test_desktop_gui_optional.py` 초기 사용자 집필 버튼 경로 확인.
- `.github/workflows/anf-studio-fast-ci.yml`: Windows Qt 오프스크린 단축 회귀 테스트. 2026-10-15 추가 푸시로 여러 대형 Windows Actions가 누적 대기 중이어서 **결과를 추정하지 말 것**. 검증 브랜치의 네 개 **활성 validation-only** 워크플로에 `concurrency cancel-in-progress` 적용하여 앞으로 이전 커밋의 중복 검증이 새 빌드를 압도하지 않게 변경. 기존 `hourly-ci.yml` 스케줄 또는 비활성 자동화는 수정·재활성화하지 않음.
- 마지막 구현 커밋 `a23f55e3b365bb7371f3f859c6b844e428aff579` (검증 브랜치만). 최신 결과는 `https://github.com/junggyeol4444/AI-NOVEL/actions?query=branch%3Avalidation%2Fgui-authoring-e2e-20261014`에서 반드시 재확인.
- 확인된 과거 Windows 11 ARM64 hosted VM에서 x64 EXE 에뮬레이션/UIAutomation 입력·저장·종료·재실행 성공과 전경 Windows 개인정보 초기 화면으로 인한 최종 네이티브 검증 실패는 그대로 유효하다. 새 GUI의 **실제** OS 화면 조작·직접 캡처·물리 Windows 10/11 x64 PC 인수는 여전히 미검증.
- 제품 전체 요구 기준으로 처음 입력→참고작 전수 구조 분석→Reference Profile/가중치 Pattern→Novel Bible/전체 기획→진짜 장편 AI 집필→모든 검수/자동 재작성/장기 기억→최종본/EPUB/사용자 승인 출판의 종단 자동화는 미완성. 단위·오프스크린 결과로 완성 주장 금지.


### 2026-10-15 계속 개발 지시 후 결과: 파일 보호/동시편집/실패한 Linux QA

- 사용자가 "여기서 계속하라는건 개발이든 검증이든 알아서 하라는거야"라고 명시했다. 향후 "계속해"는 추가 확인 질문 없이 우선순위를 판단해 개발·검증·실패 원인 수정까지 이어가라는 의미다. 기존 모든 데이터/키/설정/자동화, `main` 불변 원칙은 유지한다.
- `desktop/authoring_session.py`: 생성 전 빈 최상위 설정 명시 거부, 선택 필명 미입력은 공개 작가명을 지어내지 않고 `미정`으로 저장. 기존 DB 파일 덮어쓰기 금지: `os.O_EXCL|os.O_CREAT`로 배타 예약하고 초기화 실패 시 소유한 같은 inode의 신생 파일만 삭제. 기존 다른 파일과 경쟁 상황에서 생긴 데이터는 삭제 금지.
- `tests/test_authoring_session_safety.py`에 신규/기존 경로, 필명 미입력, 생성 실패 cleanup, 동시 경쟁 파일 보존/작품 재오픈 회귀 테스트. **Linux Actions run 38685861312에서 이 파일보호 테스트는 전부 PASS**.
- `desktop/project_studio.py`: 사용자 편집기에서 불러온 회차 revision을 별도로 추적해 외부 프로세스가 같은 회차를 바꾼 후 오래된 창이 저장을 누를 때 덮어쓰지 않도록 명시적으로 거부. 편집자 내용은 창에 남음. `test_studio_gui_optional.py`에서 외부 수정 뒤 원고 보존을 확인하는 시나리오 추가. 새 작품이 없으면 기본/보조 집필 버튼 모두 빈 편집기 대신 작품 생성 입력 화면으로 이동.
- `.github/workflows/anf-linux-studio-safety-ci.yml`: Windows 대기열과 별개로 Ubuntu PySide6 offscreen + SQLite 원고 저장/재실행 테스트 추가. **run 38685861312 FAILURE**: 기존 탐색 및 데이터 보존 테스트는 SUCCESS, GUI 테스트 시작 때 `ImportError: libEGL.so.1` (runner Qt 시스템 라이브러리 누락) 발생. 이는 GUI 품질 통과 근거가 아니다. Ubuntu 워크플로에 `libegl1`, `libopengl0`, `libxcb-cursor0`, `libxkbcommon-x11-0` 명시적 설치 단계 추가. 수정 후 실행은 다시 확인해야 하며 **그 전에는 PASS 주장 금지**.
- `scripts/ci_studio_snapshots.py`: 외부 네트워크/사용자 원고 없이 원본 창작 **합성 데이터**로 첫 시작/새 작품 입력/로컬 원고 집필/진척 홈 화면 PNG 캡처와 증거 JSON 생성. Ubuntu QA Artifact는 아직 생산 확인 전, 사람의 시각 인수나 Windows 물리 화면 검증이 아님.
- 최신 검증 브랜치 코드 commit `8db0e508d79f5f22b45d396a4204e25e73b2a71e`; GitHub `https://github.com/junggyeol4444/AI-NOVEL/actions?query=branch%3Avalidation%2Fgui-authoring-e2e-20261014`에서 **최신 결과·실패 단계·업로드 스크린샷을 먼저 확인**하라. 잦은 푸시로 이전 후보가 concurrency cancel-in-progress로 CANCELLED된 상태; CANCELLED는 PASS가 아니다.
- 물리 Windows 10/11 x64 GUI, OOBE 가려진 Windows11 hosted runner의 foreground 문제, 모든 01~100 통합·Reference→AI Writer→전수 QC/재작성→30·100·250화 장기 품질은 여전히 미완성. 제품 판정 `RELEASE_BLOCKED`.


### 2026-10-15 추가 구현 및 독립 Qt 검증 (Linux 기본 합격, Windows 여전히 미검증)

- 사용자의 "계속"은 검증·기능 구현을 자율 우선순위로 진행하라는 뜻. main 미접촉과 사용자 데이터 보호 원칙은 변화 없음.
- **GitHub Linux GUI Actions run 38686693268, commit 90f53e262389cc3ffd49352ed881890769e6adf3 = SUCCESS**. 이 실행에서 기존 탐색 회귀, Qt 첫 화면 클릭 스모크, 단독 SQLite 파일 예약/생성 경쟁 보호, GUI 버튼으로 작품 생성→첫 회차→원고 2회 버전 저장→종료→최근 작품 재실행 복원→미저장 변경 보존/폐기→외부 동시 수정 충돌 차단, 합성 4장 Qt 화면 캡처가 모두 PASS. 실제 Linux offscreen Qt/SQLite 동작 근거이며 **물리 Windows 10/11 GUI 인수 합격은 아니다**. Artifact `anf-linux-studio-qt-synthetic-screens`, run URL `https://github.com/junggyeol4444/AI-NOVEL/actions/runs/38686693268`. 직접 캡처 리뷰 시 한글 사각형(글꼴 누락)이 드러났으므로 제품 화면 합격으로 취급 금지.
- 이후 `src/ai_novel_factory/desktop/font_support.py`에서 번들 글꼴 부재 시 설치된 Noto Sans CJK KR/Noto Sans KR/맑은 고딕/나눔고딕 후보 자동 탐색. `anf-linux-studio-safety-ci.yml` Ubuntu `fonts-noto-cjk` 설치, `scripts/ci_studio_snapshots.py`에서 캡처 전 반드시 한국어 글리프 지원 검사. 새 스크린샷의 한글 정상 출력은 **새 run PASS 및 다운로드 PNG 시각 확인 전 미검증**.
- `desktop/project_studio.py`: 이전 버전 리스트/읽기 전용 미리보기 GUI 버튼 `studioVersionHistoryButton`, 사용자가 복원을 별도 확인한 뒤 `restore_as_revision(...)`으로 **기존 버전 불변, 새 수정본으로만 복원**. 외부에서 회차가 바뀌면 revision 불일치로 복원 거절. 최종본/게시 승인 절대 자동 생성하지 않음. `test_studio_gui_optional.py`에 앞선 2개 버전이 보존되며 복원이 3번째 REVISION으로 남는 회귀 시나리오 추가. 이 변경의 Linux Qt/Windows EXE 검증은 아직 대기 중.
- `desktop/project_studio.py`: 최근 작품 더블 클릭으로 오픈, 긴 신작 마법사 화면을 `QScrollArea`로 표시해 820×560 등 작은 창에서도 생성 액션 접근 지원. 목표 회차 수가 없는 예전 SQLite 작품은 `?`로 표시해 신규 GUI에서 기존 사용자 작품 열기를 막지 않음.
- `tests/test_studio_gui_optional.py`: 기존에 `restarted` 창을 인스턴스화하기 전 참조하던 잘못된 테스트 순서 제거. Windows GUI 오프스크린 테스트가 통과하더라도 사용자 육안 인수와 실제 OS foreground 인수는 별개.
- 최근 신규 기능은 `ac8ea5453aee0d37c7dfd9e31d445e33b93b99a7` 검증 브랜치에서 구현. Windows 실제 OS UIA 테스트, 오버레이에 가렸던 네이티브 화면, 진짜 30/100/250화 장편 품질/전수 참고작 유사성 검증 및 01~100 전체 완성은 계속 **RELEASE_BLOCKED**.


### 2026-10-15 현재 추가 GUI 개발: 읽기 전용 버전 탐색 + 반응형 집필실 (최신 상태)

- `project_studio.py`: 원고 저장 버튼 아래 `이전 원고·버전 이력` GUI를 연결, 버전 목록의 ordinal/kind/date와 읽기 전용 과거 초고 미리보기 제공. 사용자 승인 후에만 `restore_as_revision`으로 **새 버전**을 생성하는 복원; 기존 이력/SQLite 자료 삭제 없음. 사용자가 아직 저장하지 않은 원고가 있으면 이동·폐기를 묻고, 외부에서 episode revision이 변경된 경우 복원 거절. 최종본 승인/출판 자동 부여 없음.
- `tests/test_studio_gui_optional.py`: 이전 두 원고 버전이 유지되는 3번째 복원 REVISION 시나리오와 실제 Qt 버튼으로 역사 대화상자 열기/읽기 전용 목록·본문 미리보기 검증 추가. **최신 버전 run 통과 전 테스트 결과 PASS 주장 금지**.
- `project_studio.py`: 좁은 화면에서는 설정·검수 우측 패널을 자동으로 접어 주 원고 입력 공간을 확보하고, 설정·검수 펼치기 버튼으로 언제든 보게 함. 넓은 화면에서는 원고+설정 병렬 제공, 사용자가 직접 토글하면 크기 조절로 설정 변경을 덮지 않음. 양쪽 회차/설정 패널 최소·최대 폭 조정.
- `font_support.py`: Ubuntu CI에 Korean CJK OS 폰트가 설치될 때 bundled font가 없더라도 지원 후보를 찾아 적용. `scripts/ci_studio_snapshots.py`는 사각형 대신 실제 한국어 글리프를 렌더할 수 없으면 실패하도록 변경. 화면의 실제 이미지 확인 전 `KOREAN_FONT_OK` 선언 금지.
- 마지막 구현 SHA `c44179416ad7518ad88aa3ad5b0629c1490ad14b`, Actions 가장 최신 Linux run `38687509570`, Windows EXE `38687510278`, Windows 11 네이티브 `38687509641`. 조회 시 대기 중이었으며 앞으로 결과 재확인 필요. `main` 무변경.
- 이미 증명된 회귀 결과는 **이전 코드 `90f53e26`의 Linux offscreen Qt run `38686693268` SUCCESS 한 건**. 이 후 개선한 기능의 검증을 이전 run 결과로 거짓 추론하지 말 것. Windows 물리 사용자 인수, Windows OOBE 전경 가림 해소, 참고 전수 유사성·장편 30/100/250화 품질, 01~100 전면 기능 완성은 미검증. `RELEASE_BLOCKED` 유지.


### 2026-10-15 지속 개발: 종료 거부 시 원고 유실 위험 수정과 실증 결과

- 사용자가 명시적으로 `완성될 때까지 계속해`를 요청. 개발/검증을 되풀이 진행하되 어느 후속 실행에서도 임의로 `main` 병합, 사용자 원고·기존 DB·키·외부 게시를 변경하지 않음. 체계적인 물리 Windows 10/11 EXE GUI 인수가 남으면 출시 판정은 계속 `RELEASE_BLOCKED`.
- **발견 결함**: `MainWindow.closeEvent`가 사용자 집필실의 `confirm_discard()`를 실행해 미저장 원고를 먼저 폐기한 뒤, AI 배치 또는 외부 비공개 초안 전송이 진행 중이라 실제 창 닫기를 거절할 수 있었음. **수정**: 종료 불가 원인(활성 AI worker/WordPress draft worker)을 먼저 점검하고, 플롯 미저장 확인과 집필실 미저장 확인은 종료가 실제 가능한 단계에서만 수행. 실행 중 작업을 강제로 종료하거나 사용자 문서를 저장/삭제하지 않음.
- `project_studio.py` GUI 집필실에 `studioManuscriptStats` 실제 입력 내용 기준 **공백 제외 글자 수/어절/회차 목표 대비 비율/미저장 여부** 표시. 어절/글자 수는 입력 데이터에서 계산하며 품질/AI 모델 합격과 별개의 수치.
- `tests/test_studio_gui_optional.py`: 합성 초고 저장 후 미저장 입력을 추가, `auto_panel.is_running=True`인 상태에서 종료 시 `window.close() == False`, `request_stop()` 호출, 내용/미저장 상태 그대로 보존, 원고 폐기 확인 창이 뜨지 않는지 검사. 이어 정상 종료→프로그램 재실행→지난 원고 두 버전 열기→명시적 복원→동시 수정 덮어쓰기 거절까지 수행.
- GitHub Linux `38687509570` (old `c4417941`)에서 테스트 본문 `OK` 출력 뒤 Python 프로세스가 `Bus error (core dumped), exit 135`로 실패함. 실패를 감추지 않고 Qt 창을 `deleteLater()`/DeferredDelete로 명시적으로 정리하고 `-X faulthandler` 및 `PYTHONFAULTHANDLER` 적용, 실패하더라도 별도 합성 화면 캡처를 실행하도록 Linux Actions 변경.
- **GitHub Actions run `38688066922` at `e156fa9e` = SUCCESS**: Linux Qt 첫 실행/작품 생성·SQLite 경쟁 보호·두 번 원고 저장 및 버전 원형 보존·재실행·미저장 종료 차단·동시 편집 충돌·버전 복원, 합성 4개 GUI 화면 모두 통과. `03-novel-writer.png`와 `02-create-wizard.png` 직접 시각 검토: 한글 폰트 정상 출력 확인, 820x750 픽셀, 우측 설정 검수 패널은 버튼으로 접근 가능. 본 결과는 **Ubuntu Qt offscreen**임; 실제 Windows 사용자 인수 아님.
- **GitHub Actions run `38688203975` at `efbda1a5` = SUCCESS**: 명시적 Qt 창 정리·faulthandler 계측 추가 후 Linux 스모크/단위·GUI 회귀·합성 Qt 캡처 다시 모두 통과. 이번 버전의 Windows EXE/진짜 UIAutomation 및 물리 사용자 검증은 실행 미완료.
- 최신 구현 SHA `efbda1a515992688a830a947781b8a26f42454a5` validation-only. 최신 Windows 11 실사용 UIA run `38688203854`, Windows EXE run `38688203843`, 빠른 Windows GUI run `38688203856` 결과를 다음에 확인. `main`은 `69225edeed0a09ded5f847dad9b9ea63bc45367c`로 유지해야 함.


### 2026-10-15 14:50 KST: 명시적 사용자 의도 및 현재 개발
- 사용자가 예약/일정 설정을 강하게 거부하고, `계속`은 **이 대화에서 당장 개발/검증을 수행하라**는 뜻이라고 재강조했다. 앞서 잘못 추가된 `AI Novel Factory 완성 개발` 정기 작업을 **명시적으로 비활성화**했다. 이후 사용자 요청 없이 어떠한 스케줄도 만들지 말 것.
- `project_studio.py`: 수십~수백 회차 장기 원고 탐색을 위해 `studioEpisodeSearch`(번호·상태 텍스트 검색), `studioEpisodeMatches`(검색 결과/전체 수), `studioPreviousEpisode`, `studioNextEpisode` 추가. 검색은 회차 라벨만 읽고 원고 본문이나 다른 사용자 개인 데이터를 색인·서버 전송하지 않는다. 필터 결과가 없으면 회차 이동하지 않음. QListWidget의 필터 뒤 오래된 선택을 믿지 않고 `session.episode_number`에 근거한 직접 선택으로 미저장 원고 보호/페이지 재표시 경로를 사용.
- `test_studio_gui_optional.py`: 합성 두 번째 회차 생성 후 검색 필터·일치 회차 수·검색 결과 없음·이전/다음 이동·미저장 원고 이동 취소 시 DB 초고 유지 검증 추가.
- 코드 커밋 `f3b80af63ed1aee289610c168832911bf80d4739`, 필터 후 선택 안정성 수정 `780862724363671c638f3408b89568f603cf4031`. 최신 QA Linux run `38689275922`, Windows 11 네이티브 `38689275917` 및 Windows EXE `38689275823`은 조회 시 **queued/pending**. **이 코드 버전의 테스트 PASS 주장 금지.**
- 이전 `efbda1a515992688a830a947781b8a26f42454a5` 코드 기반 Linux GUI run `38688203975` SUCCESS, 서비스 run `38688203900` SUCCESS만 확인. Win11 실제 화면/OOBE 가림/장편 100·250화 고품질/01~100 요구사항 전체는 계속 `RELEASE_BLOCKED`. `main` 무변경 `69225edeed0a09ded5f847dad9b9ea63bc45367c`.


### 2026-10-15 한국시간 15시 무렵: 자율 즉시 개발 재개 / GUI 원고 보존 추가

- 사용자가 **"계속"** 이라고 말하면 즉시 코드/검증을 수행하라는 뜻이며, 자동화나 예약을 새로 만들라는 요청이 아니다. 이전 답변에서 임의로 만든 AI NOVEL Factory 정기 작업은 **비활성화**됐으며, 이 차례에는 어떤 예약도 새로 만들지 않았다.
- GitHub run `38689275922`, commit `780862724363671c638f3408b89568f603cf4031`의 **Linux Qt offscreen GUI, 원고 편집, 최근 작품 재실행 및 회차 검색/이동 회귀 검사 SUCCESS** 직접 확인. 이것은 물리 Windows EXE/사용자 인수 합격이 아니다. `main` SHA `69225edeed0a09ded5f847dad9b9ea63bc45367c` 무변경.
- `project_studio._restore_version()`: 이전에는 미저장 원고를 복원 처리 **전에** 지우므로, 승인 후 취소/버전 충돌/오류가 나면 미저장 텍스트를 상실할 위험이 있었다. 현재 사용자 승인 문구에 미저장 원고 폐기 조건을 고지하되 *실제 저장이 성공할 때만* 편집기를 새 복원본으로 교체한다. DB rollback 또는 거부 시 라이브 텍스트 보존. 회귀 테스트는 승인 거절/강제 롤백/정상 복원 3상태를 검사한다.
- `project_studio.confirm_discard(apply=False)`: 프로젝트 열기/생성, 첫 회차/새 회차 생성, 목록의 다른 회차 선택에서 **작업을 시도하기 전 편집기 텍스트를 지우지 않는다**. DB 작업 성공과 화면 교체가 확정되기 전에는 원고를 보존한다. 특히 `_create_episode`에서 입력 모달을 취소하면 원고 폐기 확인도 보여주지 않는다. `tests/test_studio_gui_optional.py`에서 실제 Qt 클릭으로 회차 변경 실패 및 새 회차 모달 취소 시 원고 보존 확인 시나리오 추가.
- `authoring_session.select_episode`: 회차와 소속 장면을 모두 조회 완료한 뒤에만 세션의 활성 회차를 바꾸도록 변경. 장면 조회 오류가 나면 기존 회차/원고가 유지되는 직접 로컬 테스트 `tests/test_authoring_session_safety.py` 추가.
- 최신 소스 검증 커밋 `4b4b5ccd1c4e3a10543d52490a47602f3790e762`. 이에 대한 Linux GUI run `38689911337`, Windows 11 화면 run `38689911375`, EXE 실제 사용 시나리오 run `38689911343`은 마지막 확인 시 `QUEUED`; 결과가 완성되기 전 PASS로 표시 금지. Linux/Windows 외부 runner 장기 대기열에는 구형 in_progress job 다수가 남아 있다.
- 01~100 전면 기능 및 실제 Windows 10/11 x64 foreground 조작, 30/100/250화 장편 품질과 참고작 유사성 전수 검증 등은 아직 미충족. **RELEASE_BLOCKED** 유지.


### 2026-10-15 후속 구현: 안전한 원고 복원·회차 이동·새 SQLite 열기 / CJK 스크린샷 육안 확인

- `4b4b5ccd1c4e3a10543d52490a47602f3790e762`: 과거 버전 복원 중 사용자 거부 또는 DB 오류 시 편집 중 원고를 지우지 않도록 변경. 작품 생성/열기, 회차 이동의 완료 이전 편집기 삭제 금지. 새 회차 생성 대화상자를 취소할 때는 원고 폐기 확인을 띄우거나 편집 내용을 버리지 않는다. 선택한 회차/장면을 불러오지 못하면 기존 세션의 회차/원고와 목록 선택을 보존한다. 각각 합성 Qt 회귀 테스트 추가.
- `ffeac8cd1f72d667b84d3559b856c99950110d60`: `AuthoringSession.open_project`는 신규 작품 SQLite의 회차/장면을 미리 검증한 뒤에만 구 세션을 닫음. 손상된 로컬 파일을 열어 실패할 때도 기존 사용자가 작업 중이던 작품 세션이 유지된다. 강제 `list_episodes` 오류 회귀 검사 추가. 모든 변경은 검증 브랜치 한정.
- **검증된 결과:** Linux Qt offscreen run `38689275922` SUCCESS(이전 commit `78086272`), 실서비스 PostgreSQL/Redis run `38689911350` SUCCESS(직전 commit `4b4b5ccd`). **최신 commit `ffeac8cd` 전체 Windows EXE/Qt 통합 검증은 PASS 근거 없음.** Linux quick run `38690349611`, Windows 11 run `38690349621`, Windows EXE run `38690349610`을 최신 결과 확인 대상으로 기록.
- 이전 성공 run `38688203975`의 합성 Linux Qt GUI 스크린샷 4장을 직접 내려받아 열어 보니 **한국어 글리프가 정상적으로 표시**되는 것을 확인했다. 화면은 820×750 내외 첫 작품 홈/작품 생성 마법사/원고 집필실/진척 홈이며 Qt offscreen 제품 UX 증거에 한정한다. 이 이미지를 실제 Windows 바탕화면의 포그라운드 시각 인수나 전체 실사용 QA로 잘못 표시하지 말 것.
- 물리 Windows 11 OOBE 전경 문제, 모든 원래 01~100 단계, 장편 집필 품질/저작권 안전성/출판 검수는 아직 미완. **RELEASE_BLOCKED** 유지. `main`은 `69225edeed0a09ded5f847dad9b9ea63bc45367c` 그대로, 사용자의 실제 SQLite/원고 미수정. 새 예약/알림 자동화 생성 없음.


### 2026-10-15 15시경 검증 실패를 통한 추가 원인 수정

- **Windows fast studio run `38690349590`: FAILURE (원인 특정).** 단독 신규 SQLite 보호 테스트의 9개 시나리오 중 6개 정상, 재오픈 관련 3개가 teardown 시 `PermissionError [WinError 32]`로 실패. `PlotEditorSession.open_existing`의 read-only SQLite preflight가 `with sqlite3.connect(uri, uri=True) as probe`를 사용했는데, 표준 `sqlite3.Connection.__exit__`는 트랜잭션만 종료하며 연결을 닫지 않는다. `contextlib.closing`으로 모든 분기에서 **명시적 sqlite3 연결 종료**를 수행하도록 `plot_editor_model.py` 수정. Windows 파일 잠금과 기존 사용자 원고를 보호하려는 조치이며 이 변경의 재검증 결과는 확인해야 한다.
- **Linux Qt run `38690527581`: FAILURE (원인 특정).** Qt 테스트에서 이미 네비게이션 검증 부분이 DB 2화를 생성했는데, 새 실패 회차 이동 시나리오가 2화를 다시 생성해 `EpisodeError: 해당 회차가 이미 존재` 발생. 테스트에서 기존 합성 2화를 그대로 재사용하도록 `test_studio_gui_optional.py` 수정. 이 실패는 앱의 회차 중복 방지 검사가 작동한 것이고, 테스트 설정 오류이지 작품 데이터를 버리는 버그가 아니다.
- 소스 최신 수정 SHA `ef53fd3f4ddff6af2bf319b34a4a9db5fda2784b`. 재검증 run: Linux Qt `38690721746`, Windows fast `38690721575`, Windows 실제 데스크톱 `38690721560`, Windows EXE `38690721823`. 직전 Linux/Windows 실패를 PASS로 바꿔 선언하지 말고 새 워크플로가 실제 `success`인지 확인할 것.
- 이전 성공 근거: Linux Qt `38689275922` SUCCESS(회차 검색/저장 기본), real services `38690527616` SUCCESS(SQLite 외 구성 서비스 별도). 하지만 현재 커밋의 전체 검증은 아직 `RELEASE_BLOCKED`. 예약/자동화 새로 생성하지 않았고 `main` 및 실제 사용자 데이터 변경 없음.


### 2026-10-15 15:36 KST 검증: 본문 찾기·바꾸기 / 집중 집필 모드

- Windows 데스크톱 집필실에 **본문에서 찾기 / 다음 찾기 / 선택 항목 바꾸기** 기능을 추가. 검색 문자열이 일치하지 않으면 원고 수정 없음. 바꾸기는 선택한 한 곳만 수정하며, 직접 `원고 버전 저장`을 누르기 전에는 로컬 SQLite에 반영하지 않는다. Qt UI 클릭 테스트에서 검색, 한 곳 바꾸기, 미저장 표시, DB 기존본 보존, 검색 미발견을 검증.
- 820px 수준의 좁은 창에서 찾기와 바꾸기를 위아래 두 줄 그리드로 배치해 편집 공간의 가로 잘림 최소화. 오프스크린 Qt 캡처를 육안으로 확인: 한글 폰트 정상이고 원고 본문/검색 UI 접근 가능. 그러나 화면 미려함·Windows 물리 GUI 인수 기준 만족 주장은 금지.
- **집중 집필 모드** 버튼: 회차 목록과 우측 설정/검수 패널을 숨기고 원고 입력 공간을 넓힌다. 다시 누르면 회차 목록과 패널 설정을 복구하며, 원고나 DB 값은 바꾸지 않는다. Qt 클릭 회귀 테스트에서 모드 전환·기존 원고 및 회차 유지 검사.
- **성공 검증**: 최신 소스 `5a68a4ed12bbfcc9113ee4b00f42cce8cc6fd20b` Linux Qt run `38693335765` SUCCESS, Windows fast Qt run `38693335630` SUCCESS. 이전 2열 좁은화면 코드 `c4412f54` Linux Qt `38692951451` SUCCESS. 현재 진행 중인 Windows 11 **실제 EXE/화면** run `38693335741`, 패키징된 AI 실행 run `38693335787`은 성공이나 사용자인수로 단정 금지. 쌓인 취소 결과는 실패/성공과 구분.
- 이 시점에 `main`은 `69225edeed0a09ded5f847dad9b9ea63bc45367c`, 사용자 SQLite/원고 미변경, 예약 생성 없음. 원래 01~100, 실제 Windows 11 foreground 사용자 조작, 장편 30/100/250화 품질·전수 유사성은 여전히 **RELEASE_BLOCKED**.


### 2026-10-15 즉시 개발: 사용자가 지정한 신규 TXT 원고 안전 사본

- [예약 없음] 사용자 "계속"은 **즉시** 개발·수정·검증을 수행하라는 뜻. 새 예약·자동화 생성 없음.
- `src/ai_novel_factory/desktop/draft_backup.py`에 명시적 `write_draft_copy(destination, prose)` 추가. 쓰기 허용 대상은 사용자가 직접 선택한 새 절대경로의 TXT 한 개, OS `O_CREAT | O_EXCL`로 경합 덮어쓰기 방지, UTF-8 원문 그대로, flush+fsync. 쓰기 실패 시 **본 호출에서 만든 파일이고 동일 inode인 경우에만** 불완전 파일 청소. 기존 SQLite DB·원고 버전·최종본·외부 게시와 무관. 로컬 TXT는 암호화가 아니므로 개인 정보 저장 위치에 주의 필요.
- `project_studio.py` 집필실에 `현재 원고를 TXT로 별도 보관` 버튼. **원고 수정·저장 충돌이 난 상황에서도 화면의 미저장 내용을 수동 선택한 새 파일로 복사**할 수 있다. 복사 뒤에도 편집기는 미저장 상태로 남고, 직접 `원고 버전 저장` 없이 DB 저장 완료로 표시하지 않음. 실패 시 개인정보 포함 경로를 화면에 공개하지 않음.
- `tests/test_draft_backup_safety.py` 7개 회귀 검사: 유니코드 정확한 바이트 복사, 기존파일 보존, O_EXCL 생성 경합, 빈/상대경로/SQLite 경로 거부, symlink 거부, 디스크 동기화 실패 시 자기 파일만 삭제. Linux와 Windows CI 단계에 모두 추가. GUI Qt 버튼 클릭으로 TXT 사본 생성·기존 파일 보호·원고 버전 2개 보존·편집기 미저장 상태 유지 확인.
- 도입 시 최초 Linux run `38694109119` / Windows fast `38694109130`은 `Path` 타입 검사 오류 때문에 실패. `isinstance(..., (str, Path))`로 수정. 이후 run `38694226531` / `38694226508`은 단독 TXT 테스트는 통과했으나 Qt GUI 테스트 내부 `patch` import 지연으로 실패. 테스트에서 `unittest.mock.patch`를 함수 첫 부분으로 이동.
- **검증된 최신 소스 SHA `6a18d9caeac6034de1768d6bda76f17bd0301fdb`**: Linux Qt run `38694356844` SUCCESS (독립 safety + 버튼, 스크린샷), Windows GUI run `38694356896` SUCCESS (TXT 파일 잠금/보존 + 실제 Qt 위젯 버튼), real service run `38694356784` SUCCESS. Linux artifact `anf-linux-studio-qt-synthetic-screens`에서 820×750 GUI 원고 화면에 새 보관 버튼과 한글 정상 렌더됨을 직접 육안 확인. **이 결과로 물리 Windows 11 EXE 시각 인수 PASS를 주장하지 않는다.**
- 이 SHA Windows 11 QA run `38694356766`, 패키징 EXE+로컬 GGUF run `38694356849`은 확인 시 `IN_PROGRESS`. 실제 EXE 빌드, OS foreground 전경 가림 해소, 실제 로컬 모델과 30/100/250회 장편 품질 및 01~100 요구사항 전체 기준은 **RELEASE_BLOCKED**. `main` / 사용자 원고 / 키 / 설정 미변경.
