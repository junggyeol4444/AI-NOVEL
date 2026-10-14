# 47/100단계 — 복선 설치·재언급·회수·폐기 상태 관리 (ANF-REQ-037)

## 요구사항과 범위

`docs/requirements.md`의 **ANF-REQ-037**: "복선 설치·재언급·회수·폐기 상태를 관리한다." 인수 기준: **OPEN/DEVELOPING/RESOLVED/ABANDONED 상태 추적**. 46단계까지 구현된 Novel Bible, 인물, 사건 타임라인, 참고작 원문 비복제 기능을 그대로 유지한다.

`src/ai_novel_factory/database/foreshadow.py`는 사용자가 명시적으로 작성한 복선 제목, 회차, 메모와 기록을 **작품별 로컬 SQLite**에 저장한다. `bible_foreshadow_threads`는 복선 ID·제목·수정 버전, `bible_foreshadow_events`는 복선 ID·사건 ID·회차·입력 순번·유형·메모를 저장한다. 작품 삭제 시 해당 작품의 복선·이력만 연쇄 삭제한다. 참고소설의 원문이나 설정을 자동으로 복사하거나 네트워크에 전송하지 않는다.

## 상태 전이

| 기록 유형 | 적용 조건 | 적용 후 상태 |
|---|---|---|
| `INSTALL` (설치) | 복선 생성 시 최초 1회 | `OPEN` |
| `REVISIT` (재언급) | `OPEN` 또는 `DEVELOPING` | `DEVELOPING` |
| `RESOLVE` (회수) | `OPEN` 또는 `DEVELOPING` | `RESOLVED` |
| `ABANDON` (폐기) | `OPEN` 또는 `DEVELOPING` | `ABANDONED` |

`RESOLVED`와 `ABANDONED`는 종료 상태다. 종료 상태 뒤의 추가 기록이나 두 번째 `INSTALL`은 거부한다. 설치 이전 회차 조회는 **`NOT_INSTALLED`**로 반환하며, 네 가지 관리 상태 중 하나라고 오인하지 않는다. 같은 회차에 여러 사건을 기록할 수 있고, **회차 오름차순·동일 회차 내 입력 순번**으로 처리한다. 이미 입력한 과거 회차로 새 사건을 추가하는 것도 가능하지만 전체 이력의 상태 전이가 유효해야 한다. 회수·폐기된 복선을 되살리려면 종료 사건을 명시적으로 수정·삭제해야 한다.

`get_at(project_id, thread_id, episode)`는 지정 회차의 상태·효력 발생 회차·마지막 기록 유형을 반환한다. `history`는 사건 전체를 회차순으로 반환한다. `audit`는 작품 전체 복선의 네 가지 상태별 개수, 미완료 복선 ID, 사건 수를 보고한다. **PASS는 등록된 수동 기록의 상태 전이가 유효하다는 뜻이며, 원고 의미 분석이나 실제 복선 회수의 적절성을 보증하지 않는다.** 완결 시 미회수 복선 차단은 후속 ANF-REQ-061(88단계) 범위이며 이번 단계에서 구현하지 않았다.

복선 제목 변경, 사건 추가·수정·삭제, 복선 삭제는 해당 복선의 `expected_revision` 확인을 요구한다. 여러 프로세스의 변경 충돌은 `BEGIN IMMEDIATE` 트랜잭션으로 검사하며, 잘못된 상태 전이나 오래된 버전의 변경은 전체 롤백한다. 모든 성공 변경은 Novel Bible 작품 버전도 증가시킨다. 작품당 복선 최대 512개, 사건 최대 4,096개를 검증한다. 제한을 넘는 변경은 거부한다. 사용자 작성 제목·메모는 **로컬 SQLite에 암호화되지 않은 평문**으로 저장된다. 다른 사람과 DB를 공유하지 않도록 주의해야 한다.

## Windows PowerShell 예시 (Python 설치 및 프로젝트 루트)

```powershell
$env:PYTHONPATH = 'src'
# 기존 Novel Bible 프로젝트 ID를 사용한다.
Set-Content -Encoding utf8 -Path .\title.txt -Value '잊힌 열쇠'
Set-Content -Encoding utf8 -Path .\note.txt -Value '1회차에서 단서를 설치'
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db thread-create <작품ID> --episode 1 --title-file .\title.txt --note-file .\note.txt
# 생성된 복선 ID를 사용한다. 새 복선의 revision은 1이다.
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db event-add <작품ID> <복선ID> --episode 3 --event-action REVISIT --revision 1
# 수정된 revision은 2이다.
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db event-add <작품ID> <복선ID> --episode 7 --event-action RESOLVE --revision 2
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db thread-status <작품ID> <복선ID> --episode 5
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db thread-status <작품ID> <복선ID> --episode 7
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db thread-history <작품ID> <복선ID>
python -m ai_novel_factory.database.foreshadow_cli --database .\my_bible.db foreshadow-audit <작품ID>
```

`thread-list`/`thread-show`/`thread-history`는 제목·메모를 기본적으로 표시하지 않으며 `--reveal`을 명시한 조회에서만 보여준다. 제목과 메모는 `--title-file`/`--note-file`로 입력해 OS 프로세스 인자 노출을 줄인다. 출력되는 ID·회차·상태는 비밀이 아니라고 가정해서는 안 되며 로그 취급에 유의해야 한다. CLI는 별도 파일을 생성하거나 원격 연결하지 않는다(지정한 로컬 DB 파일만 수정).

## 검증 및 한계

`tests/test_stage47_foreshadow.py`는 전이 4종, 설치 전 조회, 동일 회차 순서, 과거 기록 추가, 종료 후 변경 차단, 전체 이력 롤백, 수정 버전 충돌, 작품 격리, 삭제 연쇄, 재시작 복원, DB 손상 탐지, 기본 비노출 CLI 및 서브프로세스 실행을 검사한다. `tests/test_stage47_release_verifier.py`는 필수 누적 소스와 숨김 파일의 ZIP 포함을 검사한다. 실제 결과는 `docs/stage47_test_results.json` 및 `docs/stage47_verification_log.txt`를 참조한다.

Windows 10/11 실기기·EXE·Python 3.12, 실제 로컬 AI 집필 및 출판 승인 워크플로는 검증하지 않았다. 11개 선택적 GUI 테스트는 환경에 따라 건너뛸 수 있다. 외부 GitHub/원격 서버/클라우드 AI API는 사용하지 않는다. Novel Bible 우선, 참고작 원문 비복제, 사용자 승인 없는 출판 금지 원칙을 유지한다.
