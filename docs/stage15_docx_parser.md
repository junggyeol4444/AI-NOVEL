# 15/100단계 — DOCX 파서 (2026-10-12 11:00 Asia/Seoul)

## 목표 및 구현 범위

11단계의 참고파일 선택 흐름, 13단계의 `ParsedReference`/`ParsedBlock` 계약을 재사용하여 `.docx` 문서의 **본문 문단·제목·표를 원래 등장 순서대로** 메모리에서 추출한다. 이번 단계는 DOCX 파서만 추가하며 GUI 연결, 해시 계산, DB 저장, 회차 분할, AI 전송, 출판은 수행하지 않는다.

## 변경 파일

- `src/ai_novel_factory/references/docx_parser.py`: `parse_docx_file`, `parse_docx_bytes`, ZIP 안전성 점검, 제목·문단·표 추출.
- `src/ai_novel_factory/references/__init__.py`: 파서 공개 API 추가.
- `tests/test_docx_parser.py`: 합성 DOCX 문서로 읽기 순서·헤더 제외·파일 무변경·안전 실패·크기 제한 검증.
- `docs/stage15_docx_parser.md`: 본 문서.
- `docs/stage15_test_results.json`: 재현 가능한 실행 기록.

## 입력·출력 계약

```python
from ai_novel_factory.references import parse_docx_file

parsed = parse_docx_file(r"C:\\reference\\example.docx")
print(parsed.format, parsed.paragraph_count, len(parsed.blocks))
# 원문 문자열인 parsed.text / block.text는 로그에 출력하거나 저장하지 말 것.
```

- `format="docx"`, `encoding=None` (DOCX 내부 XML의 인코딩은 python-docx에서 처리).
- `blocks`는 문서 본문에 등장하는 문단, 제목, 표 순서. 제목의 수준은 `heading_level`에 표시.
- `ParsedBlock.start_line/end_line`은 **DOCX 본문 블록 순번**이며 실제 페이지/행 번호가 아니다.
- 표는 행 구분 `\n`, 셀 구분 `\t`로 정규화한다. 중첩 표·이미지·각주·주석·머리글/바닥글·변경 추적 텍스트·도형 텍스트는 이 단계에서 지원하지 않는다.
- 빈 문서, 손상된 ZIP, 암호화 문서, 매크로 포함 문서, 비정상 경로, 과도한 압축 해제 크기, 심볼릭 링크는 안전한 일반 오류로 거부한다.
- 기본 상한: DOCX 파일 32MiB, 압축 해제 합계 64MiB, ZIP 항목당 16MiB, ZIP 항목 수 1024, 추출 본문 200만 자, 본문 블록 5만 개. 이 제한은 임시 방어값으로 실제 대용량 문서 지원은 별도 설계 필요.

## Windows 실행·검증 명령 (프로젝트 루트, PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "python-docx>=1.1,<2"
$env:PYTHONPATH = "src"
python -m unittest tests.test_docx_parser -v
python -m unittest discover -s tests -v
python scripts/smoke_test.py
python -m compileall -q src tests
```

위 명령은 **사용자가 PC를 켜고 승인한 뒤에만** 실행한다. 실행 환경에 따라 `py -3.12`가 없을 수 있다. 설치 및 실제 Windows 검증은 현재 수행하지 않았다.

## 정책·제약

참고작 원문은 `ParsedReference.text` 및 `ParsedBlock.text`에 **일시적으로 메모리 보관**되며 디스크 저장, 로그 출력, 외부 전송, 모델 호출을 하지 않는다. 이후 생성 단계에서도 참고 원문 복제 금지, Novel Bible 우선, 유사성 검사, 출판 전 사용자 승인 정책을 유지한다. 파서는 저작권 이용 허락을 검증하지 않으므로 입력 권한 확인은 상위 흐름에서 수행해야 한다.

**통합 보류:** 현재 확보된 최신 선행 산출물은 13단계 ZIP이며 12단계 입력 검증·해시 및 14단계 EPUB 파서 산출물은 이 작업 공간에서 확인되지 않는다. 따라서 해당 모듈과의 통합이 검증되었다고 주장하지 않는다.

## 완료 판정

- 완료: 독립 DOCX 파서 코드 작성, 합성 문서 자동 테스트, 기존 프로젝트 회귀 테스트 및 기본 스모크 검사.
- 미완료: Windows/Python 3.12 실기기 검증, 실제 사용자 참고작 검증, 12·14단계와 통합, EXE 빌드.
- 다음 16단계: PDF 파서. 이번 산출물에는 PDF 파서 코드를 추가하지 않는다.