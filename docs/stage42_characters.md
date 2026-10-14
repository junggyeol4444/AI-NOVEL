# 42/100단계 — Novel Bible 인물 성격·목표·말투·비밀 저장 (ANF-REQ-032)

## 기획서 기준

`docs/requirements.md` ANF-REQ-032: **"인물의 성격·목표·말투·비밀을 저장한다."**
인수 기준: **"인물 데이터 생성·수정·조회가 가능하다."**
41단계 Novel Bible 작품 저장소에 직접 연결하며, 43단계(회차별 지식 범위),
44~49단계(세계관·관계·시간·복선·스타일·회차)는 미구현이다.

## 구현 파일

- `src/ai_novel_factory/database/characters.py`: 기존 `NovelBibleStore`의 동일한
  SQLite DB에 `bible_characters` 테이블 추가. 인물 ID와 작품 ID는 32자리 UUID hex.
  이름·성격·목표·말투는 필수, 비밀은 빈 문자열 허용. 생성·목록·상세·부분 수정·삭제.
- 인물명은 작품별 중복 불가. 각 작품의 데이터는 분리되고 작품 삭제 시 함께 삭제.
- 신규 인물은 revision 1, 수정 시 revision 증가. 수정·삭제는 **현재 revision**이
  필수이며 다른 연결의 선행 수정과 충돌하면 저장하지 않는다. 작품의 Novel Bible
  revision도 인물 변경마다 증가. 변경은 SQLite 트랜잭션으로 처리한다.
- 길이·UTF-8 바이트·제어문자·형식 검증 및 저장 데이터 손상 검사. 오류 메시지에는
  사용자 이름·대사·비밀·입력 경로를 출력하지 않는다.
- `src/ai_novel_factory/database/character_cli.py`: 로컬 파일에서만 입력하는 CLI.
  목록과 상세는 기본적으로 내용 비노출. `character-show --reveal`로 명시적으로
  요청할 때만 내용을 화면에 표시한다.
- **저장되는 내용은 사용자가 직접 입력한 Novel Bible 인물 설정이다.** 참고작의
  원문/인물/문장/고유 표현을 자동 수집·복사하지 않는다. 통계 패턴과 충돌하면
  기존 41단계 Novel Bible 규칙이 우선하는 동작을 변경하지 않는다.

## 실행 예시 (Windows PowerShell, 네트워크 연결 불필요)

프로젝트 루트에서 실행하며 `--database`는 기존 41단계 DB를 지정한다.
먼저 `novel_bible_cli project-create`로 생성한 작품 UUID를 사용한다.

```powershell
$env:PYTHONPATH = 'src'
# 인물명 파일에는 줄바꿈 없이 기록한다.
[System.IO.File]::WriteAllText((Join-Path (Get-Location) 'name.txt'), '주인공')
[System.IO.File]::WriteAllText((Join-Path (Get-Location) 'personality.txt'), '침착하고 관찰력이 뛰어나다')
[System.IO.File]::WriteAllText((Join-Path (Get-Location) 'goal.txt'), '사라진 친구를 찾는다')
[System.IO.File]::WriteAllText((Join-Path (Get-Location) 'speech.txt'), '존댓말을 쓰고 말을 아낀다')
[System.IO.File]::WriteAllText((Join-Path (Get-Location) 'secret.txt'), '친구와 과거에 만난 적이 있다')
python -m ai_novel_factory.database.character_cli --database .\my_bible.db character-create <작품ID> --name-file .\name.txt --personality-file .\personality.txt --goal-file .\goal.txt --speech-file .\speech.txt --secret-file .\secret.txt
# 위 명령의 UUID가 <인물ID>다.
python -m ai_novel_factory.database.character_cli --database .\my_bible.db character-list <작품ID>
python -m ai_novel_factory.database.character_cli --database .\my_bible.db character-show <작품ID> <인물ID>
python -m ai_novel_factory.database.character_cli --database .\my_bible.db character-show <작품ID> <인물ID> --reveal
python -m ai_novel_factory.database.character_cli --database .\my_bible.db character-update <작품ID> <인물ID> --revision 1 --goal-file .\goal.txt
python -m ai_novel_factory.database.character_cli --database .\my_bible.db character-delete <작품ID> <인물ID> --revision 2
```

위 텍스트 파일과 SQLite DB는 **사용자 PC의 로컬 개인 폴더에만** 저장하고
개발 소스 ZIP에 포함하지 않는다. 비밀은 SQLite에서 **암호화되지 않은 평문**이다.
`--reveal` 출력·터미널 기록·PC 백업에 비밀이 남을 수 있으므로 주의해야 한다.
Windows ACL·암호화·키 관리는 아직 검증·구현되지 않았다.

## 검증과 미완성

`tests/test_stage42_characters.py`: SQLite 재열기·작품별 격리·필드 수정·버전 충돌·
두 연결 동시 수정·삭제 연쇄·입력 검증·오염 데이터 거부·CLI 기본 비노출·파일
입력·네트워크 호출 금지 등을 검사한다. `tests/test_stage42_release_verifier.py`:
누적 ZIP 필수 파일 검사. 실제 실행 결과는 `docs/stage42_test_results.json` 참조.

**미구현:** 인물별 회차 지식 범위, 인물 설정의 AI Writer 프롬프트 자동 연결,
인물 간 관계/시간 검증, Windows GUI 편집 화면, 로컬 LLM 집필, EXE, 출판.
Novel Bible 저장이 참고 원문 유사성 검사나 출판 승인 절차를 대체하지 않는다.
사용자 승인 없는 출판은 허용하지 않는다. Python 3.12 및 Windows 10/11
실기기 실행은 별도 검증이 필요하다.
