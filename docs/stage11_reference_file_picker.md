# 11단계 — 참고소설 파일 선택 UI

## 범위
8단계 PySide6 기본 창의 `Reference Novels` 화면(메뉴 8번째)에 파일 선택 UI를 추가합니다.
9단계 로컬 API 상태 확인 기능과 10단계 스모크 테스트는 그대로 유지합니다.

- 다중 선택 파일 대화상자: TXT, `.md`, `.markdown`, EPUB, DOCX, PDF
- 선택 파일의 **이름만** UI에 표시하며, 전체 경로는 임시 메모리에만 보관
- 추가 선택 시 중복 경로 제거 및 기존 선택 유지; 취소 시 이전 목록 유지
- 선택 목록 비우기 버튼, 현재 선택 개수와 '아직 가져오지 않음' 상태 표시
- 원문 열람·해시·복사·파싱·DB 저장·업로드·AI 호출은 수행하지 않음

**주의:** 파일 확장자 필터는 편의 기능일 뿐 보안 검증이 아닙니다. 파일의 실제 형식,
크기, 경로 유효성, 인코딩, 해시는 12단계 이후에 처리합니다. 참고작 원문 복제 금지,
Novel Bible 우선, 유사성 검사, 출판 전 승인 규칙은 변경하지 않았습니다.

## 변경 파일

| 경로 | 변경 |
| --- | --- |
| `src/ai_novel_factory/desktop/reference_selection.py` | 순수 Python 임시 선택 모델·확장자 필터 |
| `src/ai_novel_factory/desktop/reference_picker.py` | PySide6 다중 파일 선택 화면 |
| `src/ai_novel_factory/desktop/app.py` | `references` 화면에 선택 UI 연결 |
| `tests/test_reference_selection.py` | Qt 비의존 단위 테스트 |
| `tests/test_reference_picker_gui_optional.py` | Qt 오프스크린 선택·취소·초기화 테스트 |

## 실행 명령 (PowerShell, 프로젝트 루트)

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m ai_novel_factory.desktop --check
# PySide6가 설치된 Windows 개발 환경에서만 GUI 실행
python -m ai_novel_factory.desktop
```

## 완료 기준

1. 참고소설 화면에서 파일 선택·목록 표시·취소·초기화가 동작한다.
2. 실제 파일을 열지 않고 경로만 임시로 보관한다.
3. 기존 자동 테스트가 회귀 없이 통과한다.
4. PySide6 미설치 환경에서는 GUI 테스트를 '건너뜀'으로 명시한다.

실제 Windows PC GUI 검증과 EXE 빌드는 미실시. 원격 저장소 연결·사용자 PC 파일 변경 없음.
2·4·7단계의 독립 산출물은 확인되지 않아 통합 검증이 보류되어 있습니다.
