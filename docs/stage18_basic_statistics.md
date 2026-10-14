# 18단계: 기본 문서 통계

`ai_novel_factory.references.measure_reference(document)`가 기존 TXT/Markdown/DOCX/PDF `ParsedReference`와 17단계 `split_episodes()`를 받아 원문을 저장하지 않고 **수치만** 반환합니다.

- 전체·회차별 **공백 포함 문자 수**(블록 텍스트의 글자 수 합계), **공백 제외 문자 수**(Unicode 공백 미포함), 공백으로 나눈 **토큰 수**, **문장 수(휴리스틱)**, 문단 수
- 평균 문장 길이·평균 문단 길이: 공백 제외 문자 수 / 해당 단위 수, 소수점 두 자리
- 회차당 평균 길이: 회차별 공백 제외 문자 수 평균. 서문은 이 평균에서 제외하고 전체 통계에는 포함
- 제목 블록·회차 헤더·Markdown 코드 블록 제외. DOCX 표는 한 문단으로 간주
- 마침표·물음표·느낌표·동아시아 문장부호의 뒤가 공백이나 끝이면 문장 종료로 추정. 마침표 내부의 소수점은 제외. **정밀한 문장 경계·형태소 분석은 제공하지 않습니다.**
- 모든 연산은 메모리에서만 수행. 원문·파일 경로·API 키를 결과, 로그 또는 저장소에 기록하지 않음

## 실행

```powershell
$env:PYTHONPATH = "src"
python -m unittest tests.test_basic_statistics -v
python -m unittest discover -s tests -v
```

## 예시

```python
from ai_novel_factory.references import parse_text, measure_reference
novel = parse_text("1화\n\n첫 문장.\n\n2화\n\n두 번째 문장.")
stats = measure_reference(novel)
print(stats.episode_count, stats.total.characters_no_whitespace)
```

## 품질 범위

스캔 PDF OCR 불가, 미구현 EPUB 파서, 한국어 형태소 분리는 이번 단계의 범위가 아닙니다. 이전 단계 2/4/7/12/14 일부 산출물의 이관·실제 Windows GUI 검증이 남아 있습니다. 외부 AI API 호출은 사용하지 않습니다.
