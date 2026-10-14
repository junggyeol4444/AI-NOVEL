# 48/100단계 — Style Bible 저장 및 생성 컨텍스트 반영 (ANF-REQ-038)

## 요구사항·인수 기준

`docs/requirements.md`의 ANF-REQ-038: **작품 고유 문체 규칙을 Style Bible에 저장한다.** 인수 기준: **문체 설정을 생성 컨텍스트에 반영한다.** 47단계까지의 누적 소스와 Novel Bible 우선·참고작 원문 비복제·사용자 승인 없는 출판 금지 원칙을 유지한다.

## 구현

`src/ai_novel_factory/database/style_bible.py`의 `StyleBibleStore`는 작품별 **사용자 직접 작성** 문체 규칙을 기존 Novel Bible과 같은 로컬 SQLite 파일의 `bible_style_rules` 테이블에 저장한다. 규칙은 소문자·숫자·밑줄로 된 항목 코드(예: `tone`, `voice`, `narration`, `dialogue`, `forbidden_phrases`)와 UTF-8 문체 지시문으로 구성된다. 저장·조회·목록·수정·삭제, 작품별 격리, 재시작 복원, 작품 삭제 시 연쇄 삭제, 수정 버전 충돌 차단, 전체 프로젝트 revision 증가를 지원한다. 기존 항목 수정·삭제는 `expected_revision`이 일치해야 한다. 동일 DB를 사용하는 여러 프로세스의 변경은 `BEGIN IMMEDIATE`로 직렬화하며, 오류 발생 시 변경을 롤백한다.

규칙 하나는 최대 4,000자/8,192바이트, 작품별 최대 32개·합계 32,768 UTF-8 바이트로 제한한다. 입력에 제어문자·고립 surrogate·빈 문자열을 허용하지 않는다. 저장 데이터의 손상을 검출하면 내용 노출 없이 오류로 처리한다. **문체 규칙은 암호화되지 않은 로컬 SQLite 평문**이므로 개인 PC 접근 권한 관리가 필요하다.

`build_generation_context(project_id, reference_statistics=None)`는 DB 읽기를 SQLite SAVEPOINT 스냅샷으로 묶고 `GenerationContext`를 반환한다. 우선순위는 **Novel Bible > Style Bible > 허용된 익명 참고 통계**다. 같은 키가 겹치면 상위 설정만 `fields`에 반영하고 `overridden_style_keys`·`overridden_reference_keys`에 덮어쓴 키를 기록한다. Novel Bible 규칙 또는 Style Bible 규칙이 하나도 없으면 **생성 컨텍스트 생성 실패**로 처리한다. 참고 통계는 기존 허용된 `FEATURE_KEYS`의 유한한 숫자만 사용하고 DB에 저장하지 않는다. 참고 원문, 대사, 문단을 자동 저장·포함하지 않는다. `GenerationContext.to_json()`은 정렬된 구조화 JSON을 생성하며 `publication_approved: false`를 명시한다. 이 JSON은 **향후 로컬 집필 엔진에 전달할 데이터**일 뿐, 모델 호출이나 실제 원고 생성·출판이 아니다. 데이터 필드의 사용자 텍스트를 실행 가능한 명령으로 취급하지 않는다.

## Windows PowerShell 사용 예시 (Python 설치, 프로젝트 루트)

```powershell
$env:PYTHONPATH = 'src'
# 기존 Novel Bible 작품 ID가 필요합니다. 먼저 최소 1개의 Novel Bible rule을 등록해야 합니다.
Set-Content -Encoding utf8 -Path .\style.txt -Value '서술은 간결하고 감탄사를 절제한다.'
python -m ai_novel_factory.database.style_cli --database .\my_bible.db style-set <작품ID> tone --directive-file .\style.txt
python -m ai_novel_factory.database.style_cli --database .\my_bible.db style-list <작품ID>
python -m ai_novel_factory.database.style_cli --database .\my_bible.db style-show <작품ID> tone
python -m ai_novel_factory.database.style_cli --database .\my_bible.db context <작품ID>
# 명시적으로 민감한 내용을 로컬 화면에 출력할 때만 --reveal 사용
python -m ai_novel_factory.database.style_cli --database .\my_bible.db context <작품ID> --reveal
# 수정은 현재 revision 지정이 필수
python -m ai_novel_factory.database.style_cli --database .\my_bible.db style-set <작품ID> tone --directive-file .\style.txt --revision 1
python -m ai_novel_factory.database.style_cli --database .\my_bible.db style-delete <작품ID> tone --revision 2
```

명령줄에서 규칙 본문은 기본적으로 **비노출**이며 `--reveal`을 지정한 조회에서만 표시한다. 민감한 본문은 프로세스 인자 대신 `--directive-file`을 사용한다. `--statistics-file`을 지정하면 로컬 JSON 파일의 익명 통계를 함께 결합한다. 파일 크기와 심볼릭 링크를 검사한다. `--reveal` 출력·셸 리다이렉션·스크린샷에는 비공개 설정이 포함될 수 있다. SQLite 파일·백업·명령줄 기록은 사용자가 직접 관리해야 한다.

## 검증 범위 및 한계

`tests/test_stage48_style_bible.py`는 저장·재시작·동시 수정 충돌·작품 격리·삭제·제한·손상·CLI·서브프로세스·문체 반영·Novel Bible 우선·참고 통계 비복제를 검사한다. `tests/test_stage48_release_verifier.py`는 누적 ZIP의 필수 소스·숨김 파일을 확인한다. 전체 회귀 테스트 및 ZIP 압축 해제 후 재검증은 `docs/stage48_test_results.json`과 `docs/stage48_verification_log.txt`에 기록한다.

이번 단계는 **사용자 작성 규칙을 구조화된 생성 컨텍스트에 반영하는 것까지** 구현한다. AI 모델 연결, 생성 결과의 문체 준수 자동 평가(ANF-REQ-053, 76단계), 사용자 승인/출판 워크플로, Windows EXE는 구현하지 않았다. Windows 10/11 실기기 및 Python 3.12 실행도 검증하지 않았다. GitHub/원격 저장소/외부 서버/클라우드 AI API는 사용하지 않는다.
