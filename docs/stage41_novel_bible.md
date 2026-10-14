# 41/100단계 — Novel Bible 최우선 설정 저장 (ANF-REQ-031)

## 기존 기획서 확인

`docs/requirements.md`의 ANF-REQ-031: **“Novel Bible을 작품의 최우선 설정 기준으로 저장한다.”**
인수 기준은 **“참고 패턴과 충돌 시 Novel Bible이 우선됨을 검증한다.”**
41단계는 작품별 최상위 설정의 로컬 영속 저장 및 우선순위 검증이다. 인물 상세
(42단계), 인물 지식 (43단계), 세계관 엔터티 (44단계), 관계/시간/복선/스타일/회차
(45~49단계) 기능을 이미 구현했다고 주장하지 않는다.

## 구현

- `database/novel_bible.py`: 별도 로컬 SQLite에 작품(UUID, 제목)과 사용자 작성
  canon 규칙(고정 영문 키, 자유 텍스트 값, 수정 버전)을 저장한다. 서로 다른 작품은
  독립적이며 삭제 시 종속 규칙도 함께 삭제된다. 재실행 후 재조회가 가능하다.
- 사용자가 명시적으로 저장할 때만 텍스트가 디스크에 기록된다. 참고작 원문을
  자동 수집/복제/저장하는 경로는 없다. **사용자가 직접 입력한 Novel Bible 내용은
  DB에 평문으로 저장**된다. 암호화·OS 백업 보호 기능은 아직 없다. POSIX에서는
  파일 접근권한을 `0600`으로 조정한다. Windows 파일 권한은 별도 검증이 필요하다.
- 기존 규칙 변경/삭제에는 최신 `revision`이 필요하다. 다른 창에서 수정한 버전을
  조용히 덮어쓰지 않으며 트랜잭션을 사용한다.
- `resolve_context()`는 **검증된 6종 통계 키의 유한한 숫자**만 참고 패턴으로
  받는다. 같은 키에 사용자 Novel Bible 규칙이 있으면 사용자 규칙이 반드시 우선한다.
  숫자 통계는 DB에 저장되지 않으며, 비어 있는 Novel Bible은 안전하게 실패한다.
- `database/novel_bible_cli.py`: GUI/클라우드 없이 로컬 프로젝트/규칙 생성,
  조회, 변경, 삭제, 우선순위 미리보기. 규칙 본문은 기본적으로 숨기며
  `rule-show --reveal`을 명시한 경우에만 콘솔에 출력한다.
- 입력값/파일경로/참고작 인용을 오류 메시지에 포함하지 않는다.

## 로컬 CLI 예시

프로젝트 루트에서 (`python`은 프로젝트의 로컬 Python):

```powershell
$env:PYTHONPATH = 'src'
python -m ai_novel_factory.database.novel_bible_cli --database .\my_bible.db project-create '나의 작품'
# 위 명령이 반환한 UUID를 <작품ID>에 넣으세요.
Set-Content -Encoding utf8 .\canon.txt '이 세계에서는 시간 역행이 불가능하다.'
python -m ai_novel_factory.database.novel_bible_cli --database .\my_bible.db rule-set <작품ID> canon --value-file .\canon.txt
python -m ai_novel_factory.database.novel_bible_cli --database .\my_bible.db rule-list <작품ID>
python -m ai_novel_factory.database.novel_bible_cli --database .\my_bible.db rule-show <작품ID> canon
python -m ai_novel_factory.database.novel_bible_cli --database .\my_bible.db context <작품ID>
```

위 `my_bible.db`와 `canon.txt`는 **사용자 PC에만** 두어야 하며 누적 소스 ZIP에
넣지 않는다. Windows에서 파일 삭제, 백업, 접근권한은 사용자 책임이다.

이미 존재하는 규칙을 수정할 때는 `rule-set ... --revision 1`처럼 `rule-show`의
현재 revision을 함께 전달해야 한다. `rule-delete`에도 `--revision`이 필수다.
`context --statistics-file metrics.json`은 6개 고정 통계 키에 숫자만 담은 로컬
JSON을 사용한다. 원문, 인용, 고유 설정은 허용하지 않는다. 이 입력은 아직
이전 단계의 패턴 선택 엔진과 자동 연결되지 않았으므로 **사용자가 검증된
통계만 명시적으로 제공**해야 한다.

## 테스트와 한계

`tests/test_stage41_novel_bible.py`에서 실제 SQLite 파일 재열기, 서로 다른 작품
분리, Canon/참고 통계 충돌 우선순위, 저장/삭제 트랜잭션, 버전 충돌,
손상된 데이터 거부, 오프라인 CLI, 기본 비노출, 경로/입력 검증을 확인한다.
`tests/test_stage41_release_verifier.py`에서 누적 ZIP 필수 파일도 확인한다.

**미구현:** 로컬 AI Writer/집필 프롬프트 연결, 원고 자동 검수, 인물/세계관 구조화,
Windows GUI와 EXE 실기기 검증, 자동 출판, 법적 저작권 적합성 판정.
Novel Bible 저장이 참고작 복제 방지나 출판 승인을 대체하지 않는다.
사용자가 승인하지 않은 출판은 허용하지 않는다.
