# 40/100단계 — 참고소설 분석 통합 테스트 (로컬 전용)

## 이번 단계의 범위

39단계 누적 ZIP을 실제로 **별도 폴더에 압축 해제하여 테스트**했다. 이 과정에서
39단계 ZIP에 `.gitignore`가 빠져 있어 988개 중 **3개 테스트가 오류**를 내는
패키징 결함을 확인했다. 이전 작업 폴더에는 이 파일이 존재했다. 40단계에서는
해당 파일을 누적 소스에 복구하고 ZIP 검사 도구로 재발을 방지했다.

이번 단계의 새 구현은 **자동 집필 기능이 아니라 통합 회귀 테스트와 배포 전
검증 도구**다. 가상의 합성 문장만 사용하고, 사용자가 보유한 참고소설 원문이나
실제 개인 데이터를 테스트에 사용하지 않는다.

### 통합 시나리오

`tests/test_stage40_reference_integration.py` (28개):

- 임시 TXT/Markdown 참고작 6개 생성 → 실제 로컬 파일 읽기 → 회차 분리
  → 수치 프로필 생성 → SQLite 저장/재열기 → 장르별 3개 프로필로 통계 패턴 구축.
- `equal`/`characters` 가중치, 참고 요소 선택, 관련 장르 통계 검색,
  **사용자가 명시적으로 선택한 경우에만** 사용 기록 생성.
- 강도를 한 작품에 편중시키면 선택·검색·사용 기록을 차단하고,
  설정을 원복하면 정상 복구되는지 확인.
- 참고작 구성 변경 시 기존 패턴 재구축 요구, 프로필 삭제 시 종속 패턴 무효화.
- TXT/Markdown 외에도 합성 DOCX/PDF를 실제 생성하여 가져오기·프로필화
  (각각 `python-docx`/`pypdf`가 없으면 해당 1개 테스트를 건너뜀).
- 잘못된 UTF-8, EPUB 미지원, 파일 크기 초과, 심볼릭 링크를 거부하고
  잘못된 가져오기로 DB에 참고작이 추가되지 않는지 확인.
- 직접 복제는 `blocked`, 일부 단어 변형은 `review`, 비교 근거 부족은
  자동 사용 불가. CLI에서 문단·수치만 출력하며 원문·파일 경로를 노출하지 않음.
- 소켓 접속을 막은 상태에서 실제 가져오기/검색을 수행해 네트워크 비의존 확인.

`tests/test_stage40_release_verifier.py` (14개):

- 누적 ZIP 필수 파일(`.gitignore` 포함) 누락, 압축 경로 탈출,
  중복 이름, 심볼릭 링크, `.env`/SQLite/캐시/빌드 파일 포함,
  손상된 ZIP을 검출하는지 검증.
- `scripts/verify_release_bundle.py`는 검사 대상 ZIP의 **파일명을
  오류 출력에 포함하지 않으며**, ZIP을 디스크에 풀지 않는다.
- **제한:** ZIP 검증은 무결성·구성·기본 개인정보 파일 패턴 검사이며,
  소스 전체의 보안성이나 저작권 적법성 인증이 아니다.

## 재현 방법 (프로젝트 루트에서)

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p "test_stage40_*.py" -v
python -m unittest discover -s tests -q
python scripts/smoke_test.py
python scripts/check_dependencies.py
python -m compileall -q src tests scripts
python scripts/verify_release_bundle.py "..\AI_Novel_Factory_stage40_local.zip"
```

실행 시 외부 서버, GitHub, 클라우드 AI 호출이 필요 없다. **프로젝트 의존성 설치는
이 단계에서 실행하지 않았다.** GUI는 PySide6가 없으면 건너뛰며,
Windows 10/11 실기기, Python 3.12, EXE 빌드, 로컬 LLM 집필·Novel Bible·출판
승인 워크플로는 이번 단계에서 검증되지 않았다.

## 개인정보·저작권 관련 한계

원문은 임시 테스트 파일 또는 사용자가 지정한 파일을 검사하는 동안에만 읽고,
기존 프로필/패턴/사용 기록에는 숫자와 고정 코드만 저장한다. **참고작 파일의
기본 이름과 SHA-256은 기존 목록 메타데이터에 저장될 수 있다.** 따라서
'어떤 식별정보도 저장하지 않는다'는 의미가 아니다. 검사는 사용자가 지정한
참고작과 규칙 기반 문자열/문단 유사도만 비교한다. 의역·번역·구조 유사성,
저작권 침해 여부를 판정하지 못한다. 통과는 창작 원고의 법적 안전성 보증이
아니며, 자동 출판을 허용하지 않는다.

결과 기록: `docs/stage40_test_results.json`.
