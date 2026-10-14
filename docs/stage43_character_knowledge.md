# 43/100단계 — 인물별 회차 지식 범위 (ANF-REQ-033)

## 기획서 원문과 인수 기준

`docs/requirements.md`의 ANF-REQ-033: **인물별 지식 범위를 회차별로 관리한다.**
인수 기준: **인물이 모르는 정보를 사용한 예시를 오류로 표시한다.**

## 구현 범위

- `database/character_knowledge.py`: 기존 41·42단계 **동일한 로컬 Novel Bible SQLite**에
  `bible_knowledge_facts`(작품별 지식 사실) 및 `bible_knowledge_events`(인물·사실·회차별
  앎/모름 전환) 테이블 추가. 기존 DB를 재열면 테이블이 자동 추가된다.
- **사용자가 직접 등록한 사실**만 저장한다. 참고작 텍스트나 캐릭터 정보를 자동 추출·복사하지 않는다.
  사실 설명은 최대 4,000자/8,192 UTF-8바이트이며 SQLite에 **평문**으로 저장된다.
- 사실은 생성 후 수정할 수 없는 **불변 ID**다. 뜻이 바뀌면 사실을 삭제(관련 지식 이벤트
  전부 삭제됨)한 후 새 사실로 등록해야 한다. 회차별 지식 전환은 생성·조회·목록·버전 지정
  수정·삭제를 지원한다. 동일 회차의 기존 전환을 수정할 때 현재 `revision`이 필수다.
- 회차는 **1~1,000,000의 정수**. N회차에 `knows=True`로 등록한 지식은 N회차부터
  이후 변경 전까지 알려진 것으로 판단한다. `knows=False`를 등록하면 그 회차부터
  다시 모르는 상태다. 이벤트가 없거나 지식을 배우기 전인 경우 **알고 있다고 추정하지 않는다**.
- `check_uses(project_id, character_id, episode, fact_ids)`는 **이미 식별된 사실 ID**들을
  해당 인물이 그 회차에 알고 있는지 검사한다. 1~100개의 서로 다른 ID가 필수이고,
  하나라도 모르면 `allowed=False`와 `not_recorded`/`not_yet_learned`/`not_known` 오류가
  나온다. `require_known(...)`는 모르는 사실이 있으면 `KnowledgeError`로 차단한다.
  **중요: 원고 텍스트를 읽어 의미를 파악하거나 자동으로 사실 ID를 붙이는 NLP/LLM 기능은
  아직 없다.** 사용자/향후 집필 검증기가 회차·인물·사용 사실 ID를 제공해야 한다.
- 다른 작품의 사실·인물 ID를 사용할 수 없다. 복합 외래키가 직접 SQL 입력에서도 작품 간
  연결을 막는다. 인물·사실·작품 삭제 시 관련 이벤트는 연쇄 삭제된다. 변경마다 작품
  Novel Bible revision이 증가한다. Novel Bible 규칙은 기존처럼 참고 통계보다 우선한다.
- `database/knowledge_cli.py`: 네트워크 없는 명령줄 인터페이스. 사실 텍스트는 기본 비노출,
  `fact-show --reveal`일 때만 출력한다. 실패 출력에도 사실 내용이나 파일 경로를 담지 않는다.

## Windows PowerShell 오프라인 사용 예시

프로젝트 루트에서 실행한다. 기존 41·42단계 작품 ID와 인물 ID를 사용한다.

```powershell
$env:PYTHONPATH = 'src'
# fact.txt에는 직접 창작한 설정 사실만 작성한다.
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db fact-create <작품ID> --text-file .\fact.txt
# 출력된 fact_id를 <사실ID>에 넣는다.
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db fact-list <작품ID>
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db fact-show <작품ID> <사실ID>
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db event-set <작품ID> <인물ID> <사실ID> 3 --knows
# 2회차에는 아직 알지 못하므로 ERROR, 종료 코드 2
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db knowledge-check <작품ID> <인물ID> 2 --fact-id <사실ID>
# 3회차부터는 PASS, 종료 코드 0
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db knowledge-check <작품ID> <인물ID> 3 --fact-id <사실ID>
# 5회차에 잊거나 정보를 잃은 것으로 설정
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db event-set <작품ID> <인물ID> <사실ID> 5 --does-not-know
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db event-list <작품ID> <인물ID>
python -m ai_novel_factory.database.knowledge_cli --database .\my_bible.db knowledge-at <작품ID> <인물ID> <사실ID> 6
# 동일 회차 수정은 --revision 1 같은 현재 버전이 필요하다.
```

CLI `knowledge-check`는 **오류를 발견하면 종료 코드 2**를 반환하며, 존재하지 않는
작품·인물·사실·잘못된 입력 등은 종료 코드 1이다. 이는 원고의 법적 독창성이나
자동 출판 허가가 아니다. 사용자 승인 없는 출판 기능은 제공하지 않는다.

## 검증 및 제약

- 신규 `tests/test_stage43_character_knowledge.py`: 재실행 지속성, 회차 전/후,
  망각/재학습, 인물/작품 분리, 복합 FK, 동시 수정 충돌, 삭제 연쇄, 민감 텍스트 비노출,
  손상된 DB 레코드, CLI 오류 코드, 오프라인 실행 등.
- `tests/test_stage43_release_verifier.py`: 누적 ZIP 필수 파일과 숨김 `.gitignore` 검증.
- 검증 수치는 `docs/stage43_test_results.json`에 기록한다.
- **미구현/미검증:** 원고 자유 텍스트의 자동 의미 분석, 로컬 AI Writer 연결,
  실제 Windows 10/11 GUI·EXE, Python 3.12 실행, 암호화 저장, 자동 출판.
  이전 원문 비복제 검사 및 Novel Bible 우선 원칙은 유지한다.
