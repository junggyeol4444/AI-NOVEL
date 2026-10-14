# 2026-10-12 — 사용자 확정: PC 단독 실행 아키텍처 (최우선 규칙)

기존 3단계 설계 중 서버 위치 미정/원격 AI/원격 저장소를 운영에 사용하는 선택지는
이후 사용자가 명시한 **완전 로컬 실행**과 충돌하므로 **폐기된 과거 설계**다.
아래 과거 기록은 참고용으로만 유지하며 구현 결정의 근거가 아니다.

```
사용자 Windows PC ─ AI Novel Factory.exe (PySide6)
                   ├─ Python 직접 호출: 문서 파서·Reference Profile·작품 설정
                   ├─ 로컬 SQLite: 캐릭터/Novel Bible/원고 기록 (완성 예정)
                   ├─ 프로세스 내부 작업 처리: 작업 큐·체크포인트 (완성 예정)
                   ├─ PC 로컬 모델 파일: AI 추론 (미구현)
                   └─ EPUB/출판 파일 생성 (미구현)
```

- **GitHub는 어떠한 실행·저장·인증·업데이트 필수조건도 아니다.** ZIP과 EXE는 GitHub 없이 사용 가능해야 한다.
- **외부 호스트 주소, 클라우드 AI, PostgreSQL/Redis 서버 연결은 이 로컬 개발본에서 금지**된다.
- FastAPI는 9단계 개발 유산인 **선택적인 동일 PC 진단 기능**일 뿐이며, 분석 및 출판 작업의 필수 전제조건이 아니다.
- AI 모델은 로컬 파일로 제공하고 PC 내부 프로세스로 실행해야 한다. **아직 실제 추론 코드는 없다.**
- 네트워크가 없어도 설치된 파일·모델로 핵심 기능을 수행하도록 후속 개발과 실기기 검증이 필요하다.
- 외부 출판은 전적으로 사용자 명시적 승인 이후 별개로 다룬다.
- PostgreSQL·Redis·Celery 및 외부 AI 키가 적힌 초기 의존성 문서는 기존 이력이며 설치·실행 요구사항이 아니다.

---

# 기존 초기 설계 원본 기록 (이하 문서의 원격/미정 선택지는 폐기됨)

# AI Novel Factory — 3단계 기술 스택·아키텍처 설계

> 상태: 설계 계약 작성 및 정적 검증. 실제 EXE, 서버, DB, AI 호출은 구현·실행하지 않음.
> 원본: 첨부 기획안 + 1단계 `docs/requirements.json` (74개 요구사항).
> 주의: 현재 작업 공간에서 2단계 결과를 확인하지 못함. 2단계 경계 확정 결과가 확보되면 충돌 여부를 검토해야 함.

## 1. 기술 선택

| 계층 | 기술 | 근거 | 실제 도입 시기 |
|---|---|---|---|
| Windows GUI | Python, PySide6 | 네이티브 데스크톱 인터페이스 | 8단계 |
| EXE 배포 | PyInstaller | Python 앱 Windows 패키징 | 97단계 |
| API | FastAPI, Pydantic | 명시적 요청·응답 모델 | 9단계 |
| 영속 DB | PostgreSQL | 작품/인물/회차 정규 데이터 | 41~50단계 |
| 의미 검색 | pgvector | 과거 회차/설정 검색 | 56단계 |
| 비동기 작업 | Redis, Celery | 장기 생성 작업 큐 | 67단계 |
| 문서 입력 | TXT/MD, EPUB, DOCX, PDF 파서 | 원 기획안 입력 포맷 | 13~16단계 |
| AI | 교체 가능한 provider adapter | 제공자 미선정·승인 필요 | 61단계 |
| 테스트 | Python unittest, pytest | 설계/기능/통합 검증 | 단계별 |
| 전자책 | EPUB3 | 전자책 표준 출력 | 93단계 |

Python 및 라이브러리의 **정확한 버전과 고정 의존성**은 5단계에서 결정한다. Windows 지원 버전과 아키텍처는 사용자 승인 대기 상태다.

## 2. 실행 구조

