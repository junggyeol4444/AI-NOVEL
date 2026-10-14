# 23단계 — 주요 사건 시점 **후보** 분석

## 목적 및 범위

22단계에서 사용한 고정 키워드 4범주(갈등·진행·해결/보상·반전)가 **어느 시점에 출현하는지**를 계산합니다. 이는 위치 기반 정량 지표이며 **줄거리상 주요 사건을 발견하거나 중요도를 검증하는 의미 분석이 아닙니다**. 단어가 등장해도 실제 사건이 아닐 수 있고, 핵심 사건에 해당 단어가 없어도 놓칠 수 있습니다. 이후 로컬 AI를 통한 사건 의미분석 단계에서 검증할 후보 정보로만 활용합니다.

## 구현

- `src/ai_novel_factory/references/event_timing.py`
  - `analyze_event_timing_text(text, number=1, max_markers=20000)` — 단일 회차 후보 분석
  - `analyze_reference_event_timing(document, split=None, max_markers=20000)` — 17·22단계 연계, 회차별 분석
- `EventCuePosition`: 고정 범주, 회차 내 문단 번호(1 기반), 공백 제외 글자 오프셋(0 기반), 회차 내 위치 백분율(0~100 미만), 5분위 구간(1~5)
- `EpisodeEventTiming`: 회차 총 글자 수·문단 수·후보 수·4범주 빈도·5분위별 분포·단독 최다 구간. 5분위 최다 구간이 동률 또는 후보가 없으면 `peak_quintile=None`
- `ReferenceEventTiming`: 회차별 결과, 합계, 각 회차의 상대 5분위 합계
- 최대 후보 개수 제한은 전체 참고 작품에 적용됩니다. 설정 초과 시 결과를 잘라내지 않고 안전하게 오류로 반환합니다.

## 분석 규칙 / 개인정보 보호

1. `ParsedReference`와 17단계 `SplitEpisodes`를 사용하고, 22단계 구조 통계와 총 글자·문단·범주별 출현 횟수를 대조합니다.
2. 서문·회차 제목·Markdown 코드 펜스는 후보 위치 계산에서 제외됩니다. 본문 및 표 블록만 처리합니다.
3. 위치는 **공백 제외 글자** 기준입니다. `position_percent = round(100 * preceding_visible_characters / episode_visible_characters, 2)`이고, 길이가 0이면 후보도 없습니다.
4. 어휘는 기존 22단계 `_PATTERNS`와 동일합니다. 한국어 어미 변화(`성공했다` 등)나 따옴표 내부 인용을 정밀하게 구분하지 못합니다.
5. 반환 데이터에는 원문, 인용문, 일치한 구체적인 단어, 제목, PC 경로, API 키를 담지 않습니다. 원문 복제·외부 전송·DB 저장·AI 호출은 수행하지 않습니다.
6. 추후 장편 집필의 **Novel Bible** 내용이 참고소설의 이러한 정량 지표보다 우선합니다. 참고소설 표현을 새 작품에 재사용하는 용도로 사용하지 않습니다.

## 실행·검증

```powershell
$env:PYTHONPATH = 'src'
python -m unittest tests.test_event_timing -v
python -m unittest discover -s tests -v
python scripts/smoke_test.py
```

테스트는 위치 계산/정렬/문단 오프셋/최다 구간 동률/회차 경계/서문/코드 제외/잘못된 입력/후보 개수 제한/21·22단계 수치 일치/원문 미노출 등을 포함합니다. 이는 Windows PC EXE 실행, EPUB 파서 통합, 의미분석 정확도 검증을 뜻하지 않습니다.

## 다음 단계

24단계: 사건 후보 출현 간격과 전개 속도의 정량 지표. 의미적 중요도·사건 발생 확정 여부는 계속 별도 검증해야 합니다.
