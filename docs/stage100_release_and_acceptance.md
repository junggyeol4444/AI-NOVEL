# 공식 100단계 — 최종 릴리스·사용설명서·인수 테스트 기준

## 근거와 범위

- 공식 사용자 제공 100단계 로드맵의 **100단계**에 한정한다.
- 실제 `docs/requirements.md`의 **ANF-REQ-072**: 산출물 목록, 설치 방법, 알려진 문제 제공.
- 원본 기획안 `붙여넣은 텍스트(1)(7)(1).txt`는 이번 실행에서 접근 불가하므로 **직접 검증하지 못함**. 사용자 제공 로드맵과 99단계 누적 ZIP 원본 요구사항을 우선한다.
- 이번 산출물은 출시 문서, 설명서, 체크리스트 및 무해한 로컬 릴리스 증거 검사기이다. 실제 EXE 빌드·외부 접속·인증·배포를 수행하지 않는다.

## 산출물 목록과 용도

| 파일 | 용도 | 현재 성격 |
|---|---|---|
| `README.md` | 최신 작업 이력 및 실행 안내 | 누적 소스 설명 |
| `docs/stage100_user_manual.md` | 오프라인 사용자 설명서 | EXE 미실행 명시 |
| `docs/stage100_release_and_acceptance.md` | 인수 기준 및 남은 오류 | 현재 문서 |
| `scripts/stage100_release_audit.py` | 이전 검증 보고서 및 문서 존재 감시 | 로컬 읽기 전용 코드 |
| `docs/stage100_release_audit.json` | 실제 Linux 환경 검사 결과 | 출시 차단 증거 |
| `docs/stage100_release_inventory.json` | 주요 소스/문서 해시 목록 | 자기 자신·전체 ZIP의 서명 아님 |
| `docs/stage100_test_results.json` | 신설 테스트 및 회귀 요약 | Linux에서만 유효 |
| `docs/stage100_verification_log.txt` | 실제 실행 명령/결과 기록 | 오프라인 실행 로그 |
| `AI_Novel_Factory_stage100_local.zip` | 이전 전 단계 포함 누적 소스 | 정식 제품 설치 파일 아님 |
| `AI_Novel_Factory_stage100_final_verification.json` | 별도 압축 해제 재검증 | ZIP 외부 별도 보고서 |

## 인수 체크리스트 — 거짓 통과 금지

| 범위 | 요구 조건 | 현 상태 |
|---|---|---|
| 91~94 | 로컬 표지·메타데이터·EPUB3·회차 TXT 파일 생성/구조 검사 | 기존 Linux 테스트 통과 기록. 실리더/플랫폼은 미검증 |
| 95 / ANF-REQ-066 | 공식 게시 플랫폼 규격 확인 + 허용된 테스트 업로드 검증 | **미충족/외부 접속 금지** |
| 96 | 공식 플랫폼별 형식 및 실환경 업로드 적합성 | **미검증** (사용자 지정 제한만 비교) |
| 97 / ANF-REQ-001 | Windows/Python 3.12에서 진짜 PyInstaller EXE 생성·실행·종료 | **미충족** (Linux/Python 3.13.5) |
| 98 / ANF-REQ-070 | 필수·선택·유료 구성요소 안내 | 로컬 안내·진단 코드 시험 통과 |
| 99 / ANF-REQ-071 | 실제 Windows EXE/GUI/종합 회귀, 실화면 사용자 검토 | **미충족**; Linux 검증으로 대체 불가 |
| 100 / ANF-REQ-072 | 산출물 목록·설치 방법·알려진 문제·인수 기준 | 문서 및 릴리스 감사 구현/테스트 대상으로 검증 |
| 보안/승인 | 사용자 PC 접근·원고 확정·외부 출판·계정 연결·유료 이용은 명시적 승인 후 | **이번 실행은 모두 미수행** |

**릴리스 판정: BLOCKED.** 100단계의 문서 완성을 다른 단계의 인수 완료 또는 전체 제품 출시와 동일시하지 않는다.

