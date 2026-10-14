# 45/100단계 — 인물 관계 변화 회차별 저장 (ANF-REQ-035)

## 요구사항

`docs/requirements.md`의 ANF-REQ-035: **인물 관계 변화를 시간에 따라 저장한다.**
인수 기준: **같은 인물 쌍의 서로 다른 회차 관계를 조회할 수 있다.**

## 실제 구현

- `src/ai_novel_factory/database/relationships.py`: 기존 Novel Bible·인물 설정과 **동일한 로컬 SQLite 파일**에 `bible_relationship_events` 테이블을 추가한다. 관계는 사용자가 직접 작성하며 참고작에서 자동 추출하지 않는다.
- 관계는 두 **서로 다른** 인물의 **무순서 쌍**에 속한다. `A-B`와 `B-A`는 같은 쌍이다. 따라서 이 기능은 두 사람의 **공유된 관계 상태**를 기록하며, A가 B를 어떻게 생각하는지와 B가 A를 어떻게 생각하는지처럼 **방향별 감정 차이는 모델링하지 않는다.** 필요 시 이후 단계에서 확장한다.
- `episode`는 1~1,000,000 정수이며, 해당 회차부터 **다음 관계 이벤트 직전까지** 관계가 유지된다. 예: 1회차 동료, 4회차 적대라면 1~3회차 동료, 4회차부터 적대. 최초 기록 이전에는 `not_recorded`를 반환하고 관계를 추측하지 않는다.
- 사용자 입력 `relationship`은 필수(1~4,000자, UTF-8 최대 8,192바이트), `notes`는 선택(0~4,000자, UTF-8 최대 8,192바이트)이다. 사용자 작성 텍스트는 현재 **암호화되지 않은 SQLite 평문**으로 저장한다.
- `save_relation(project_id, a, b, episode, relationship=..., notes=...)`는 새로운 이벤트만 생성한다. 기존 이벤트 수정에는 **현재 `expected_revision`**이 필수이며, 최신 버전이 아니면 변경하지 않는다. `get_event`는 **정확히 지정한 회차**, `get_at`은 해당 회차에 **유효한 최근 이벤트**, `history`는 쌍의 모든 이벤트를 회차 오름차순으로 조회한다. `list_at`은 지정 회차에 기록된 모든 쌍의 최신 관계를 1개씩 조회한다. `delete_event`는 버전 일치 시 해당 회차 이벤트를 삭제한다. 마지막 이벤트를 삭제하면 이전 이벤트가 다시 유효해진다.
- 작품/인물 소속을 검사하고 복합 외래키로 다른 작품의 인물을 연결할 수 없게 한다. 인물 또는 작품을 삭제하면 관계 기록이 연쇄 삭제된다. 성공한 변경은 Novel Bible 작품 버전을 올리고 실패한 변경은 롤백한다.
- `src/ai_novel_factory/database/relationship_cli.py`: 명시적으로 지정한 **로컬 UTF-8 파일**에서만 관계·메모 내용을 읽는다. CLI 기본 출력은 관계 내용과 메모를 숨기며 `--reveal` 옵션에서만 표시한다. 오류는 사용자 작성 내용을 출력하지 않는다. 파일 URI 및 UNC 입력 경로는 거부한다.
- Novel Bible의 사용자가 명시한 설정이 참고소설의 익명 통계보다 우선하며, 참고작 원문 비복제 검사·출판 전 승인 원칙은 변경하지 않는다. **집필 엔진 연결·원고 의미 자동 분석·출판 기능은 구현하지 않았다.**

## Windows PowerShell 로컬 사용 예시

프로젝트 루트에서 실행한다. 기존 41단계에서 생성한 작품 ID 및 42단계에서 생성한 서로 다른 인물 ID 두 개가 필요하다.

```powershell
$env:PYTHONPATH = 'src'
Set-Content -Encoding utf8 .\relation.txt '협력 관계'
python -m ai_novel_factory.database.relationship_cli --database .\my_bible.db relationship-set <작품ID> <인물A_ID> <인물B_ID> --episode 1 --relationship-file .\relation.txt
python -m ai_novel_factory.database.relationship_cli --database .\my_bible.db relationship-show <작품ID> <인물A_ID> <인물B_ID> --episode 2
python -m ai_novel_factory.database.relationship_cli --database .\my_bible.db relationship-history <작품ID> <인물A_ID> <인물B_ID>
python -m ai_novel_factory.database.relationship_cli --database .\my_bible.db relationship-list <작품ID> --episode 2
# 기존 1회차 기록 수정: --revision 1을 지정 (성공하면 revision 2)
python -m ai_novel_factory.database.relationship_cli --database .\my_bible.db relationship-set <작품ID> <인물A_ID> <인물B_ID> --episode 1 --relationship-file .\relation.txt --revision 1
python -m ai_novel_factory.database.relationship_cli --database .\my_bible.db relationship-delete <작품ID> <인물A_ID> <인물B_ID> --episode 1 --revision 2
```

새 회차의 변화를 기록할 때는 `relationship-set`에 **다른 회차**를 지정하고 `--revision`을 생략한다. 기존 회차를 덮어쓸 때만 `--revision`이 필요하다. 성공 종료 코드 0, 검증/파일/버전 오류는 1이다. `--reveal`은 개인 정보 노출에 주의해 사용한다.

## 검증 범위와 한계

- 신규 `tests/test_stage45_relationships.py`와 `tests/test_stage45_release_verifier.py`는 회차별 변화·미기록·역순 쌍 동일성·인물/작품 격리·동시수정 방지·SQL 외래키/제약·연쇄 삭제·재실행 복원·CLI 기본 비노출·ZIP 누적 필수 파일을 검사한다.
- 이전 단계 전체 테스트와 ZIP 압축 해제 후 재실행 결과는 `docs/stage45_test_results.json`에 기록한다.
- 이 단계는 **규칙 기반 사용자 입력 데이터 관리**이며, AI가 원고에서 인물 관계를 추론하거나 모순을 자동 감지하지 않는다. 다른 관점의 방향별 관계/정확한 날짜 타임라인은 범위 밖이다.
- Windows 10/11 실기기, EXE, Python 3.12, GUI 연결은 검증하지 않았다. 기존 PySide6 선택 테스트는 환경에 따라 건너뛴다. 이 기능은 저작권 적법성이나 출판 승인을 보장하지 않는다.
