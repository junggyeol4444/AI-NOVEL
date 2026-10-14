# 44/100단계 — 세계관·조직·지역·능력·아이템 저장 (ANF-REQ-034)

## 원본 요구사항 및 인수 기준

`docs/requirements.md`의 ANF-REQ-034: **세계관·조직·지역·능력·아이템을 저장한다.**
인수 기준: **세계관 항목을 식별자 기반으로 조회할 수 있다.**

## 실제 구현

- `src/ai_novel_factory/database/world_canon.py` — Novel Bible과 **동일한 로컬 SQLite 파일**에
  `bible_world_entries` 테이블을 추가한다. 기존 작품/규칙/인물/지식 기록은 변경하지 않는다.
  기존 데이터베이스를 `WorldCanonStore`로 열면 새 테이블이 생성된다.
- 종류 코드는 `worldview`(세계관 규칙), `organization`(조직), `region`(지역),
  `ability`(능력), `item`(아이템) **다섯 가지**로 제한한다. 모든 항목은 **작품별**로
  분리되고 생성 시 32자리 무작위 hex `entry_id`를 받는다. 이후 이름/종류를 변경해도
  **식별자는 그대로** 유지된다. `get_entry(project_id, entry_id)`로 조회한다.
- 사용자 직접 작성 `name`(1~120자, 최대 UTF-8 480바이트)과
  `description`(1~4000자, 최대 UTF-8 8192바이트)을 저장한다.
  이름은 단일 줄, 설명은 여러 줄을 허용한다. 항목 이름은 동일 작품·동일 종류 안에서
  중복할 수 없지만, 다른 종류/다른 작품에서 같은 이름은 허용한다.
- 생성/조회/종류별 목록/수정/삭제를 지원한다. 수정/삭제에는 **현재 revision**이 필요하며
  잘못된 버전은 거부한다. 모든 성공한 변경은 상위 Novel Bible 작품의 revision을 올린다.
  작품 삭제 시 소속 항목은 외래키 연쇄 삭제된다. 실패한 변경은 롤백한다.
- `src/ai_novel_factory/database/world_cli.py` — 인터넷이 필요 없는 명령줄 인터페이스.
  이름/설명은 **명시적으로 지정한 로컬 UTF-8 텍스트 파일**에서만 읽는다.
  조회/목록/생성/수정의 기본 출력에는 사용자 작성 이름과 설명을 표시하지 않는다.
  `world-show --reveal`에서만 해당 내용을 출력한다. 오류 메시지에는 내용/파일 경로를
  포함하지 않는다. 파일 URI 및 UNC 형식 원격 입력 경로는 거부한다.
- 참고소설에서 원문을 자동으로 추출하거나 세계관 항목으로 복사하지 않는다.
  Novel Bible 우선 원칙 및 기존 비복제 검사 기능을 유지한다.

## Windows PowerShell 사용 예시 (인터넷 불필요)

프로젝트 루트에서 실행한다. 41단계의 `project-create`로 만든 작품 ID를 사용한다.

```powershell
$env:PYTHONPATH = 'src'
# 아래 두 파일에는 사용자가 직접 창작한 세계관 내용을 저장한다.
Set-Content -Encoding utf8 .\world_name.txt '붉은 산맥'
Set-Content -Encoding utf8 .\world_description.txt '북쪽 국경을 이루는 산맥이다.'
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-create <작품ID> --category region --name-file .\world_name.txt --description-file .\world_description.txt
# 출력의 entry_id를 <항목ID>로 사용한다.
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-list <작품ID>
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-list <작품ID> --category region
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-show <작품ID> <항목ID>
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-show <작품ID> <항목ID> --reveal
# revision 1 항목의 설명 변경 (성공하면 revision 2)
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-update <작품ID> <항목ID> --revision 1 --description-file .\world_description.txt
python -m ai_novel_factory.database.world_cli --database .\my_bible.db world-delete <작품ID> <항목ID> --revision 2
```

CLI 성공 종료 코드 0, 유효성/버전/파일 오류는 1이다. `--reveal`은 사용자 본인 요청일 때만 사용한다.

## 검증 범위 및 한계

- 신규 `tests/test_stage44_world_canon.py` 및 `tests/test_stage44_release_verifier.py`:
  5종 생성·ID 조회, 작품/종류 격리, 수정/삭제 버전 충돌, SQL 제약, 프로젝트 삭제 연쇄,
  재실행 복원, 기존 인물·지식 저장소와의 호환성, Novel Bible 우선 순위, 민감 정보 비노출,
  원격 파일 경로 거부, CLI 서브프로세스, 누적 ZIP 필수 파일·숨김 파일 검사.
- 기존 `scripts/verify_release_bundle.py` 필수 파일 목록에 44단계 소스/테스트/문서/결과를 추가했다.
- 결과 수치는 `docs/stage44_test_results.json`에 기록한다.
- **주의:** 사용자 입력 세계관 설정은 로컬 SQLite에 **암호화되지 않은 평문**으로 저장된다.
  참고 원문과의 유사성이나 저작권 적법성을 자동 판단하지 않는다.
  세계관 설정을 AI 집필 컨텍스트에 자동 주입하는 기능, 실제 로컬 Writer, GUI 연결,
  Windows 10/11 EXE 실행, Python 3.12 검증, 자동 출판은 **아직 구현/검증되지 않았다.**
  이 기능은 출판 승인 수단이 아니며 사용자 승인 없는 출판을 하지 않는다.
