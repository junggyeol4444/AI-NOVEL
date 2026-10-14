# 31/100단계 — 복수 참고작 Reference Profile 통합 분석

## 목적과 범위

30단계의 **로컬 SQLite**에 저장한 두 작품 이상(최대 50개)의 텍스트 없는 `ReferenceProfile`을
불러와 비교한다. 소설 원문을 다시 읽지 않으며, 원문·제목·파일명·인물명·대사·표현을
통합 결과에 포함하지 않는다. 원본 소설의 표현을 생성 프롬프트에 복제하지 않는다.
이 결과는 **규칙 기반 통계**이며 서사적 유사성/의미 분석 또는 작가 스타일 복제 모델이 아니다.

## 구현

- `references/profile_collection.py`: 순수 Python, 네트워크·AI 호출·DB 쓰기 없음.
  - `combine_reference_profiles(profiles, weighting='equal')`: 검증된 2~50개 프로필의 평균·분산·글자 수·단서 밀도·말미 단서 유형 집계.
  - `combine_saved_profiles(store, reference_ids, ...)`: 사용자가 지정한 **서로 다른** ID로 로컬 SQLite에서 검증된 프로필을 읽음. 중복·없는 ID·손상된 JSON·악성 입력 거부. 임의 다른 프로필로 대체하지 않음.
  - `render_profile_collection`: 이름 없는 숫자·고정 분류만 화면/CLI에 출력.
- 명령줄: `profile_cli.py compare ID1 ID2 [ID3 ...] [--weighting equal|characters]`.
- 선택형 PySide6 화면: 프로필 목록에서 2~50개를 다중 선택하고 **선택한 작품들 통합 비교** 버튼 클릭.
- 통합 결과는 프로그램 메모리에만 존재하며 DB 테이블/원고/모델 프롬프트에 **저장되지 않는다**.

## 집계 방식의 의미

1. `equal`(기본): 참고작마다 한 표. 작품별 대사 비율·평균 문장 길이·어휘 다양도·감정 균형·말미 후보 회차 비율을 **참고작 수**로 동일 가중 평균.
2. `characters`: 작품별 **공백 제외 글자 수**를 가중치로 위 수치의 평균과 표준편차 계산. 모든 참고작이 0자라면 가중치가 0이므로 동일 가중치로 대체하고 결과에 표시. 글자 수 0인 작품은 다른 작품의 수치 가중 평균에 영향을 주지 않음.
3. 모든 집계 방식에서 **사건 단서 밀도 = 전체 사건 후보 수 × 1,000 / 전체 작품 본문 글자 수**. 이는 작품별 단서 밀도의 산술 평균과 다를 수 있음.
4. 5구간 곡선: 각 작품의 회차를 상대적 위치에 매핑. 각 구간에서 한 작품의 회차별 통계를 먼저 평균해 **동일 가중 방식에서 장편 작품이 과대표되지 않도록** 함. 기여 작품 수·회차 수를 함께 표시. 비어 있는 구간은 0으로 표시하되 기여 수 0으로 식별.
5. 말미 단서 유형: 후보 여부를 의미 분석하지 않고 기존 25/30단계 분류를 단순 합산. 총량은 전체 회차 수와 같음.
6. 어휘 다양도: **각 작품에서 측정한 다양도의 평균**이며 원문을 합친 전체 어휘 다양도가 아님.
7. 최솟값·최댓값은 모든 비교 작품을 포함(가중치 0인 작품 포함), 표준편차는 작품별 가중치 기반 모집단 편차.

## 사용 예시 — 네트워크 연결 불필요

```bash
# 이 PC에서만 실행. 기준 프로젝트 폴더에서 PYTHONPATH=src 설정 필요
PYTHONPATH=src python -m ai_novel_factory.references.profile_cli --database ./local.sqlite3 import novel1.txt
PYTHONPATH=src python -m ai_novel_factory.references.profile_cli --database ./local.sqlite3 import novel2.txt
PYTHONPATH=src python -m ai_novel_factory.references.profile_cli --database ./local.sqlite3 list
PYTHONPATH=src python -m ai_novel_factory.references.profile_cli --database ./local.sqlite3 compare 첫번째_ID 두번째_ID
PYTHONPATH=src python -m ai_novel_factory.references.profile_cli --database ./local.sqlite3 compare 첫번째_ID 두번째_ID --weighting characters
```

Windows PowerShell에서는 `PYTHONPATH=src` 대신 `$env:PYTHONPATH='src'`를 사용한다.

## 보안 및 제한

- 외부 서버, GitHub, 클라우드 AI API, 임의 온라인 저장소 **필요 없음**.
- 원본이 사라져도 이미 저장된 프로필의 통합 비교 가능(로컬 DB는 남아 있어야 함).
- 프로필 버전 1만 지원. 50개 초과는 제한; 선정한 2~50개 범위가 전체 참고작을 대표하는지는 사용자가 판단해야 함.
- 초기 코드는 텍스트 기반 단서 후보와 통계 지표만 사용. 실제 캐릭터 관계, 서사 의미 및 복선 해석 불가.
- 구형 5단계 `pyproject.toml`에는 미사용 PostgreSQL·Redis/Celery 선택 의존성 목록이 남아 있으나 이번 엔진은 이를 설치하거나 연결하지 않음. 실제 런타임은 SQLite와 로컬 함수만 사용하며 `settings.py`가 외부 서비스 설정을 거부함. 오래된 설치 문서는 이후 오프라인 전용으로 추가 정리 필요.
- Qt GUI가 없는 개발 환경에서는 GUI 테스트 건너뜀. Windows/Python 3.12/EXE 실제 실행 검증은 아직 없음.

## 테스트

`PYTHONPATH=src python -m unittest tests.test_profile_collection -v`

`PYTHONPATH=src python -m unittest discover -s tests -q`

`PYTHONPATH=src python scripts/smoke_test.py`

테스트는 통계 공식, 가중치, 제로 글자 예외, 상한, 5구간, 원문 누출 방지, DB 읽기 전용,
DB 재시작, 중복/손상 프로필, 네트워크 차단, CLI 비교를 포함한다.
