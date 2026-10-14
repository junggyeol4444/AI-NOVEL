# 39/100단계 — 로컬 유사성 검사 기준선 (2026-10-12)

## 구현 범위

- 새 분석 엔진: `src/ai_novel_factory/references/similarity_baseline.py`
- 로컬 CLI: `src/ai_novel_factory/references/similarity_cli.py`
- 자동 테스트: `tests/test_similarity_baseline.py`
- 기존 38단계 **원문 연속 일치 보호 게이트**를 검사 전에 실행한다. `blocked`는 그대로 차단, `review`는 검토 대상으로 유지한다.
- 이 단계에서 문단(빈 줄 기준, 파일 파서에서 읽은 Markdown의 헤더/코드 제외)을 NFKC·casefold 후 공백/구두점을 제거하여 **연속 5문자 shingle 집합**으로 표현한다. 참고 원문은 검사 중 메모리에서만 처리한다.
- Jaccard `교집합 크기 / 합집합 크기`가 **0.70 이상**이거나, 원고 문단 shingle 포함률이 **0.80 이상**이면서 Jaccard도 **0.40 이상**이면 `review` 후보로 표시한다. 문단 24자(정규화 후) 미만은 단독 비교에 사용하지 않는다.
- 참고 원문과 검사 원고가 없거나 비교 가능한 문단이 없으면 **`inconclusive`**이며 자동 사용을 허용하지 않는다. 체크 한도를 넘을 경우 예외로 실패를 반환하여 **`clear`로 취급하지 않는다**.
- 결과에는 일치 문장·n-gram·고유 텍스트·파일명·경로·인물명이 일절 없고, 참고 입력 순번, 문단 순번, 유사도 수치만 포함된다. 결과 자체도 파일/DB에 저장하지 않는다.

## 판정과 제한

| 결과 | 의미 | 자동 사용 게이트 |
|---|---|---|
| `blocked` | 38단계 보호 규칙으로 96자 이상 긴 직접 일치 | 차단 |
| `review` | 38단계 검토 대상이거나 39단계 문단 유사성 기준 초과 | 차단, 사용자 검토 |
| `inconclusive` | 유효한 비교 문단 없음 | 차단 |
| `clear` | **제공한** 참고작에 대해 위 검사 기준선 미탐지 | 현재 게이트 통과, 독창성/저작권 안전 보장 아님 |

한국어 형태소 분석이나 문장 의미 기반 평가가 **아니며**, 의역·번역·원문 재배열·창작 설정 복제를 탐지하지 못할 수 있다. 흔한 어구/반복 표현으로 거짓 양성도 생길 수 있다. 임계치는 내부 개발용 초깃값으로, 실제 저작권상 안전 기준이나 법적 판정이 아니다.

## 사용 방법 (인터넷 불필요)

```powershell
$env:PYTHONPATH = "src"
python -m ai_novel_factory.references.similarity_cli --draft "C:\\my_work\\draft.txt" --reference "C:\\my_reference\\novel1.txt" "C:\\my_reference\\novel2.docx"
```

TXT / Markdown / DOCX / 텍스트 추출 가능한 PDF 지원. EPUB은 기존 누적본의 파서가 아직 없으므로 거부한다. 반환 코드: **0=`clear`**, **1=`review`/`blocked`/`inconclusive`**, **2=입력 오류 또는 검사 불가**. 경로·원문은 오류 출력에 나타나지 않는다.

사용자가 소유/열람 권한을 가진 원문을 실행 시 직접 선택해야 한다. **통계 Reference Profile만으로는 원문 유사성 검사가 불가능하다.** 참조 파일을 저장하거나 외부 서비스에 전송하지 않는다.

## 검증과 이후 작업

- `PYTHONPATH=src python -m unittest discover -s tests -q`
- `PYTHONPATH=src python scripts/smoke_test.py`
- `python scripts/check_dependencies.py`
- `python -m compileall -q src tests`

이 단계는 **국소 검사 기준선**을 만드는 것으로, 61단계 이후 로컬 Writer의 실제 생성 출력에 게이트를 연결하고 의미 유사성 검사까지 완성한 것은 아니다. 향후 Novel Bible, 출판 승인과 연결해야 한다.

실제 Windows EXE/GUI/Python 3.12 테스트는 여전히 미수행. GitHub, 네트워크 서버, 클라우드 AI API 호출 없음.
