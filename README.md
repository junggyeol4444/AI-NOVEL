# 23단계 — 사건 시점 후보(정량 지표)

- `src/ai_novel_factory/references/event_timing.py` — 22단계 키워드 위치별 출현 분포
- `tests/test_event_timing.py` — 후보 위치·정보 보호·연동 테스트
- `docs/stage23_event_timing.md` — 분석 한계 및 실행 방법
- 예약은 사용자가 별도 요청 전까지 비활성 상태

---

# AI Novel Factory

Windows EXE 기반 AI 장편소설 자동 제작·출판 시스템 개발 프로젝트입니다.

## 개발 상태 (2026-10-12)

- 총 100단계 로드맵. 대화에서 16단계까지 단계별 ZIP이 보고되었고, **17단계 회차 분리 구현과 테스트 코드도 작성·GitHub 업로드되었습니다.**
- 현재 GitHub에는 기존 소스 및 문서의 **일부만 이전**되어 있습니다. 전체 17단계 누적 ZIP 내용과 GitHub 코드는 아직 완전히 일치하지 않습니다.
- 2, 4, 7, 12, 14단계 독립 산출물은 이전 대화에서도 확인되지 않았으며 통합 검증이 보류된 상태입니다.
- Windows EXE 빌드 및 Windows GUI 실기기 검증은 수행되지 않았습니다.
- 현재까지 GitHub에 업로드된 소스는 [Actions](../../actions)에서 Python 3.12로 자동 테스트할 수 있습니다.
- 전체 누적 개발 ZIP은 현재 대화의 Stage17 산출물에서 받을 수 있습니다.

## 실행과 테스트

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Windows에서 GUI를 실행하려면 추후 PySide6 설치 승인 및 실제 시스템 테스트가 필요합니다.

## 예약 정책

**사용자가 "예약"이라고 요청하기 전까지 자동 예약 개발은 중지합니다.**

- ChatGPT의 AI Novel Factory 정기 개발 예약은 비활성화되었습니다.
- GitHub Actions의 시간별 cron 예약도 제거되었습니다.
- Actions는 소스 업데이트(push), PR, 또는 수동 실행(workflow_dispatch) 때에만 검사합니다.
- 사용자가 대화에서 "계속"이라고 지시하면 그때만 다음 개발 단계로 진행합니다.
- GitHub Actions 자체는 신규 AI 코드를 작성하거나 자동으로 커밋하지 않습니다.

## 핵심 원칙

- 참고 소설의 원문·고유 설정·문장 복제 금지
- Novel Bible 설정 우선
- 설정 및 유사성 검사, 출판 전 사용자 승인
- API 키 및 비밀번호는 저장소에 업로드하지 않음
- PC 설치, 외부 서비스 연결 및 유료 이용은 사전 사용자 승인

## 개발 상태: 20단계 — 참고소설 가져오기 검증

- 파일 선택 → 메모리 파싱(TXT/Markdown/DOCX/PDF) → 회차 분리 → 기본 통계 → 메타데이터 등록 연결
- EPUB는 원래 기획에 포함되나, 누락된 14단계 파서가 연결될 때까지 명시적으로 거부
- 입력 바이트 단일 읽기 및 SHA-256, 원문·전체 파일 경로 DB 비저장
- 로컬에서 182개 테스트 중 179개 통과, GUI 3개 건너뜀 (별도 Windows 검증 필요)
- 테스트: `PYTHONPATH=src python -m unittest discover -s tests -v`
- 예약 실행은 사용자 요청에 따라 중지; GitHub Actions는 push/PR/수동 실행만 활성
