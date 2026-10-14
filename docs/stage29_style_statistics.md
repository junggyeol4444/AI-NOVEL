# 29/100단계 — 참고소설 문체 통계 분석 (로컬·오프라인)

## 목적과 범위

기존 18단계 문서 통계, 21단계 대사·서술 비율 분석을 기준으로, 소설의 **표면적 문체 특성**을 수치화한다. TXT/Markdown/DOCX/PDF 파서에서 생성한 `ParsedReference`를 활용하며, 이 단계에서 새로운 파일 파서를 구현하지 않는다. 별도 로컬 생성 AI 또는 유료 외부 API는 사용하지 않는다.

> 숫자만으로 작가의 문체·의도·장르·서사 품질을 인식했다고 주장하지 않는다. 참고 작품의 표현을 복제하거나 자동으로 집필 프롬프트에 삽입하지 않는다. 실제 생성 시에는 사용자 Novel Bible과 원문 유사성 보호를 우선해야 한다.

## 구현 파일

- `src/ai_novel_factory/references/style_statistics.py`
- `src/ai_novel_factory/references/__init__.py` 공개 API 추가
- `tests/test_style_statistics.py` 신규 테스트 55개
- `docs/stage29_test_results.json` 검증 기록

### 공개 API

```python
from ai_novel_factory.references import (
    analyze_style_text,
    analyze_reference_style,
    parse_text,
)

single = analyze_style_text('첫 문장이었다.\n\n“무슨 일이지?”')
print(single.metrics.sentence_length.mean)

reference = parse_text('1화\n\n이야기가 시작됐다.\n\n2화\n\n“정말?”')
summary = analyze_reference_style(reference)
print(summary.episode_count, summary.total.repetition_ratio)
```

- `analyze_style_text(text, number=1, max_tokens=250000)` → `EpisodeStyle`
- `analyze_reference_style(document, split=None, max_tokens=250000)` → `ReferenceStyle`
- `StyleMetrics`: 문단·문장·띄어쓰기 토큰 수, 공백 제외 글자 수, 길이 요약, 반복 비율, 대사 비율, 문장부호 및 문자 종류 집계
- `LengthSummary`, `PunctuationCounts`, `ScriptCounts`, `EpisodeStyle`, `ReferenceStyle`: 불변(`frozen`) 데이터
- 원문 전체 문자 길이 최대 **2,000,000자**; 통계에서 취급하는 공백 구분 토큰 최대 **250,000개**(설정으로 축소 가능). 상한을 넘으면 원문을 포함하지 않는 `ReferenceParseError` 발생.

## 계산 방식

| 항목 | 정확한 계산 정의 및 한계 |
|---|---|
| 문장 길이 | 18단계의 문장 종결 정규식 `[.!?。！？]+` 및 뒤따르는 닫는 인용부호를 바탕으로 분할. 끝나지 않은 마지막 조각도 1문장으로 계산. 공백 제외 글자 수(문장부호 포함). **자연어 문장 경계 인식이 아닌 휴리스틱**. |
| 문단 길이 | 기존 파서의 빈 줄 구분 문단마다 공백 제외 글자 수. 강제 줄바꿈만으로 문단이 분리되지는 않음. |
| 길이 분포 | 문장/문단 길이 각각 `count`, `minimum`, `maximum`, `mean`, `median`, `p90`, 모집단 표준편차. `p90`은 정렬 후 `ceil(0.9 * n)`번째 값(최근접 순위법). 소수 값은 표시를 위해 두 자리 반올림. |
| 단어 수 | 공백 기준으로 나눈 개수, **한국어 형태소 또는 어절 정제 작업이 아님**. 18단계 통계와 일치. |
| 어휘 다양도 | 각 공백 구분 토큰을 `casefold` 및 **토큰 양쪽의 비단어 문자 제거** 후 빈 값을 제외하고 중복 제거. `type_token_ratio = 서로 다른 정규화 토큰 수 / 정규화 토큰 총수`. 원문/정규화 단어는 결과에 실리지 않음. |
| 반복 비율 | `repeated_token_occurrences = 정규화 토큰 수 - 서로 다른 토큰 수`; `repetition_ratio = 반복 토큰 수 / 정규화 토큰 수`. 문장이 길수록 비율이 변할 수 있어 서로 다른 길이 작품 간 직접 비교 주의. |
| 대사 비율 | 21단계의 균형 잡힌 인용 부호 구간 추정. **실제 발화 비율을 확정하지 않음**. |
| 문장부호 | 마침표, 물음표, 느낌표, 말줄임표(`...` / `…`), 쉼표, 콜론, 세미콜론 별 출현 횟수. `...`는 말줄임표 1개로, 마침표 3개로 이중 집계하지 않음. |
| 문자 구성 | 공백 제외 문자 가운데 한글 완성형/자모, ASCII 영문, Unicode 십진 숫자, 나머지 문자 집계. 확장 라틴 문자 등은 `other`에 포함. |

