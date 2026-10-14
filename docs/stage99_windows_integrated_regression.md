# 99단계 — Windows 실제 실행 및 종합 회귀 테스트

## 원본 목표 / 검증 상태

- 공식 로드맵 99단계는 **Windows 실제 실행/종합 회귀 테스트**이다.
- 기존 `docs/requirements.md` **ANF-REQ-071**: Windows 종합 회귀 보고서에서 통과·실패·미검증 구분.
- **이번 실행은 Linux / Python 3.13.5**에서 이뤄졌다. Windows PC, Windows GUI, PyInstaller EXE 실빌드와 사용자 눈으로 확인한 UI 실행을 검증할 수 없었으므로 **99단계 인수 미충족**.
- 기존 95 공식 API/96 플랫폼 규격/97 Windows EXE 미충족 역시 유지.
- 원본 기획안 TXT는 이 실행에서 실제 첨부에 접근하지 못했다. 대화의 공식 로드맵과 누적 소스 요구사항 기준으로 범위를 결정했다.

## 구현한 오프라인 검증 코드

- `scripts/stage99_windows_acceptance.py`: 실행 OS 및 Python 버전 검사, 명시된 경로의 Windows PE 확인, 실제 Windows에서 EXE의 `--check`, `--gui-smoke` 실행 후 종합 회귀 도구 연결. **비Windows에서는 테스트를 실행한 척하지 않고 exit 2 + `UNVERIFIED` 출력**. 실제 Windows에서만 실행된 증거를 기록한다.
- `scripts/stage99_partitioned_regression.py`: 모든 `tests/test_*.py` 모듈을 중복 없는 8개 그룹으로 나누어 실행, stdout/stderr·명령·종료 코드를 기록한다. 설치·네트워크·게시 없음.
- `tests/test_stage99_windows_acceptance.py`: 거짓 Windows 인증 방지, 무효 EXE 거부, 서류/스모크만 통과하면 종합 회귀 미검증 유지, 출력 파일 무단 덮어쓰기 금지 등 테스트.

## Windows에서 수행할 실제 테스트 — 사용자가 마련한 별도 오프라인 PC 환경에서만

Windows x64 및 로컬 Python 3.12, 이미 확보된 의존성을 사용하는 허가된 환경에서 실행한다. **설치·다운로드나 외부 서버 조회를 이 스크립트가 하지 않는다.**

1. 97단계 `python scripts/build_windows_exe.py --report build/stage97-result.json`가 실제 Windows에서 성공하고 `dist/stage97/AI_Novel_Factory.exe`가 생성된 경우에 한한다.
2. `python scripts/stage99_windows_acceptance.py --preflight-only`로 실제 Windows 사전조건을 확인한다. 사전검사 자체는 Windows 실행 성공 증거가 아니다.
3. 기존 `build/stage99/` 폴더가 **없는 상태**에서 `python scripts/stage99_windows_acceptance.py --report build/stage99-evidence.json`을 실행한다. 모든 테스트의 stdout/stderr는 로컬의 `build/stage99/` 내부에 남는다. 이미 결과가 있으면 자동으로 덮어쓰지 않는다.
4. EXE가 Windows에서 실제 열리고 닫히는지, 로컬 연결 상태가 정확한지, 메뉴가 그려지는지, 키 입력·오류 대처가 동작하는지 **실제 화면에서 직접 확인**하여 별도의 수동 인수 기록으로 남긴다. CLI 결과의 `physical_display_user_review=UNVERIFIED`는 수동 확인을 절대로 자동으로 통과 처리하지 않는다.
5. 전체 회귀에서 누락/실패한 그룹이 하나라도 있으면 `FAIL` 또는 `UNVERIFIED`로 보고한다. 모의 모델이나 Qt 오프스크린 화면 시험을 실제 사용자용 GUI 검증으로 혼동하지 않는다.

검사기는 원고·참고작·프롬프트·비밀키를 출력 JSON에 포함하지 않는다. 로컬 코드와 이전 테스트에 한정하며 실제 외부 출판/업로드 또는 계정 접속 기능을 호출하지 않는다.

## 이번 실행 결과

Linux에서 `python scripts/stage99_windows_acceptance.py --preflight-only --report docs/stage99_linux_preflight.json` 실행: **exit 2**, `not_windows`, `python_not_3_12`, `exe_missing` 사유. Windows 종합 회귀와 GUI 실제 실행은 **UNVERIFIED**. 프로젝트 전체 테스트는 Linux 환경에서 별도로 수행하며, 이 결과를 Windows 인수 성공으로 주장하지 않는다.
