# 8단계 — PySide6 데스크톱 기본 UI

## 목표
기획안의 관리자 메뉴 12개를 가진 Windows용 데스크톱 프로그램의 기본 창을 구현한다.
현재는 메뉴 탐색과 화면 표시만 지원하며 API·DB·AI·출판을 연결하지 않는다.

## 파일
- `src/ai_novel_factory/desktop/navigation.py`: 메뉴 계약 (Qt 비의존)
- `src/ai_novel_factory/desktop/app.py`: PySide6 창·사이드바·페이지
- `src/ai_novel_factory/desktop/__main__.py`: 실행 및 의존성 오류 안내
- `tests/test_desktop_navigation.py`: 독립적인 메뉴 테스트
- `tests/test_desktop_gui_optional.py`: PySide6 설치 시 GUI 스모크 테스트

## 실행
프로젝트 루트에서:
```powershell
$env:PYTHONPATH = 'src'
python -m ai_novel_factory.desktop --check
python -m unittest discover -s tests -v
# 사용자 승인 후, 별도 Python 환경에 desktop 의존성이 설치된 경우:
python -m ai_novel_factory.desktop
```

## 안전 규칙
- 참고소설 원문을 로드하거나 복제하지 않는다.
- Novel Bible 우선 정책을 변경하지 않는다.
- 유사성 검사 화면은 준비만 하며 검사 통과를 주장하지 않는다.
- 출판 버튼·AI 호출·네트워크 작업을 구현하지 않는다.
- API 키, 사용자 PC 설정, 외부 저장소에 접근하지 않는다.

## 검증 제한
PySide6가 없는 실행 환경에서는 GUI 스모크 테스트가 건너뛰어진다.
Windows GUI 실기기 검증 및 EXE 빌드는 수행하지 않았다.
2·4·7단계 산출물은 현 작업 공간에서 확인되지 않으므로 통합 검증은 보류한다.
