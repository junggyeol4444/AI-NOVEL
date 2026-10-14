# 49/100단계 — 회차별 집필 데이터 저장 및 재시작 복원 (ANF-REQ-039)

## 요구사항 및 인수 기준

`docs/requirements.md`의 ANF-REQ-039: **회차별 플롯·장면·초고·확정본·요약·검사 기록을 저장한다.** 인수 기준: **회차 데이터를 재시작 후 복원할 수 있다.** 기존 48단계의 Novel Bible 우선·참고작 원문 비복제·사용자 승인 없는 출판 금지 원칙을 유지한다.

## 구현

`src/ai_novel_factory/database/episodes.py`의 `EpisodeStore`는 기존 작품별 Novel Bible SQLite DB에 `bible_episodes`, `bible_episode_scenes`, `bible_episode_checks` 테이블을 추가한다. 모든 데이터는 사용자가 직접 입력한 텍스트다. 참고작 파일·원문을 자동 가져오거나 복사하지 않으며, 원고 생성 모델 호출·외부 서버·클라우드 API·GitHub 기능이 없다.

- 회차: 1~1,000,000 사이 번호로 생성·조회·정렬 목록·수정·삭제. 작품별 최대 1,000개. `plot`(플롯), `draft`(초고), `final_text`(확정본), `summary`(요약) 각각 UTF-8 텍스트로 저장. 빈 문자열 허용. 각 필드 80,000/500,000/500,000/80,000바이트 제한, 네 필드 합계 최대 1,100,000바이트.
- 장면: 회차마다 1~200번 위치로 구분하여 생성·조회·수정·삭제. 위치 중복 금지, 장면당 80,000 UTF-8 바이트. 위치는 1부터 연속적일 필요가 없고, 정렬은 위치 오름차순이다.
- 검사 기록: 회차마다 최대 500개, `category`(소문자 코드), `outcome`(PASS/WARN/FAIL/NOT_RUN), `note`(8,192바이트)를 **사용자가 수동 등록**. 기록은 수정·삭제하지 않는 추가 전용 방식이며 등록 시 원고 `content_revision`을 기록한다. 이후 원고/장면이 수정되면 해당 기록을 `stale=true`로 표시한다. 검사 기록이 `PASS`라도 출판 승인이나 실제 자동 검증을 뜻하지 않는다.
- 회차/장면 변경은 현재 `expected_revision` 일치를 요구하며 `BEGIN IMMEDIATE` SQLite 트랜잭션으로 처리한다. 오류는 롤백하고 작품 전체 revision도 증가시킨다. 검사 기록 등록은 현재 회차 revision 일치가 필요하지만 **원고 revision은 증가시키지 않는다**. 따라서 같은 원고 revision에 여러 수동 검사를 기록할 수 있다.
- `EpisodeStore.snapshot`은 회차·장면·검사 기록을 단일 SQLite SAVEPOINT 읽기 스냅샷으로 결합한다. `EpisodeSnapshot.to_json()`은 기본적으로 원고·메모를 비노출 처리하고, `reveal=True`일 때만 명시적으로 출력한다. `publication_approved`는 항상 `false`다.
- 작품 삭제 시 외래 키 ON DELETE CASCADE로 회차·장면·검사 기록도 삭제된다. 회차 삭제 시 하위 장면·검사 기록이 삭제된다. 타 작품의 동일 회차 번호와 장면/검사 기록은 분리된다.
- 저장 텍스트는 UTF-8로 제한하고 NUL·제어문자·잘못된 surrogate를 거부한다. 데이터 손상은 사용자 원고를 오류 메시지에 노출하지 않고 실패 처리한다.

**주의:** 사용자 작성 원고·검사 메모는 암호화되지 않은 로컬 SQLite 평문이다. DB 파일·백업·로컬 화면의 `--reveal` 출력 접근을 사용자가 보호해야 한다. 저장된 확정본은 출판 가능 상태를 의미하지 않는다. 원고가 참조 원문과 비슷한지 자동 판정하지 않는다.

## Windows PowerShell 예시 (프로젝트 루트, Python 설치)

```powershell
$env:PYTHONPATH = 'src'
# 먼저 기존 Novel Bible CLI에서 작품을 생성하여 아래 ID를 교체하세요.
$projectId = '작품의32자리ID'
Set-Content -Encoding utf8 .\plot.txt '1회차 플롯'
Set-Content -Encoding utf8 .\draft.txt '1회차 초고'
Set-Content -Encoding utf8 .\scene.txt '첫 번째 장면'
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db episode-create $projectId 1 --plot-file .\plot.txt
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db episode-set $projectId 1 --revision 1 --draft-file .\draft.txt
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db scene-add $projectId 1 --revision 2 --position 1 --text-file .\scene.txt
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db check-add $projectId 1 --revision 3 --category continuity --outcome NOT_RUN
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db episode-show $projectId 1
# 명시적으로 로컬 화면에 원고를 보여줄 때만 --reveal
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db episode-show $projectId 1 --reveal
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db scene-list $projectId 1
python -m ai_novel_factory.database.episode_cli --database .\my_bible.db check-list $projectId 1
```

모든 본문 입력은 로컬 UTF-8 파일에서만 읽고 심볼릭 링크·원격 경로·파일 크기를 검사한다. `--reveal` 출력은 민감한 사용자 원고를 포함할 수 있다. 실제 검사 실행이나 출판 명령은 제공하지 않는다.

## 검증 범위와 한계

`tests/test_stage49_episodes.py`는 6종 데이터 저장·재시작 복원·다중 작품 격리·동시 수정 충돌·트랜잭션 롤백·장면 위치 중복·수동 검사 기록 구버전 판정·원고 기본 비노출·CLI 및 하위 프로세스·입력 크기 제한·손상 검출·연쇄 삭제를 검사한다. `tests/test_stage49_release_verifier.py`는 누적 ZIP의 필수 파일·숨김 파일을 검사한다. 전체 회귀 결과 및 ZIP 별도 압축 해제 후 결과는 `docs/stage49_test_results.json`과 `docs/stage49_verification_log.txt`에 기록한다.

이 단계는 **로컬 SQLite 저장 및 복원**까지다. 실제 로컬 AI 집필 엔진, 자동 원고 품질 검사, 참고작 원문 유사성 자동 평가, 자동 출판, 출판 승인 워크플로, Windows EXE는 구현하지 않았다. Windows 10/11 실기기 및 Python 3.12 실행은 별도 검증이 필요하다. GitHub/원격 저장소/외부 서버/클라우드 AI API 사용 없음.
