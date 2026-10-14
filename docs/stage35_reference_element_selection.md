# AI Novel Factory 35/100 — 참고 요소 선택 (오프라인)

## 목적

장르별로 이미 계산된 **여러 참고작의 통계적 관찰값** 중 사용자가 원하는 항목만 골라 저장한다. 참고작의 문장, 대사, 고유 플롯, 인물명, 작가 문체를 추출·복제하거나 생성 모델에 전달하지 않는다. 이 단계는 **선택 레시피의 저장·조회**까지 구현한다. AI Writer 연동과 유사성 검사는 후속 단계다.

## 선택 가능한 요소 (고정 6종)

| 내부 키 | 한글 명칭 | 의미 |
|---|---|---|
| `dialogue_ratio` | 대사 비율 | 따옴표 기반 대사 후보 문자 비중 |
| `sentence_characters` | 평균 문장 길이 | 공백을 제외한 문장 길이 통계 |
| `lexical_diversity` | 어휘 다양도 | 공백 분할 기반 통계로 형태소 분석 아님 |
| `emotion_balance` | 감정 어휘 균형 | 고정 어휘사전 기반 근삿값 |
| `cliffhanger_episode_rate` | 회차 말미 단서 비율 | 클리프행어 확정이 아닌 말미 단서의 빈도 |
| `event_cue_density_per_1000` | 1,000자당 사건 어휘 | 사건이 확정되지 않은 어휘 단서 밀도 |

사용자는 항목 **1~6개**를 직접 선택한다. 미지의 항목, 사용자 지정 문장·프롬프트, 중복 항목, 원문 복제 요청을 입력으로 받지 않는다. 선택값은 기존 통계의 관찰치일 뿐 집필에 강제할 목표치가 아니다.

## 저장 및 재검증

- `src/ai_novel_factory/references/element_selection.py`: 고정 항목 화이트리스트, 정렬·중복 거부, `PatternStrengthPreview` 안전 검증, 안전한 숫자 보고서.
- `src/ai_novel_factory/database/element_selections.py`: 기존 `ReferenceCatalog` SQLite 연결에 테이블 `reference_element_selections` 추가. `genre`, `weighting`, 정렬된 항목 코드 JSON, UTC 변경시각만 저장. **원문/원고/파일 경로/작가명/인물명/검색 문장은 저장하지 않는다.**
- 저장하거나 불러올 때마다 장르 레시피 최신 여부와 34단계 강도 적용 상태를 다시 계산한다. 참여 참고작 2개 미만이거나 하나의 실효 비중이 60%를 초과하면 선택 불가다. 저장 설정은 보존되지만 `get()`은 막고 목록에는 "재구축·강도 재설정 필요"로 표시한다.
- 장르 구성이 바뀌거나 참고 프로필이 삭제되면 옛 선택을 조용히 재사용하지 않는다. 강도 설정을 정상으로 되돌리면 다시 조회 가능하다.
- `elements-delete`는 선택 설정만 제거하고 30단계 프로필, 32단계 장르 분류, 34단계 강도 설정을 유지한다.
- UI: 참고작 화면에 고정 항목 6개 목록과 `참고 요소 저장` / `저장한 요소 보기` / `요소 선택 초기화`를 추가했다. 로컬 PySide6가 설치된 실행 환경에서만 화면이 활성화되며, 이 작업 환경에서는 직접 GUI 실행을 검증하지 못했다.

## 개발환경 CLI 예시

먼저 `import`, `genre-assign`, `genre-build`를 사용해 한 장르에 참고작 2~50개의 정상적인 익명 통계 프로필을 구성한다.

```powershell
$env:PYTHONPATH = 'src'
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 elements-save fantasy dialogue_ratio emotion_balance
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 elements-show fantasy
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 elements-list
python -m ai_novel_factory.references.profile_cli --database .\references.sqlite3 elements-delete fantasy
```

`--weighting characters`는 `elements-save` 또는 `elements-show` 등의 명령 뒤에 지정하며, 해당 가중치 장르 패턴을 앞서 별도로 구축해야 한다. 명령은 외부 서비스가 필요하지 않고 사용자가 선택한 로컬 SQLite 파일만 다룬다.

## 검증 및 알려진 한계

- `tests/test_element_selection.py`: 중복·경계 입력, 올바른 선택, 재시작 후 재조회, 두 가중치의 분리, 장르 변경·프로필 삭제·강도 편중에 따른 재검증, DB 손상·SQL 악성 텍스트 입력 거부, 원문 비노출, 네트워크 차단 상태, CLI, 선택적 PySide6 위젯 테스트.
- `docs/stage35_test_results.json`에 실제 통과 결과 기록. 개발 환경 Python 3.13이며 배포 요구 사항은 Python 3.12. PySide6 GUI는 이 환경에 없어 테스트를 건너뛰었다.
- 로컬 AI가 원고를 쓰거나 선택 통계값을 집필 계획에 연결하는 기능은 아직 없다. 인터넷 없는 Windows EXE 자체 빌드는 아직 진행하지 않았다.
- **GitHub, 원격 DB, Redis 서버, 유료 AI 서비스 또는 클라우드 API와 연동하지 않는다.**

다음: **36/100 — 관련 패턴 검색**. 선택된 안전한 통계 항목에 대해 PC 내부 저장 프로필 검색을 확대하되 원문 인용·작가 모방을 금지한다.