본문 분석은 **표준 문단과 표 블록만 사용**하며 회차 제목, Markdown 코드 영역을 제외한다. 서문은 작품 전체(`total`)에 포함되지만 개별 회차(`episodes`)에는 포함하지 않는다. 작품 전체 어휘 다양도는 **전체 문단을 합쳐 다시 계산**하며, 각 회차 비율을 단순 평균하지 않는다.

기존 18단계(`measure_reference`), 21단계(`measure_dialogue_reference`) 수치와 회차 번호·문단·문장·공백 제외 글자·토큰·대사 비율을 교차 검증한다. 외부에서 전달된 `SplitEpisodes` 역시 기존 검증을 통해 해당 문서와 일치해야 한다.

## 개인 데이터·원문 보호

- 반환값은 고정 필드명·숫자 외의 인물명, 작품명, 문장, 어휘 목록, 매칭한 실제 문자열을 보유하지 않는다.
- 분석 중 임시로 만든 어휘 `set`은 호출 내부에서만 사용하며, 파일 저장·외부 요청·원격 업로드·로그 출력을 수행하지 않는다.
- 독립 분석 함수는 입력 `str`만 처리한다. 외부 결제·API 인증이나 네트워크가 필요하지 않다.
- 장편 원문을 추출한 직후 다른 모듈의 메모리에 남아 있는지 여부까지 보안적으로 보장하는 기능은 아니며, 메모리 수명 관리와 보안은 후속 통합 검증 대상이다.
- 문체 통계는 작품 표현의 **모사나 직접 복제를 자동 수행하지 않는다**. 원문 유사성 기준/검사는 39·78단계에서 따로 구현해야 한다.

## 검증 명령

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_style_statistics.py' -v
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python scripts/smoke_test.py
```

PowerShell에서는 `$env:PYTHONPATH='src'` 설정 후 Python 3.12를 대상으로 실행 권장.

## 실행한 검증 결과 (2026-10-12)

- Python **3.13.5** 환경에서 신규 55개 테스트 전부 통과.
- 기존 포함 총 **510개**, **507개 통과 / 3개 건너뜀 / 실패 0개**.
- 스모크 검사 필수 항목 통과. Python 요구 버전인 3.12와 다르다는 안내 1건.
- 전체 회귀 테스트 실행 중 **이전 SQLite 연결 미종료 ResourceWarning**이 발생. 이번 단계에서 해결한 것으로 표시하지 않음.
- **실제 Windows 3.12 GUI/EXE 테스트, 실제 작가 문체의 품질 평가, 로컬 LLM 의미적 문체 추론은 아직 미완료**.
- 현재 대화 전용 개발: GitHub 조회/업로드/커밋/병합, 예약 자동화, 외부 AI API 사용 없음.

**다음 단계:** 30/100 — `Reference Profile` 저장 및 표시. 개인 원문을 직접 저장하지 않는 정량 프로필 구조를 기본으로 설계.
