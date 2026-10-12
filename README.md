# AI Novel Factory

Windows EXE 기반 AI 장편소설 자동 제작·출판 시스템입니다.

## 개발 상태 (2026-10-12)

- 기획: 100단계.
- 별도 개발 산출물: 16단계(PDF 파서)까지 ZIP 형태로 작성 및 테스트 보고됨.
- **GitHub 코드 이전: 아직 완료되지 않음.** 기존 Stage16 ZIP의 Python 소스 및 테스트는 GitHub에 추가되어야 합니다. README가 개발 완료를 의미하지 않습니다.
- 기존 미확인 독립 단계: 2, 4, 7, 12, 14. 통합 검증 미완료.
- 다음 기능 개발: 17단계 회차 자동 분리.
- Windows EXE 빌드·실기기 검증: 미완료.

## 예약 및 CI

[GitHub Actions: hourly verification](.github/workflows/hourly-ci.yml)는 UTC 매 정시(한국시간 매 정시)마다 GitHub에 실제 올라온 코드를 검사합니다. GitHub 스케줄 실행은 지연될 수 있습니다. 소스코드가 아직 없다면 검사를 건너뛰고 *마이그레이션 대기*를 기록합니다. GitHub Actions 자체가 AI 코드를 생성하거나 GitHub에 커밋하지는 않습니다.

별도로 설정한 ChatGPT 매시간 개발 예약에서 다음 미완료 단계의 코드를 작성하고 GitHub 저장소에 반영을 시도합니다. 실행 및 푸시 결과는 각 회차에 확인해야 합니다.

## 핵심 원칙

- 참고 소설의 원문, 고유 설정 및 문장을 복제하지 않기
- Novel Bible이 Reference Profile보다 우선
- 유사성 검사 및 출판 전 사용자 승인
- API 키와 비밀정보를 GitHub에 커밋하지 않기
- 사용자가 승인하기 전 외부 계정/유료 서비스 연결하지 않기
