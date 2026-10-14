# 24단계 — 전개 속도·사건 후보 간격 분석

## 목표

23단계의 회차별 **키워드 사건 후보** 출현 위치에서, 각 회차의 분포 밀도와 후보 간 간격을 수치화한다.
**의미를 이해한 사건 탐지, 실제 전개 속도 또는 독자 체감 리듬의 평가가 아니다.**

## 구현 및 공개 API

- `src/ai_novel_factory/references/event_pacing.py`
- `analyze_pacing_text(text, *, number=1, max_markers=MAX_EVENT_MARKERS)`
- `analyze_reference_pacing(document, *, split=None, timing=None, max_markers=MAX_EVENT_MARKERS)`
- `GapMetrics`, `EpisodePacing`, `ReferencePacing` 불변 레코드
- `tests/test_event_pacing.py` 신규 자동 테스트

한 회차의 글자 수는 공백 제외 문자 수이고 회차 제목 및 코드 블록은 제외한다. 참고작의 서문도 전체 회차 밀도에서 제외한다.

### 지표의 정확한 정의

- **밀도**: `(키워드 후보 출현 개수 / 공백 제외 문자 수) × 1,000` (문자가 없으면 0)
- **후보 간 간격**: 시간이나 문단이 아닌 인접 후보 **시작 위치** 간 공백 제외 문자 수 차이. 후보가 0개나 1개이면 평균/중앙값/최솟값/최댓값은 `None`.
- **간격 표준편차**: 모집단 표준편차. 변동계수는 `표준편차 / 평균`, 평균이 0이면 정의되지 않아 `None`.
- **최장 시작 위치 구간**: 0, 후보 시작 위치들, 전체 글자 수 경계 간 최장 거리. 키워드 길이는 제외하지 않으므로 ‘실제 사건 없는 글자 길이’라는 뜻은 아니다.
- **5구간 밀도**: 23단계와 동일하게 `offset*5//total`로 구간을 배정하고, 각 구간의 실제 공백 제외 문자 용량으로 나누어 밀도를 계산한다. 5자 미만의 짧은 본문도 0으로 나누지 않는다.
- **작품 전체 밀도**: 회차별 비율의 산술 평균이 아니라 `전체 후보 수 / 전체 회차 본문 글자 수 × 1,000`.
- **작품 평균 간격**: 회차 **내부** 후보 간 거리의 전체 합계 / 회차 내부 간격 개수. 회차 간 이동은 간격에 포함하지 않는다.
- 모든 실수형 보고 값은 소수 둘째 자리(변동계수는 넷째 자리) 반올림한다.

## 보안·유의사항

숫자와 고정된 유형만 반환한다. 원문 텍스트, 인용 구절, 파일 경로는 데이터 객체에 남기거나 네트워크/DB로 전송하지 않는다. 23단계 시점 결과가 주어지면 원문에서 재계산한 결과와 동등한지 검사해 오래된 입력을 거부한다. 계산할 수 없는 실제 의미적 리듬을 단정하지 않는다. AI 모델 호출이나 외부 유료 API는 사용하지 않는다.

## 실행 명령

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_event_pacing.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/smoke_test.py
```

## 보류

Windows PySide6 GUI 및 로컬 모델을 통한 의미 기반 사건 확인은 아직 구현·검증하지 않았다. 참고소설 유사성·원문 비복제 보호 및 수동 출판 승인은 향후 단계의 별도 과제다.
