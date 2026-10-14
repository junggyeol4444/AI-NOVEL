# PC 단독 실행 설계 정정 및 검증 기록 — 2026-10-12

## 왜 정정했는가

이전 아키텍처는 GUI와 백엔드 API, PostgreSQL, Redis, AI 제공자를 별도 실행 위치에서
선택할 수 있도록 두었다. 이는 후속 사용자 지시인 **모든 기능이 로컬 PC에서 실행**과
충돌한다. GitHub 업로드 자체는 프로그램의 런타임 의존성을 만들지 않지만,
원격 서비스가 필요한 것으로 읽힐 여지를 남긴 설계는 잘못된 상태였다.

## 코드 현황을 확인한 내용

- 참고작 파서/분석 및 SQLite 메타데이터 DB는 현재 로컬 코드로 구현됐다.
- `desktop/api_client.py`와 `api/__main__.py`는 이미 localhost/loopback 이외 연결을 거부한다.
- FastAPI는 사용자가 명시적으로 실행하는 로컬 진단 선택 기능이다.
- 이번 정정에서 `settings.load_settings()`가 비로컬 API 호스트, DB/Redis 서비스 URL,
  외부 AI 프로바이더 및 로컬 모델에 쓰이지 않는 API 키를 거부하도록 변경했다.
- 3단계 기계 판독 설계를 PC 내부 실행으로 변경하고 런타임 검증 규칙을 추가했다.
- 외부 GitHub 연결 없이 이 로컬 ZIP에서 개발·검사한다.

## 이후 기능 설계에 강제되는 원칙

- GUI가 로컬 Python 함수를 직접 호출. 필수 서버 없음.
- SQLite 등 PC 파일에 사용자 설정·Novel Bible·회차 정보를 저장.
- 생성 중 장시간 작업도 같은 PC 내부 프로세스로 실행; 원격 작업자 없음.
- AI 추론은 PC에 설치한 로컬 모델로 수행; 유료 API 키 및 인터넷 없음.
- 참조작 원문 비복제, Novel Bible 우선, 생성물 유사성 검사, 출판 전 승인 계속 적용.

## 현재 한계

완제품/Windows EXE는 아직 없다. Novel Bible 구현, 실제 로컬 AI 집필,
인프로세스 작업 스케줄러, 패키징 및 오프라인 Windows 실기기 검증은 후속 과제다.
이번 변경은 원격 서비스 의존이 불가능하도록 **현 단계 설정과 설계 계약을 잠그는 것**이지,
미완성 기능을 완료했다고 주장하는 것이 아니다.

## 재현 가능한 검증

`PYTHONPATH=src python -m unittest discover -s tests -q`
`PYTHONPATH=src python scripts/smoke_test.py`
`PYTHONPATH=src python src/ai_novel_factory/architecture.py`

이번 결과는 추후 실행 로그와 함께 확인하며, Windows EXE는 별도 검증해야 한다.
