# 16/100단계 — PDF 파서

진행 시점: 2026-10-12, 15단계 직후 사용자의 직접 지시에 따라 즉시 진행.

## 목표 및 범위

첨부된 AI Novel Factory 기획안의 `참고소설 분석 → 텍스트 추출` 과정 중 `.pdf` 입력을 처리한다. 13단계 `ParsedReference` / `ParsedBlock` 데이터 계약을 활용해 **텍스트 선택이 가능한 PDF**를 페이지 순서대로 읽고, 스캔/이미지 전용 PDF를 식별한다. 외부 AI, OCR, 저장소, 데이터베이스, 업로드, 출판 기능은 이 단계의 범위가 아니다.

## 변경 파일

- `src/ai_novel_factory/references/pdf_parser.py`: `parse_pdf_bytes`, `parse_pdf_file`, `ParsedPdfReference` 구현.
- `src/ai_novel_factory/references/__init__.py`: PDF 파서 API 노출.
- `tests/test_pdf_parser.py`: 생성한 합성 PDF를 이용한 자동 테스트 21개.
- `docs/stage16_pdf_parser.md`: 본 문서.
- `docs/stage16_test_results.json`: 실행 검증 기록.
- `docs/pending_user_actions.md`: PC 환경에서의 승인/테스트 보류 기록.

## 계약 및 반환값

```python
from ai_novel_factory.references import parse_pdf_file

parsed = parse_pdf_file(r"C:\reference\sample.pdf")
print(parsed.format)            # pdf
print(parsed.page_count)        # 전체 페이지 수
print(parsed.paragraph_count)   # 추출된 문단 블록 수
print(parsed.image_only_pages)  # (2, 5)처럼 이미지 전용 페이지 번호
print(parsed.empty_pages)       # 콘텐츠가 없는 것으로 판단된 페이지 번호
```

- `ParsedPdfReference`는 기존 `ParsedReference`를 확장한다. 원문 문자열은 **메모리에만 존재**, `repr`에는 포함하지 않는다.
- `blocks`는 PDF의 읽기 순서인 **페이지 순서**로 수집한다. 한 페이지 안에서는 pypdf가 반환한 텍스트 순서에 의존한다. 다단 편집·복잡한 지면 순서는 틀릴 수 있다.
- `ParsedBlock.start_line`과 `end_line`은 PDF에 대해서만 실제 줄 번호가 아니라 **1부터 시작하는 페이지 번호**다.
- 빈 줄로 나뉜 텍스트를 문단으로 처리하고 시각적 자동 줄바꿈은 강제로 합치지 않는다.
- `image_only_pages`는 글자가 추출되지 않으면서 이미지 XObject가 확인되는 페이지다. 원본 전체가 이미지 기반이고 추출된 텍스트가 없으면 `OCR이 필요합니다` 오류를 낸다. 일부 이미지 페이지가 혼재하면 나머지 추출 결과를 반환하면서 이미지 페이지 번호를 명시한다.
- 암호화 PDF, 손상된 PDF, 잘못된 확장자, 심볼릭 링크, 크기/페이지/문자 수 제한 초과는 원문·경로를 노출하지 않는 오류 메시지로 중단한다.
- 기본 제한: PDF 파일 32MiB, 500페이지, 본문 2백만 글자, 페이지당 추출 텍스트 10만 글자, 최대 문단 블록 5만 개. **검증용 임시 상한**이며 악의적인 모든 PDF 리소스 소모를 완벽히 방어한다는 뜻은 아니다.
- PDF 첨부파일, 주석, 양식 필드, 이미지 픽셀 내용, OCR 결과는 추출하거나 실행하지 않는다.

## 실행 및 재현 (사용자 PC 설치/실행은 승인 후)

PowerShell에서 프로젝트 루트로 이동한 뒤:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "pypdf>=5,<7" "python-docx>=1.1,<2" "fastapi>=0.115,<1"
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python scripts/smoke_test.py
python -m compileall -q src tests
```

위 명령은 **사용자 PC에서 실행한 것이 아니며**, 설치·서버 실행 승인 전까지 PC 작업을 보류한다. 3종 외부 패키지는 기존 파서·API 테스트를 위한 최소 후보이며 Windows GUI 테스트에는 PySide6가 추가로 필요하다.

## 검증 요약

- 신규 PDF 단위 테스트 21개 통과 (텍스트 페이지 순서, 페이지/문자 제한, 이미지 기반 탐지, 빈 페이지, 암호화 거부, 경로/파일 무결성, 오류 메시지 안전성 등).
- 전체 113개 중 110개 통과, GUI 관련 3개는 PySide6 미설치로 건너뜀.
- 초기 스모크 검사 필수 6개 통과, Python 버전 차이 경고 1개 (현재 테스트 환경은 Python 3.13이며 목표 버전 3.12는 미검증).
- 합성 한국어 PDF 2페이지를 ReportLab과 시스템에 설치된 한국어 글꼴로 임시 생성하여 `pypdf`의 한글 문자열 순서와 내용을 비교, 통과. 테스트용 글꼴 파일은 사용자 산출물에 포함하지 않음.

## 저작권 및 실행 제약

분석은 사용 권한이 있는 참고작에만 수행한다. 참고소설 원문을 새로운 소설로 복사하지 않고 **구조적 특징**만 분석에 사용한다. Novel Bible이 참고 Profile보다 항상 우선하며, 뒤의 유사성 검사 및 출판 전 사용자 승인 규칙은 변경하지 않는다. 이번 파서는 원문을 **임시로 메모리에 보유**하므로 호출자 역시 원문 저장, 로깅, 외부 전송을 하지 않아야 한다.

**통합 보류:** 2·4·7·12·14단계 독립 산출물이 이번 작업의 선행 ZIP에서 확인되지 않아 해당 모듈과의 통합이 성공했다고 주장하지 않는다. 16단계 결과는 15단계 ZIP에 누적한 코드다. 이 문서는 17단계 회차 분할을 구현하지 않는다.

## 완료 판정

- 완료: PDF 독립 파서, 안전 입력 검사, 텍스트 추출 및 이미지 페이지 판별, 단위/회귀 테스트, 개발 ZIP 생성.
- 보류: Windows/Python 3.12 실행, 실제 사용자 PDF 대량 호환성, OCR, 12·14단계 통합, EXE 빌드.
- 다음 단계: **17단계 — 회차 분할** (다음 사용자 지시 또는 해당 예약 실행 시).
