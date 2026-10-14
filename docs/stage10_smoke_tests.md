# 10단계 — 초기 스모크 테스트

## 목표와 범위

9단계까지의 프로젝트를 기반으로 **프로그램 진입점과 필수 계약이 최소한 동작하는지** 확인한다. 이번 단계는 초기 점검용 테스트 도구만 추가한다. 새 기능, 소설 생성, 출판, DB 연결, Windows EXE 빌드는 수행하지 않는다.

## 신규 파일

- `scripts/smoke_test.py`: 오프라인 기본 점검, 선택적 로컬 HTTP 왕복, 선택적 Qt 오프스크린 확인.
- `tests/test_smoke.py`: 스모크 러너 동작과 안전 기본값 검증.
- `docs/stage10_smoke_tests.md`: 사용 방법, 판정 및 한계.
- `docs/stage10_test_results.json`: 현재 실행 환경의 테스트 결과 (별도 실행 후 기록).

## 실행 방법 (프로젝트 루트, Windows PowerShell)

```powershell
$env:PYTHONPATH = 'src'
python scripts/smoke_test.py
python scripts/smoke_test.py --json
python -m unittest discover -s tests -v
```

명시적으로 **로컬** API 서버 실행을 허용한 환경에서만:

```powershell
python scripts/smoke_test.py --with-http
```

PySide6를 설치하고 오프스크린 GUI 검증을 허용한 환경에서만:

```powershell
python scripts/smoke_test.py --with-gui
```

두 선택 옵션은 사용자가 실행하기 전까지 네트워크/GUI 프로세스를 시작하지 않는다. HTTP 모드는 `127.0.0.1`에만 임시 서버를 바인딩하며 종료 시 자식 프로세스를 정리한다. 외부 API, DB, Redis, AI 제공자, 출판 플랫폼에 연결하지 않는다.

## 판정 기준

- 필수 검사 `safe_defaults`, `health_contract`, `desktop_navigation`, `loopback_guard`, `api_cli`, `desktop_cli`가 모두 PASS.
- `python_version`은 개발 기준 3.12와 다른 환경에서 WARN으로 기록하고, 테스트 통과로 오인하지 않는다.
- 선택적 검사에서 미설치 의존성은 SKIP으로 기록하며, 수행했다고 보고하지 않는다.
- FAIL이 하나라도 있으면 종료 코드 1. 그렇지 않으면 0.
- 이 테스트는 전체 기능, 보안 감사, Windows EXE, 사용자 PC, 외부 서비스 통합 검증을 대체하지 않는다.

## 원기획 불변 규칙

참고소설 원문 복제 금지, Novel Bible 우선, 유사성 검사 및 출판 전 사용자 승인 원칙을 유지한다. 스모크 테스트는 참고소설·원고 데이터에 접근하지 않으며 생성·출판 기능을 호출하지 않는다.

## 통합 확인 보류

2·4·7단계 산출물은 확인되지 않아 해당 단계와의 연속 통합 검증은 미완료. 현재 실행 환경의 Python 버전이 3.12가 아니라면 대상 버전 재검증 필요. Windows GUI 실기기 확인 및 설치/설정은 사용자 승인 후 진행한다.
