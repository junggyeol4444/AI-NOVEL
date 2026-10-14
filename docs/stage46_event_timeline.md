# 46/100단계 — 주요 사건의 날짜·상대시간 및 선후관계 검사 (ANF-REQ-036)

## 요구사항 및 실제 범위

`docs/requirements.md`의 **ANF-REQ-036**: 주요 사건의 날짜·상대시간을 관리한다. **인수 기준: 상충되는 사건 순서를 검출한다.**

- `event_timeline.py`: Novel Bible과 같은 **오프라인 로컬 SQLite** 파일에 `bible_timeline_events`(작품별 사건)와 `bible_timeline_order`(명시적 선후관계)를 저장한다. 사건은 사용자가 명시적으로 작성한다. 참고작의 원문을 자동 수집하지 않는다.
- `event_id`는 자동 생성 UUID 32자리, 제목은 1~120자. 사건 시간은 (a) `YYYY-MM-DD`의 날짜만 지정, (b) 시간대가 있는 ISO 8601 날짜시간, (c) 기준 사건 ID와 **정수 분 단위** 상대 오프셋, (d) 미정 중 하나이다. 절대시간과 상대시간 동시 지정은 거부한다. 날짜만 지정하면 **그날의 24시간 구간**으로 취급하고 임의의 자정 발생으로 확정하지 않는다. 날짜시간은 UTC로 정규화한다. 상대 오프셋의 절댓값은 525,600,000분 이하여야 한다.
- 사건 생성/수정/삭제, 작품별 목록·단일 조회, 선후관계 추가·삭제, 전체 `audit`를 지원한다. 선후관계는 `A < B`라는 **엄격한** 시간순이다. 상대 오프셋이 양수면 기준 사건이 먼저, 음수면 파생 사건이 먼저이다. 0분은 동시 발생을 의미한다.
- **검출**: 상대 참조의 순환·없는 기준 사건, 선후관계 순환, 동시 사건의 엄격한 선후관계, 전이적 경로상 **불가능한** 절대 날짜 순서를 거부한다. 불가능한 저장·수정은 SQLite 트랜잭션을 **롤백**한다. 예: 10월 3일 사건 → 날짜 미정 사건 → 10월 1일 사건의 순서 제약은 모순으로 거부된다.
- 날짜가 겹치거나 시간이 미정이라면 **안전하다고 단정하지 않는다**. 검사 결과의 `unresolved_event_ids`는 정확한 절대시간으로 해석할 수 없는 사건을 나타낸다. 날짜만 기록된 사건도 날짜 구간은 알지만 하루 중 발생 시각은 미정이다. 이 기능은 완전한 제약 충족성 판정기가 아닌 **순환·명백한 불가능성 검출 기준선**이다. 원고 문장의 의미를 자동으로 읽거나 타임라인 모순을 추론하지 않는다.
- 작업별 `expected_revision`으로 수정·삭제 충돌을 방지하고, 성공한 변경마다 Novel Bible 작품 버전을 올린다. 작품/사건 ID를 검증하고 다른 작품의 사건을 연결하지 못하게 한다. 사건에 참조·순서 연결이 있으면 사건 삭제를 막는다. 작품 삭제 시 관련 사건과 순서 제약을 삭제한다.
- 검사의 자원 소모를 제한하기 위해 작품당 사건 최대 **512개**, 명시적 순서 제약 최대 **2,048개**를 허용한다. 초과하면 변경을 거부한다. 사용자 작성 제목은 SQLite에 **암호화되지 않은 평문**으로 저장한다.
- `event_cli.py`는 오프라인 명령줄 도구다. 기본 출력은 사건 제목을 숨기며, `--reveal`에서만 표시한다. 날짜·사건 ID는 출력된다. CLI 오류 메시지에는 사용자 작성 제목이 포함되지 않는다. 데이터베이스는 로컬 파일 경로만 허용한다. `--title` 값은 OS 프로세스 인자에서 보일 수 있으므로 민감한 제목을 사용할 때 주의한다.
- Novel Bible 설정 우선, 참고작 원문 비복제, 출판 전 사용자 승인 원칙은 그대로 유지된다. 자동 집필·원고 의미 검출·출판 승인/배포 기능은 이번 단계에서 구현하지 않았다.

## Windows PowerShell 예시 (Python 설치 환경, 프로젝트 루트)

```powershell
$env:PYTHONPATH = 'src'
# 기존 41단계에서 생성한 작품 ID를 사용한다.
python -m ai_novel_factory.database.event_cli --database .\my_bible.db event-add <작품ID> --title '출발' --when '2026-10-12'
# 출력된 event_id를 기준 사건 ID로 사용한다.
python -m ai_novel_factory.database.event_cli --database .\my_bible.db event-add <작품ID> --title '도착' --anchor <출발사건ID> --offset-minutes 90
python -m ai_novel_factory.database.event_cli --database .\my_bible.db event-list <작품ID>
python -m ai_novel_factory.database.event_cli --database .\my_bible.db order-add <작품ID> <출발사건ID> <도착사건ID>
python -m ai_novel_factory.database.event_cli --database .\my_bible.db event-audit <작품ID>
python -m ai_novel_factory.database.event_cli --database .\my_bible.db event-show <작품ID> <출발사건ID> --reveal
# 변경에는 현재 revision을 반드시 지정한다.
python -m ai_novel_factory.database.event_cli --database .\my_bible.db event-update <작품ID> <출발사건ID> --title '수정' --when '2026-10-12T09:00:00+09:00' --revision 1
python -m ai_novel_factory.database.event_cli --database .\my_bible.db order-remove <작품ID> <출발사건ID> <도착사건ID>
```

`event-add`/`event-update`의 `--when`과 `--anchor`/`--offset-minutes`는 **서로 배타적**이다. `event-audit`는 성공 시 `PASS`와 사건·제약·미해결 개수, 실패 시 `ERROR` 및 종료 코드 1을 출력한다. `PASS`는 **등록된 명시적 제약 범위**에서 모순을 찾지 못했다는 뜻이지 작품 전체의 서사적 정확성을 보증하지 않는다.

## 검증 범위 및 미검증 사항

`tests/test_stage46_event_timeline.py`와 `tests/test_stage46_release_verifier.py`에서 UTC 정규화, 날짜 단위의 보수적 판정, 상대시간 참조, 순환, 날짜/순서 충돌, 전이적 모순, 동시 사건, 롤백, 수정 버전, 작품 분리, 재시작 복원, CLI 기본 비노출, ZIP 필수 파일을 검사한다. 실제 실행 결과는 `docs/stage46_test_results.json`에 기록한다. Windows 10/11 실기기, Python 3.12, GUI/EXE, 실제 AI 모델은 이 환경에서 검증하지 않았다.
