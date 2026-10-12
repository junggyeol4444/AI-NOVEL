# 18단계: 참고소설 기본 문서 통계

TXT/Markdown/DOCX/PDF 파서가 반환하는 ParsedReference 및 17단계 회차 분리 결과에 기본 통계를 적용합니다.

## 제공 통계
- 전체/회차별 공백 포함 문자 수, 공백 제외 문자 수
- 공백으로 나눈 토큰 수 (한국어 형태소 분석 결과가 아님)
- 문장 수 (마침표·물음표·느낌표·동아시아 문장부호 기반 근사치)
- 문단 수, 평균 문장 길이, 평균 문단 길이
- 회차 수, 평균 회차 길이 (본문 공백 제외 문자 수 기준)
- 서문 분량 분리 (전체 분량에는 포함, 회차당 평균에는 제외)

## 사용 방법

Python에서 ai_novel_factory.references의 parse_text 및 measure_reference를 가져와 사용합니다.
예: measure_reference(parse_text("1화\n\n첫 문장.\n\n2화\n\n둘째 문장."))

## 실행·검증

PowerShell:
$env:PYTHONPATH = "src"
python -m unittest tests.test_basic_statistics -v
python -m unittest discover -s tests -v

## 산출물과 보안 범위

- 원본 소설 문장/파일 경로를 통계 결과에 포함하거나 서버로 전송하지 않습니다.
- Markdown 코드 블록·회차 표제는 본문 통계에서 제외하며 DOCX 표는 본문 문단 하나로 계산합니다.
- 문장 경계 및 단어 개수는 휴리스틱이므로 통계 오차가 있을 수 있습니다.
- 스캔 PDF는 OCR 대상이며 이번 단계 범위가 아닙니다.
- EPUB 파서와 단계 12 해시 검증 및 일부 선행 단계의 코드 이전은 별도 후속 과제입니다.
- 외부 AI API를 사용하지 않습니다.
