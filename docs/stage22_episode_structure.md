# 22단계 — 회차 구조 지표 분석

## 목표

17단계 회차 경계와 18·21단계 통계를 활용해 회차별 **관측 가능한** 구조 지표를 정량화합니다. 장르·사건·복선·인물 심리를 이해한 것처럼 주장하지 않으며, 이후 AI 분석의 입력 후보로 사용합니다.

## 구현 (`src/ai_novel_factory/references/episode_structure.py`)

- `analyze_reference_structure(document, split=None)` — 서문을 제외한 회차별 본문 분석, 전체 통계와 검증
- `analyze_structure_text(text, number=1)` — 개별 문자열 분석
- 위치 기반 3구간 `opening`·`middle`·`ending`: 구간별 문단 수, 공백 제외 글자 수, 인용부호 기반 대사 추정 비율
- 고정 어휘 **갈등(conflict)**, **진행(progression)**, **보상/해결(payoff)**, **반전(reversal)** 키워드 출현 횟수
- 마지막 문단의 `?`·`!`·`…` 표시: `ending_hook`가 `question`, `exclamation`, `ellipsis`, `none` 중 하나인 경우만 인정
- `possible_hook=True`는 **후보**일 뿐 실제 클리프행어 판정이 아님
- 참고 작품의 내용/문장/제목/전체 경로는 결과 구조체, DB 또는 로그에 포함하지 않음

## 분할 경계

회차별 본문 문단이 1개라면 ending에만, 2개라면 opening/ending에 하나씩 배치합니다. 3개 이상일 때 문단 순서상 3등분하며, **플롯의 실제 도입·중반·결말로 분류한 결과가 아닙니다.** 키워드는 공백·문장부호로 구분된 고정 어휘를 세므로 `성공했다`처럼 활용된 형태는 탐지하지 못할 수 있습니다. 부호와 키워드 출현 횟수는 정확한 서사 사건 감지 결과가 아니며, 인용문 안의 단어도 집계될 수 있습니다.

서문은 `preface_characters`만 별도로 표기합니다. Markdown 코드 펜스와 회차 제목은 본문 분석 대상이 아닙니다. TXT/Markdown/PDF/DOCX에서 생성된 `ParsedReference`를 공통 인터페이스로 사용합니다. EPUB 파서는 14단계 누락 산출물 때문에 아직 통합되지 않았습니다.

## 검증

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python scripts/smoke_test.py
```

자동 검증으로 구간 보존, 마지막 문장 부호, 고정 어휘, 회차/서문 경계, DOCX·PDF 공통 블록, 잘못된 회차/분리 결과 거부, 결정성, 원문 비노출을 점검합니다. Windows EXE 실사용·AI 의미분석의 정확도는 검증 범위 밖입니다.

## 이후 단계

23단계: 주요 사건 시점 추정. 실제 주요 사건을 판정하려면 구조 키워드 외에 별도 의미분석과 사용자 검수 절차가 필요합니다. 참고소설의 원문 표현을 새 소설 원고에 복제하지 않습니다.
