# 11단계 재검증 — 참고소설 파일 선택 UI

- 검증 기준: 2026-10-12 07:56 Asia/Seoul, 11/100단계
- 원본: `AI_Novel_Factory_stage11.zip` (기존 11단계 산출물)
- 이번 작업: 기존 11단계 소스의 압축 해제·실행 확인. 기능 범위를 넘어서는 수정 없음.

## 연결 파일 및 역할

- `src/ai_novel_factory/desktop/reference_selection.py`: 선택 경로를 메모리에만 보관하고 중복 제거, 파일명만 표시
- `src/ai_novel_factory/desktop/reference_picker.py`: PySide6 파일 선택 창, 선택 목록, 취소·초기화
- `src/ai_novel_factory/desktop/app.py`: Reference Novels 화면에 위젯 연결
- `tests/test_reference_selection.py`: 파일 접근 없는 선택 모델 테스트
- `tests/test_reference_picker_gui_optional.py`: PySide6가 있는 환경에서 GUI 테스트

## 재현 명령 (프로젝트 루트, PowerShell)

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python scripts/smoke_test.py
python -m ai_novel_factory.desktop --check
# 실제 Windows GUI 검증은 PySide6 설치된 개발 환경에서 별도로 수행
python -m ai_novel_factory.desktop
```

## 실제 검증 결과

- `python -m unittest discover -s tests -v`: 총 55개, 성공 52개, 건너뜀 3개, 실패 0개.
- 건너뜀 사유: 실행 환경에 PySide6 미설치, GUI 표시 테스트 미실행.
- `python scripts/smoke_test.py`: 필수 6개 검사 통과. Python 3.12 기준과 실행 환경 버전 차이 경고 1개.
- `python -m ai_novel_factory.desktop --check`: `UI section contract OK: 12 sections`.
- 원문 읽기·복사·분석·저장·업로드·AI 호출은 이 단계의 범위가 아님.

## 판정 및 한계

11단계 선택 모델과 정적 통합 검사는 완료. PySide6 GUI 실기기 및 Windows EXE 실행은 미검증.
2·4·7단계 독립 산출물과의 교차 검증은 보류. 원격 저장소 및 사용자 PC에는 변경 사항 없음.
Novel Bible 우선·참고작 원문 비복제·유사성 검사·출판 전 사용자 승인 원칙 유지.
