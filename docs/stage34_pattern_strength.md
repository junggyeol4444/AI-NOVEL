# 34/100 — 참고 작품별 패턴 강도 설정 (완전 로컬)

## 목적 및 동작 원칙

33단계의 장르별 Reference Pattern Library에 **참고 작품별 정수 강도(0~100)**를 사용자가 지정하고, 이것이 기존 통계 관찰값의 상대 비중에 어떻게 반영되는지 **미리보기**를 추가한다. 아직 소설 생성/Writer 에이전트가 없으므로 **이 값으로 소설을 쓰거나 특정 작가의 표현을 복제하는 기능은 구현하지 않는다.**

- 미설정 기본값은 `50`이며, 명시적으로 `0`을 설정하면 해당 작품은 *강도 미리보기에서만* 제외된다. 원본 파일, 참고작 프로필, 장르 분류, 기존 통계는 삭제되거나 변경되지 않는다.
- `equal`: 기준 가중치가 작품당 1이다. 최종 상대 가중치는 `강도 × 1`이다.
- `characters`: 기준 가중치가 작품의 본문 공백 제외 글자 수이다. 최종 상대 가중치는 `강도 × 글자 수`이다. 전체 작품의 글자 수가 0이면 단계31의 규칙에 맞춰 작품당 1로 대체한다.
- 미리보기 실효 비중은 각 작품의 계산된 가중치를 총합으로 나눈 백분율이다. 수치를 **몰래 자동 수정하지 않으며**, 사용자 설정을 그대로 사용해 계산한다.
- 적어도 2개 작품이 실효 가중치 양수여야 하며, **한 참고 작품이 60%를 초과**하면 결과를 `선택 불가`로 명시한다. 0개는 `empty`, 1개는 `fewer_than_two`, 편중은 `over_concentrated`, 안전 기준 충족은 `ready`로 구분한다. 이것은 후속 패턴 선택 단계에 적용할 검토 정책이며, 현재 단계에는 자동 Writer 연결이 없다.
- 결과는 기존 6개 수치형 특징의 **가중 평균**과 익명 UUID·설정값·실효 비중만 포함한다. 원문, 발화, 인물명, 작가명, 원본 파일 경로/이름을 결과·새 DB 테이블·보고서에 저장하지 않는다.
- 장르 패턴은 사전에 32단계 `genre-build`로 저장돼 있어야 한다. 이후 작품 구성원이 변경됐다면 재구축할 때까지 **미리보기 불가**다. 강도 수정은 장르 레시피를 변경하지 않으며, 미리보기는 요청 시 최신 강도를 즉시 사용한다.

## 주요 구현 파일

- `src/ai_novel_factory/database/pattern_strengths.py`: 기존 로컬 `ReferenceCatalog` 연결을 재사용하는 `PatternStrengthStore`; `(reference_id, strength)` 정수만 가진 `reference_pattern_strengths` SQLite 테이블. FK는 `reference_profiles`에 연결해 프로필 삭제 시 강도 설정도 제거한다. 0~100 검증을 Python과 SQLite CHECK 양쪽에서 강제한다.
- `src/ai_novel_factory/references/pattern_strength.py`: `preview_strengths()`와 `render_strength_preview()`; 기존 패턴 상태 점검, 동일 작품 겹침 방지, 강도 계산 및 한 작품 편중 경고. 글쓰기용 프롬프트·본문 생성 API는 **포함하지 않음**.
- `src/ai_novel_factory/references/profile_cli.py`: 강도 저장·조회·초기화·설정 목록·장르 미리보기 명령.
- `src/ai_novel_factory/desktop/reference_profile_browser.py`: PySide6 참고작 화면에 정수 선택 위젯·강도 저장·장르 강도 미리보기 버튼 추가. 선택한 프로필의 현재 설정값을 표시한다. UI 생성 시 네트워크 호출 없음.
- `tests/test_pattern_strength.py`: 저장·삭제·경계·편중·분석 결과의 원문 비포함·오프라인·CLI·선택적 GUI 테스트.

## 사용법 (Windows PowerShell, Python 개발 환경)

먼저 참고작 2~50개를 가져와 프로필을 만들고, 같은 장르로 지정하여 `genre-build`를 수행해야 한다. 아래의 실제 UUID는 `list` 명령에서 얻는다.

```powershell
$env:PYTHONPATH = 'src'
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 strength-show <참고작_UUID>
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 strength-set <참고작_UUID> 75
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 strength-list
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 strength-preview fantasy
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 strength-preview fantasy --weighting characters
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 strength-reset <참고작_UUID>
```

`strength-list`는 기본값 50인 미설정 작품을 표시하지 않는다. `strength-reset`은 명시 설정만 삭제한다. `strength-preview`는 DB에 아무것도 기록하지 않는다.

## 실제 테스트 및 남은 작업

- 32·33단계 이전 통계/원문 보호 정책을 변경하지 않았다.
- 개발 환경 Python 3.13.5, PySide6 부재. Windows GUI 실기기나 EXE는 아직 검증하지 않았다.
- 상세 검증 요약은 `docs/stage34_test_results.json` 참고. 원래의 33단계 `unittest` 테스트도 누적 실행한다.
- 외부 서버·GitHub·클라우드 AI 서비스에 접근하지 않았다. 이번 단계 구현은 표준 라이브러리 SQLite·Python만으로 동작한다.
- **다음 단계 35/100:** 실제 창작 계획에 참조 패턴을 선택해 쓰는 경우, `usable_for_selection` 검사 및 내용 비복제 정책을 반드시 시행해야 한다. 현재 수치형 미리보기만 있고 Writer 연동은 아직 없다.
