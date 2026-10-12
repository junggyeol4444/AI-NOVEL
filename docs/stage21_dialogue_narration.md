# 21단계 — 대사·서술 비율 분석

## 목표 및 범위

Stage 13~20의 **추출된 참고소설 문서 객체**를 메모리에서 분석하여 회차별·서문·전체의 대사 및 서술 비율을 계산한다. 별도의 AI, 외부 API, 원문 저장 또는 네트워크 연결이 없다.

## 산식과 판단 규칙

- 문서의 `paragraph`·`table` 본문만 분석한다. 제목 및 Markdown 코드 블록은 제외한다.
- `"..."`, `“...”`, `「...」`, `『...』`의 **닫힌 인용 부호**로 둘러싸인 문자를 *대사 추정*으로 분류한다.
- 짝이 없는 따옴표 뒤 본문은 대사로 간주하지 않고, 단일 인용 부호 `'...'`는 내면 생각과 구분할 수 없어 서술에 포함한다.
- 공백을 제외한 원문 Unicode 문자 수를 기준으로 계산한다. 문장 구분에 쓰인 부호도 문자 수에 포함한다.
- `대사 비율 = 대사 문자 수 / (대사 문자 수 + 서술 문자 수)`, 소수 네 자리 반올림. 분모가 0이면 0.0이다.
- 각 회차 시작 표제 및 서문을 구분하고, 총 문자 수는 Stage 18의 `characters_no_whitespace`와 일치해야 한다.
- 인용 부호 안의 제목·독백을 실제 발화와 구분하지 못하며, 따옴표 없는 대화는 미검출이다. 따라서 이것은 **의미론적 판정이 아닌 보수적인 규칙 기반 근삿값**이다. 정밀한 대화 행위 분류는 후속 AI 분석 단계의 과제다.

## 실행 예시

```python
from ai_novel_factory.references import parse_text, measure_dialogue_reference

document = parse_text('1화\n\n“가자.” 그는 말했다.')
result = measure_dialogue_reference(document)
print(result.total.dialogue_ratio, result.total.narration_ratio)
```

## 테스트

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_dialogue_statistics -v
python -m unittest discover -s tests -v
```

원문은 결과 객체 및 로그에 포함되지 않으며, Novel Bible 우선·참고작 비복제·유사성 검사·출판 승인 규칙은 변경하지 않는다. 기존 12·14단계 누락 기능과 Windows 실기기 GUI 검증은 여전히 보류된다.
