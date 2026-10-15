# AI Novel Factory — 원본 기획안/100단계 사용자 경로 결함 감사 (2026-10-15)

**검증 브랜치 전용, 정식 출시/인수 승인 아님.** 사용자가 제공한 기획안 및 공식 01~100단계 계획을 기준으로 실제 소스 모듈, PySide6 화면, Windows GitHub Actions 로그를 구분한 감사이다. 원본 누적 문서는 변경하지 않는다.

## 확인된 최초·주요 단절

- **03단계 기술 구성**: 실제 PostgreSQL/pgvector, Redis/Celery 서비스 실연동 미검증. 일부 모듈은 선택적 설정, 로컬 대체, 테스트용 인터페이스다. 근거: scene_vectors.py, celery_local_adapter.py, docs/stage100_release_and_acceptance.md.
- **08단계 사용자 화면**: 메인 창이 존재하던 기존 app.py는 12개 메뉴 중 9개가 “해당 기능은 후속 개발 단계에서 연결됩니다”였다. 메뉴 이름과 DB 모듈의 존재를 GUI 완성으로 표시할 수 없다.
- **41~50단계 기억 DB**: Novel Bible, Character, World, Timeline, Relationship, Foreshadowing 저장 모듈은 존재했으나 원래 전용 화면과 단절. 이번 검증 브랜치에서 기존 SQLite DB/프로젝트 ID로 연결했다.
- **61~70단계 AI 사용**: 기존 Windows CI가 별도로 Python, PyTorch, Transformers 및 공개 SmolLM2 135M 모델을 설치한 것은 EXE 하나만 갖고 사용하는 최종 사용자 경험의 검증이 아니다.
- **95~100단계 실제 출판**: publisher_adapter.py는 sandbox simulation만 구현하고, 실제 플랫폼 업로드는 미지원. 실계정/공식 정책/실환경 승인 및 Windows 물리 화면 인수가 남아 있다.

## 10개 개발 구간 기능 대조

| 원본 단계 | 존재/연결한 기능 | 명확히 미검증 또는 미완성인 부분 |
|---|---|---|
| 01~10 개발 기반/EXE 구조 | PySide6 GUI, 로컬 FastAPI health check, Windows PyInstaller 빌드 | PostgreSQL/Redis 실연동, 사용자 PC 설치·설정 |
| 11~20 참고 파일 등록/읽기 | TXT/MD, EPUB, DOCX, PDF 파서, 참고 파일 선택 및 분석 GUI | 깨끗한 새 PC에서 각 형식 전수 재검증, 작품별 선택 참고작 자동 연계 |
| 21~30 Reference Analyzer | 구조·통계/Profile 계산 및 표시 모듈 | 전체 분석 품질 및 기획·집필까지의 전달 증명 |
| 31~40 다중 패턴 | 장르 패턴·강도·요소 선택·사용 이력, 이번에 저장 패턴 조회 GUI 연결 | 선택 패턴을 자동 Writer/Planner에 실제 주입하는 전체 흐름 |
| 41~50 Novel Bible/장편 기억 | Bible·인물·세계·시간선·관계·복선·Knowledge·Style·Episode 저장 모듈, 이번에 6개 사이드바 편집 GUI 연결 | 고급 지식/Style 조작과 모든 CRUD·충돌 복구 사용성 |
| 51~60 자동 기획 | Story Arc·Episode/Scene Planner·Plot 편집 모듈, 이번에 장르/소재/목표량/분위기 저장 | 초기 설정만으로 전체 Story Arc/회차 계획 자동 완성 |
| 61~70 AI Writer/작업 | 로컬 EXE IPC, 장면 초고·저장, 일부 작업 큐 및 Qt 화면 | 쉬운 일반 사용자 모델 설정, 실 Redis/Celery 연계, 장편 품질 |
| 71~80 품질 검사/자동 수정 | Continuity·Knowledge·Timeline·Foreshadow·Logic·Style·Repetition·Similarity·Reader·Rewrite 모듈 | 등록 참고작 전수 자동 검사, 전 자동 검수/수정 사용자 흐름 |
| 81~90 장기 운영 | Memory Delta, 버전관리, Scheduler API와 Mock 기반 장기 시험 | 실제 모델 30화/100화 장시간 생성, 설정 유지·자동 재개 실증 |
| 91~100 출판/배포 | Cover, Metadata, EPUB3, 웹소설 원고 출력, Windows EXE | 실플랫폼 API/실게시, EPUBCheck/실리더, Windows 물리 화면, 인수 승인 |

## 이번 검증 브랜치 변경

- src/ai_novel_factory/desktop/canon_workspace.py — Novel Bible, Characters, World, Timeline, Relationships, Foreshadowing 메뉴. 기존 저장소와 프로젝트 격리·revision을 사용해 신규/기존 기록 저장.
- src/ai_novel_factory/desktop/additional_workspaces.py — 저장 Reference Pattern 조회, **사용자가 직접 제공한 참고 텍스트로만** 국소 비교, 비공개 TXT/EPUB 준비. 이 화면은 전수 유사성 검증/실제 출판 기능이 아니다.
- src/ai_novel_factory/desktop/app.py — 12개 메뉴를 빈 안내문 대신 앞의 실제 저장·조회·준비 위젯에 연결.
- src/ai_novel_factory/desktop/authoring_controls.py, authoring_session.py, authoring_workflow.py — 장르/소재/목표 회차/회차별 글자 수/분위기 저장 및 Writer 컨텍스트와 경로 선택기.
- src/ai_novel_factory/desktop/ci_user_journey.py — 실제 Windows 패키징 EXE 내부의 Qt 입력·버튼, 별도 EXE 프로세스 재실행/복구, TXT/EPUB 재읽기, 사이드바·SQLite 저장 검사.
- 모든 신규 코드·테스트는 validation 브랜치에만 존재. main 수정·merge·pull request 없음.

## 검증 증거와 주의

- Windows 패키징 EXE 기본 집필/AI 초고/저장/EXE 재실행/TXT/EPUB 재읽기: Actions 38661031596 PASS.
- 설정·인물·세계·시간선·관계·복선 6개 GUI 저장: Actions 38663984228의 개별 단계 PASS. 당시 나머지 3개 메뉴가 미연결이라 전체 잡은 FAIL.
- 이 감사 작성 시점 이후 새 커밋의 Windows Actions 종료·로그까지 확인해야 최종 코드 검증을 판정할 수 있다. 메뉴를 열 수 있다는 사실은 100단계 완성 증거가 아니다.
- 실사람 디스플레이·기기 호환성, 250화 자동 작성, 30/100화 실제 모델 장기 시험, 실서비스 PostgreSQL/Redis, 등록 참고작 전체 유사성, 외부 게시·API/계정/승인 및 최종 창작물 품질은 UNVERIFIED 또는 명시적 미구현이다.

**최종 인수 판정: RELEASE_BLOCKED.** 원본 목표인 참고작 구조 분석 → 자동 기획 → 장기 집필/검사/재작성 → 기억 갱신 → EPUB/표지 → 사용자 승인 후 출판 전체 흐름은 추가 구현·실사용 검증이 필요하다. 완료되지 않은 단계를 완료로 상향하지 않는다.
