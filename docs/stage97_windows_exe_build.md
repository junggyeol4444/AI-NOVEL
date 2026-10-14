# 97단계 — PyInstaller Windows EXE 빌드 (오프라인 준비 / 실제 Windows 빌드 미완료)

## 공식 기준 및 상태

- 공식 100단계 로드맵 **97: PyInstaller Windows EXE 빌드**.
- 기존 `docs/requirements.md`의 **ANF-REQ-001**: Windows 빌드 산출물 생성 + 실행·종료 시험. 이 기준은 **아직 충족되지 않았다**.
- 원본 기획안 `붙여넣은 텍스트(1)(7)(1).txt`는 현재 접근 가능한 파일에 없어 직접 재확인하지 못했다. 사용자가 대화에서 제공한 로드맵과 ZIP 내부의 기존 요구사항을 사용하였다.
- 기존 95단계 ANF-REQ-066 공식 플랫폼 테스트 업로드 및 96단계 공식 규격 확인도 **미완료**이며 이번 빌드 설정 작업은 이를 해결하지 않는다.

## 추가한 실제 소스

1. `packaging/windows/launcher.py` — 기존 PySide6 데스크톱 진입점을 유지하며 `--check`(GUI 구조 검사), `--gui-smoke`(Qt 오프스크린 창 생성·닫기) 지원. 임의의 원고 확정·업로드·네트워크 호출 없음.
2. `packaging/windows/AI_Novel_Factory.spec` — Windows에서 기존 GUI 모듈을 포함하는 PyInstaller **one-file GUI EXE** 분석·묶음 설정. PyInstaller 자동 훅이 제공하는 Qt 동적 라이브러리를 필요로 하므로 실제 Windows 실행 검증 필수.
3. `scripts/build_windows_exe.py` — Windows + Python 3.12 + PyInstaller + PySide6 사전 검사, 기존 출력 덮어쓰기 방지, 로컬 패키징, PE 헤더 간이 검사, EXE의 `--check` 및 `--gui-smoke` 실제 Windows 실행 검증, SHA-256 증거 기록. 오프라인에서만 실행하고 외부 다운로드·업로드를 수행하지 않음.
4. `scripts/verify_release_bundle.py` — 소스 ZIP 검증에서 위 **지정된 경로의 단 하나의 `.spec` 파일만** 허용. 그 외 `.spec`, 사용자 데이터, 배포 바이너리는 여전히 거부.
5. `.gitignore` — 기존의 모든 `.spec` 무시 규칙은 유지하고 추적 대상인 위 단일 `.spec`만 예외 처리.

## Windows 실행 명령 — 승인된 준비 환경에서 로컬 수동 실행

실제 Windows x64 PC의 Python 3.12 환경에 이미 오프라인 제공된 PyInstaller/PySide6 패키지가 있어야 한다. 여기서는 다운로드·패키지 설치·계정 연결을 하지 않는다. 미설치이면 중단한다.

```powershell
python scripts/build_windows_exe.py --preflight-only --report build/preflight.json
python scripts/build_windows_exe.py --report build/stage97-result.json
```

빌드가 정말 성공했다면 `dist/stage97/AI_Novel_Factory.exe`가 생성돼야 하고 빌드 스크립트는 **그 EXE를 Windows에서 실제 실행**하여 `--check` 및 `--gui-smoke` 통과 기록이 있어야만 `windows_runtime_verified=true`로 표시한다. 실행/종료 및 사용자 GUI 확인은 99단계에서 추가 시험해야 한다. 사전검사 없이 빌드를 강행하는 옵션은 없다.

`--gui-smoke`는 그래픽 환경을 모의하는 한정 검사이며 실제 사람이 보는 창·장시간 운용·오프라인 Windows 실기기 호환성 증명은 아니다. PE 헤더도 단독으로는 실행 가능성 증명이 아니다. 로컬 AI 추론, 실제 Redis/Celery·pgvector, 게시 플랫폼 연결, 완전 자동 집필 등은 이번 작업의 검증 범위가 아니다.

## 이번 Linux 실행의 실제 결과

환경: Linux / Python 3.13.5. PyInstaller, PySide6 미설치.

- `PYTHONPATH=src python packaging/windows/launcher.py --check` → exit 0; 진입점 구조 검사만 통과.
- `python scripts/build_windows_exe.py --report docs/stage97_build_preflight.json` → exit **2**, 이유 `not_windows`, `python_not_3_12`, `missing_pyinstaller`, `missing_pyside6`.
- **Windows EXE 생성: 미수행 / 실제 Windows 런타임: 미검증.**
- 네트워크·GitHub·클라우드 AI API·외부 출판 API 사용 없음. 승인 없는 원고 확정·출판·업로드 없음.

## 검증 범위

`tests/test_stage97_windows_packaging.py`의 패키징 구조·가드·변조·실행 진입점 오프라인 계약 검사와 기존 프로젝트 전체 회귀 검사를 수행한다. 증거는 `docs/stage97_test_results.json`, `docs/stage97_verification_log.txt`, `docs/stage97_worktree_*`, `docs/stage97_candidate_*` 및 별도 최종 검증 결과에 기록한다.