```text
[사용자 Windows PC]
  AI Novel Factory.exe (PySide6)
            |
            | HTTP(S) JSON
            v
[FastAPI: 로컬 또는 승인된 원격 환경, 미결정]
            |
   [Orchestrator / Planner / Writer / Quality / Publishing]
            |                  |                  |
            v                  v                  v
  PostgreSQL+pgvector     Celery+Redis       승인된 AI API
    (위치 미결정)         (위치 미결정)        (미선정)
```

- EXE는 사용자 조작, 진행 표시, 승인 화면을 담당한다.
- EXE가 DB/Redis에 직접 접속하지 않는다. API 경계를 거친다.
- API가 로컬이면 loopback(127.0.0.1)에만 바인딩하는 것을 기본으로 하며, 원격이면 TLS와 인증이 필수다.
- 사용자 PC가 꺼진 상태의 실제 집필/빌드는 **승인된 원격 작업 실행기와 원격 저장소가 준비된 경우에만** 가능하다.
- 배포 위치와 오프라인 동작 범위는 2단계 산출물 확인 및 사용자 승인 이후 확정한다.

## 3. 소설 제작 데이터 흐름

```text
허용된 참고작 → 문서 파서 → Reference Profile(구조·통계) ┐
                                                    v
Novel Bible (우선) → Story Arc → Episode → Scene Planner
                                                    |
                                                    v
                                    필터링된 컨텍스트 → Writer
                                                    |
                                                    v
                             Continuity / Logic / Style / Similarity
                                                    |
                                         실패: 문제 Scene 재작성
                                                    |
                                          성공: 원고 확정
                                                    |
                                    Memory Delta → DB 업데이트
                                                    |
                                 EPUB·출판 파일 / 출판 승인 대기
```

참고작 원문은 Writer에 직접 전달하지 않는다. 참고작은 권리 확인 후 구조·통계·패턴만 활용한다. Novel Bible이 참고 프로필보다 우선한다. 참고작이 있는 원고는 유사성 검사 기록 없이 확정하지 않는다. 외부 게시에는 별도 사용자 승인이 필요하다.

## 4. 설계 불변 조건 (machine-readable)

`docs/architecture_decisions.json`에 구성요소, 연결, 설치 위치 미결정 상태, 필수 통제 규칙을 저장한다. `src/ai_novel_factory/architecture.py`는 JSON 계약을 검증한다. 이는 제품 구현이 아니라 후속 개발이 따라야 할 계약이다.

## 5. 사용자 승인 대기 — PC를 켠 뒤 확인

- Windows 버전/CPU, 백엔드·DB·Redis·worker의 로컬/클라우드 위치.
- 원격 소스 저장소·CI/CD 연결 권한.
- AI 제공자, API 키, 사용 예산 상한.
- 원고/참고작 보관 위치, 보존 기간 및 사용 권한.
- 출판 플랫폼 계정과 실제 게시 승인 방식.

이 항목들은 **승인 전 설치·연결·결제하지 않는다**. 현 시점에는 사용자가 즉시 해야 할 작업이 없다.

## 6. 실행 및 검증

프로젝트 루트에서:

```powershell
python -m unittest discover -s tests -v
python src/ai_novel_factory/architecture.py
```

- 성공 기준: 1단계 요구사항 정합성 테스트와 3단계 설계 계약 테스트 모두 통과.
- 검증 범위: 문서/JSON의 구조·필수 규칙·연결 관계. 실제 Windows GUI/DB/API/EXE 실행은 미검증.

## 7. 완료 판정 및 다음 단계

- [x] 원기획안 기술 스택과 EXE 연결 구조를 정리.
- [x] 구성요소·데이터 흐름·권한 경계를 기계 판독 가능한 형태로 작성.
- [x] 비복제·Novel Bible 우선·유사성·출판 승인 정책 반영.
- [x] 문서 정합성 자동 검증.
- [ ] 2단계 경계 설계와 교차 확인 (산출물 부재).
- [ ] 사용자 승인 및 실제 서비스/Windows 실행 검증 (추후).

**4단계: 저장소·폴더 구조.** 지금 정의한 모듈 경계를 기준으로 프로젝트 디렉터리, 모듈 import 경계, 테스트/문서 경로를 구체화한다.
