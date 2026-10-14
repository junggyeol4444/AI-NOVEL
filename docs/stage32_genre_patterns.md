# 32/100 — Genre Pattern 구축 (완전 로컬)

## 기능 정의

32단계는 30~31단계에서 만든 **원문이 없는 Reference Profile**을 활용해, 사용자가 **직접 분류한** 장르별 통계적 공통점과 작품 간 차이를 계산한다. 장르 예측 모델이 아니며, 소설 원문이나 특정 작가의 문체를 복제하는 학습 파이프라인이 아니다.

**모든 작업은 Windows PC 안의 Python 프로세스 및 로컬 SQLite 파일에서 이루어지도록 설계했다.** GitHub, 웹 서버, 외부 AI API, 사용자 PC 밖의 DB를 사용하지 않는다.

## 구현 파일

- `src/ai_novel_factory/references/genre_patterns.py` — 장르 패턴 데이터 모델·통계·한글 보고서. 기존 31단계 집계 계약을 재사용.
- `src/ai_novel_factory/database/genre_patterns.py` — 로컬 SQLite에서 직접 지정한 장르와 선택된 참고작 ID 집합을 관리.
- `src/ai_novel_factory/references/profile_cli.py` — 장르 지정·조회·구축·저장·삭제 명령.
- `src/ai_novel_factory/desktop/reference_profile_browser.py` — 장르 콤보박스, 선택 프로필의 장르 지정 버튼, 구축·조회 버튼.
- `tests/test_genre_patterns.py` — 52개 테스트(이 환경에서 PySide6 GUI 테스트 1개 미실행).

## 데이터와 통계

- 장르 코드: `fantasy`, `romance`, `mystery`, `thriller`, `science_fiction`, `historical`, `martial_arts`, `horror`, `contemporary`, `drama`, `comedy`, `other`.
- 각 참고작은 한 번에 **하나의 대표 장르**로 분류한다. 혼합 장르 태그 지원은 아직 없다.
- 같은 장르에 **서로 다른 분석 프로필 2~50개**가 있어야 패턴 구축이 가능하다. 한 작품으로 장르의 공통점을 단정하지 않는다.
- `equal`은 각 참고작을 동일 가중치로, `characters`는 작품 본문 글자 수로 가중치를 준다.
- 수치: 작품별 대사 비율, 평균 문장 길이, 어휘 다양도, 감정 어휘 균형, 회차 말미 단서 비율, 사건 어휘 밀도의 최솟값·최댓값·평균·표준편차. `평균±1 표준편차`를 물리적으로 가능한 범위로 제한하여 **관찰 참고 구간**을 제공한다. 이는 권장 창작 목표값이 아니다.
- 상대적 회차 위치에 따른 5구간 곡선과 말미 단서 유형별 건수는 기존 31단계 통계에 포함된다.
- 작은 표본과 장르를 사람이 임의 선택한 데 따른 표본 편향, 어휘 기반 탐지의 오인식 가능성을 보고서에 명시한다.
- **작품별 사건 어휘 밀도 평균**과 **전체 작품 문자를 합친 밀도**는 다르므로 별도 계산·표기한다.

## 저장 및 신선도

SQLite 데이터베이스에 `reference_genres(reference_id, genre)`, `genre_pattern_selections(genre, weighting, reference_ids_json, updated_at)` 두 테이블을 추가한다. 선정 정보는 **UUID만 포함한 JSON 배열**이다. 실제 통계값은 필요할 때 원문 없는 프로필을 다시 계산한다. 따라서 프로필 수치가 바뀌어도 갱신된 결과가 표시된다.

**선정한 작품 구성이나 장르 지정이 바뀌면 기존 저장 선택은 거부하고 다시 구축하도록 안내**한다. 원문, 파일 전체 경로, 작가의 고유 표현이나 이름을 이 두 테이블에 저장하지 않는다. 참고작의 파일명은 기존 메타데이터 목록에 보관되지만 장르 패턴 테이블에는 기록되지 않는다.

한 장르에 50개가 넘는 참고작을 지정했을 때는 전체 집계를 임의로 잘라내지 않고 오류를 반환한다. 여러 장르 구분과 50개 초과 풀링은 향후 확장 대상이다.

## 로컬 CLI 예제

프로젝트 루트에서 다음 명령을 실행한다. Windows PowerShell에서는 `$env:PYTHONPATH='src'`를 먼저 설정한다.

```powershell
$env:PYTHONPATH='src'
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 import .\sample1.txt
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 import .\sample2.txt
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 list
# list에서 나온 서로 다른 참고작 ID를 각각 지정
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 genre-assign <첫번째ID> fantasy
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 genre-assign <두번째ID> fantasy
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 genre-build fantasy
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 genre-show fantasy
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 genre-list
python -m ai_novel_factory.references.profile_cli --database .\my_reference.sqlite3 genre-tags --genre fantasy
```

`genre-build fantasy --weighting characters`로 글자 수 가중치를 선택할 수 있다. 이를 표시하려면 `genre-show fantasy --weighting characters`를 사용한다. `genre-unassign <ID>`는 특정 참고작의 장르 지정을 해제하고, `genre-delete fantasy`는 장르 패턴의 저장 선택만 삭제한다. 원문, 참고작 프로필 또는 참고작 메타데이터는 삭제되지 않는다.

GUI에서는 **프로필 목록에서 작품 선택 → 장르 선택 → '선택한 작품에 장르 지정' → '이 장르 패턴 구축'** 순으로 사용한다. 실제 Windows GUI 구동 검증은 별도 과제다.

## 안전성·테스트

- SQL 값은 파라미터로 전달하며, 장르 코드는 코드에 내장한 열거형에 한정한다. DB CHECK 제약도 추가했다.
- 사용자가 지정한 ID는 소문자 32자리 UUID 형식을 검사한다. 부적절한 데이터 또는 원문 복제 문자열이 들어갈 여지를 차단한다.
- 원문을 삭제해도 SQLite 프로필과 장르 분류가 남아 있다면 기존 장르 패턴은 재구축 가능하다.
- 오프라인 검증 테스트에서는 소켓 연결을 강제로 차단한다.
- 31단계에서 남은 구식 테스트 2개의 SQLite 연결 미종료를 명시적 `closing()` 처리로 수정했다. 외부 DB 사용과는 무관하다.
- 이 개발 환경은 Python 3.13이어서 선언된 Python 3.12 / Windows EXE·GUI 실기기 확인이 **미완료**다.

## 명령

```bash
PYTHONPATH=src python -m unittest tests.test_genre_patterns -q
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python scripts/smoke_test.py
PYTHONPATH=src python scripts/check_dependencies.py
```

다음 단계(33/100) Reference Pattern Library에서는 복수의 Pattern을 검색·선택·비교하는 읽기 전용 라이브러리를 구성한다.