## 안전한 인수 검증 절차

1. 누적 소스 ZIP의 `ZipFile.testzip()`과 이전 ZIP의 파일별 내용/이름 보존을 독립적으로 확인한다. `.gitignore`, `.env.example` 등 숨김 파일을 제외하지 않는다.
2. 소스 실행 환경에서 `python scripts/stage100_release_audit.py --report local_release_audit.json`를 호출하면 95~99단계의 기존 JSON 증거를 확인한다. **리포트 파일이 이미 있으면 덮어쓰지 않는다.** 실행 상태가 `BLOCKED`이면 공개 릴리스 금지. 내용만 바꾼 자기보고형 JSON은 인증이 아니며 실제 증거를 따로 검사한다.
3. `python -m unittest -q` 등의 전체 테스트를 독립 압축 해제 환경에서 실행하고 명령/표준출력/표준오류/건너뜀 수를 보존한다. 이전 테스트 진행 기록을 대체하지 않는다.
4. **Windows x64 실제 컴퓨터**에서 합법적으로 준비된 오프라인 Python 3.12·PyInstaller·PySide6로 `python scripts/build_windows_exe.py --preflight-only`와 Windows 실빌드를 수행할 수 있다. 사용자 PC에서 자동 설치하지 않는다.
5. EXE 실제 실행/종료/GUI 표시/로컬 백엔드/보안 기능/전체 회귀를 `docs/stage99_windows_integrated_regression.md`에 따라 실측한다. 가상 플래그나 Mock Writer 결과는 실측이 아니다.
6. 공식 플랫폼 API 명세, 정책, 접근 허용과 계정·사용자 승인이 확보되지 않았다면 95~96의 외부 업로드 검사를 **UNVERIFIED**로 계속 보존한다. 실제 게시 전 원고·메타데이터·표지의 현재 승인 기록을 재확인해야 한다.
7. 최종 출시는 오프라인 리포트 자동 통과로 확정되지 않는다. 릴리스 책임자와 사용자가 실제 산출물, 변경사항, 라이선스, 알려진 문제, 설치 안내를 직접 검수하고 명시적 동의를 남겨야 한다.

## 현재 알려진 문제 및 보류

- **실 Windows EXE 없음**: Linux에서는 Windows PyInstaller EXE를 실제 생성·실행했다고 주장할 수 없다.
- **외부 게시 기능 비활성**: API 규격/플랫폼 규칙/샌드박스 실검증이 없다. 현재 접속 금지.
- **실제 로컬 LLM 추론 및 품질 미검증**: 86~87단계 장편 시험은 Mock Writer 기반.
- **PostgreSQL/pgvector, Redis/Celery 실연동 미검증**: SQLite 오프라인 대체 기능 위주.
- **완전한 문장 의미 유사성/저작권 판단 및 출판 적합성은 보증하지 않음**.
- **EPUBCheck·실제 전자책 리더 및 GUI 물리 화면 미검증**.
- 프로젝트 설정 대상 Python 3.12, 시험 환경 Linux 3.13.5 불일치. 일부 Qt GUI 테스트 미설치로 건너뜀.
- SQLite 연결 경고/테스트 건너뜀은 실행 로그에 보존하고 출시 적합성을 추정하지 않는다.

## 릴리스 서명/버전 정보 규칙

- 이 소스 ZIP은 **stage100 local developer handoff**, `RELEASE_BLOCKED`; 정식 v1.0 배포판이 아니다. 기존 `pyproject.toml`의 버전은 변경하지 않았다.
- `docs/stage100_release_inventory.json`은 선택한 주요 소스 구성 요소 SHA-256을 표시한다. ZIP 자체 해시는 ZIP 바깥 최종 검증 JSON에 기록해야 순환 해시를 피할 수 있다.
- ZIP 전체 검증 실패, 이전 파일 누락, 미확인 API/GUI 실증은 출시 허가로 바꾸지 않는다.
