# 23단계 — 주요 사건 시점 후보 분석

22단계 고정 어휘 4개 범주(갈등·진행·보상·반전)의 **출현 위치**를 측정합니다.
이는 단어 위치 히스토그램이며 실제 주요 사건을 의미적으로 감지하거나 중요도를 평가하지 않습니다.

## 분석 결과

- `analyze_event_timing_text(text, number=1, max_markers=20000)` — 회차 내 후보 위치
- `analyze_reference_event_timing(document, split=None, max_markers=20000)` — 회차별 결과
- 문단 번호(1 기반), 공백 제외 글자 오프셋(0 기반), 회차 내 상대 백분율과 5분위, 범주별 횟수
- 다섯 구간에서 후보가 가장 많은 구간은 단독 1위일 때만 산출하고, 동률이면 미정(`None`)
- 회차·서문·Markdown 코드 펜스 경계와 22단계 어휘 횟수를 교차 검증합니다.
- 전체 참고작 후보 수 상한은 20,000입니다. 상한 초과 시 결과를 자르지 않고 오류 반환.

## 비복제 및 해석상의 주의

원문이나 일치한 단어·문장, 파일명, 전체 경로를 반환·DB 기록·외부 전송하지 않습니다.
기존 22단계와 동일한 정확 일치 정규식으로 후보를 수집하며 한국어 어미 변형은 놓칠 수 있습니다.
따옴표 안의 인용도 포함될 수 있으므로 이 데이터를 실제 주요 사건 시점으로 간주하면 안 됩니다.
새 작품을 쓸 때는 Novel Bible이 우선이며 참고작 원문 복제를 허용하지 않습니다.

## 테스트 명령

    PYTHONPATH=src python -m unittest tests.test_event_timing -v
    PYTHONPATH=src python -m unittest discover -s tests -v
    PYTHONPATH=src python scripts/smoke_test.py

Windows 실기기 EXE 및 로컬 AI의 의미분석 품질은 아직 검증하지 않았습니다.
다음 단계(24)는 후보 출현 간격·분포 지표 분석입니다.
