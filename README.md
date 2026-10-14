## 최신 작업 — 공식 99단계 Windows 실제 실행/종합 회귀 (Linux에서 도구 및 오프라인 회귀만 검증)

- **ANF-REQ-071**: 실제 Windows에서 EXE 실행 및 종합 회귀 결과를 PASS/FAIL/UNVERIFIED로 구분할 수 있는 `scripts/stage99_windows_acceptance.py`, `stage99_partitioned_regression.py`와 단계 지침을 추가.
- 현재 Linux/Python 3.13.5에서 테스트한 사전검사: `not_windows`, `python_not_3_12`, `exe_missing`. **Windows EXE 실제 실행 및 99단계 인수 미충족**. Linux 회귀 테스트는 Windows 회귀의 대체물이 아니다.
- 공식 플랫폼 API(95), 공식 업로드 형식(96), Windows EXE 실빌드(97) 미충족 유지. `physical_display_user_review`는 실제 Windows에서 수동 확인 전 항상 UNVERIFIED.
- 원본 기획안 TXT 직접 미확인; 대화의 100단계 로드맵과 누적 소스 `docs/requirements.md` 기준. 외부 서버·GitHub·클라우드 API 접속·원고 확정·출판 없음.
- 설명: `docs/stage99_windows_integrated_regression.md`; 테스트/실행 기록: `docs/stage99_test_results.json`, `docs/stage99_verification_log.txt`, `docs/stage99_worktree_*`.

---

## 최신 작업 — 공식 98단계 설치·설정·외부서비스 연결 안내 (오프라인)

- `docs/stage98_installation_and_connection_guide.md`: Windows EXE(미생성)와 소스 사용 시 필수·선택·유료 구성요소 구분, 백업/오프라인 설정/외부서비스 금지 및 확인 절차 명시. **ANF-REQ-070** 기준.
- `scripts/stage98_offline_setup.py`: 환경 수정이나 설치 없이 이 실행 환경에 대한 읽기 전용 점검. API 키·환경 변수 값·원고 데이터·사용자 로컬 경로를 수집하거나 공개하지 않음. 승인/출판·원격 연결 없음.
- 95 공식 API 테스트, 96 공식 플랫폼 형식, 97 Windows EXE 실빌드 인수 조건은 **미충족**으로 유지. 원본 기획안 TXT는 직접 확인할 수 없어 사용자 제공 공식 로드맵과 기존 요구사항 기준으로 작성.

---

## 최신 작업 — 공식 97단계 Windows PyInstaller EXE (오프라인 빌드 준비, 실제 Windows 빌드 미완료)

- `packaging/windows/AI_Novel_Factory.spec` + `launcher.py`와 `scripts/build_windows_exe.py`: 기존 PySide6 GUI의 Windows one-file PyInstaller 설정 및 사전검사·독립 실행 검증 도구를 추가했다.
- **ANF-REQ-001 인수 미충족.** 현재 Linux/Python 3.13.5에는 PyInstaller·PySide6가 없어 실제 Windows `.exe`를 만들거나 실행하지 못했다. `docs/stage97_build_preflight.json`에 차단 사유를 기록한다. EXE 파일이 있다고 주장하지 않는다.
- 기존 95단계 공식 플랫폼 API 실검증과 96단계 공식 업로드 적합성 확인도 **미완료**로 유지한다. 원본 TXT는 접근 불가.
- Windows 오프라인 준비 환경에서 재현 가능한 절차: `docs/stage97_windows_exe_build.md`. 원고 확정·외부 서버·GitHub·게시/업로드 없음.

---

## 최신 작업 — 공식 96단계 플랫폼별 형식·업로드 가능성 검사 (오프라인 부분 구현)

- `platform_format_audit.py`: **사용자가 제공한 검증되지 않은** 형식 제한을 기존 메타데이터·회차별 TXT·EPUB3 파일과 비교한다. `LOCAL_DECLARED_MATCH_ONLY`는 오직 로컬 선언 규칙에 대한 일치이며 **실제 업로드 가능성과 다르다**. 모든 결과의 `actual_upload_possible`은 `UNKNOWN`으로 고정된다.
- 95단계 공식 API 규격·샌드박스 업로드는 여전히 미검증(`ANF-REQ-066` 인수 미충족). 96단계 역시 공식 플랫폼 규칙과 실제 업로드 적합성을 검증하지 않았으므로 **오프라인 부분 구현**으로 기록한다.
- 96단계에 직접 지정된 기존 ANF-REQ 번호는 없으므로 번호를 창작하지 않았다. 원본 기획안 TXT는 현재 접근 불가; 사용자가 제공한 100단계 로드맵과 누적 요구사항을 사용했다.
- 실제 게시·업로드·GitHub·외부 AI API·원격 서버 사용 없음. 원고 본문·비밀정보는 검증 보고서에 포함하지 않는다.
- 사용법과 한계: `docs/stage96_platform_format_audit.md`.

# AI Novel Factory — 95/100단계 오프라인 부분 구현 (실플랫폼 미검증)

**95단계 ANF-REQ-066 (공식 API Publisher Adapter): 인수 기준 미충족.** 89단계 실제 로컬 승인 상태 및 94단계 원고 본문/해시를 재검증한 뒤, 네트워크 없는 `LocalSandboxPublisherAdapter`로 **모의 업로드**만 수행합니다. 실제 공식 API 규격 확인, 공식 테스트 환경 업로드, 사용자 신원 인증, 외부 출판은 **하지 않았고 할 수 없습니다**. `upload_to_real_platform`은 항상 차단됩니다.

- 구현: `src/ai_novel_factory/publisher_adapter.py`; 테스트: `tests/test_stage95_publisher_adapter.py`.
- 상세 범위/제약: `docs/stage95_publisher_adapter.md`; 전체 회귀 검증: `docs/stage95_test_results.json`, `docs/stage95_verification_log.txt`.
- 원본 기획안 TXT 미확인. 사용자 제공 공식 로드맵과 기존 `docs/requirements.md`의 `ANF-REQ-066`만 사용. 외부 서버·GitHub·클라우드 모델 API 사용 금지 준수.
- Windows EXE/GUI·실제 로컬 AI·Redis/Celery·pgvector 및 실제 플랫폼 샌드박스 **미검증**. 공식 인수 완료 전에는 **95단계 미완료**, 96단계 구현을 앞당기지 않음.

---

# AI Novel Factory — 85/100단계 누적 개발본

**85단계 / ANF-REQ-050: 로컬 자동 집필 예약 및 작업 실행 이력.** `writing_scheduler.py`에 1회/시간별/일별 UTC 예약, SQLite 원자적 큐 등록, 실행/실패/재시도 감사 기록, 오프라인 누락 슬롯 건너뜀, 중복 방지를 추가했습니다. 예약 `tick`은 호출자가 실행해야 하며 실제 초고 작성은 별도 허가된 로컬 콜백을 통해서만 가능합니다. **PC가 꺼져 있을 때 자동 실행하거나 Windows OS 작업 스케줄러를 등록하는 기능은 아닙니다.**

- 소스: `src/ai_novel_factory/writing_scheduler.py`; 신규 테스트: `tests/test_stage85_writing_scheduler.py`.
- 설명: `docs/stage85_writing_scheduler.md`; 검증 기록: `docs/stage85_test_results.json`, `docs/stage85_verification_log.txt`, `scripts/stage85_partitioned_regression.py`.
- 원본 기획안 TXT는 직접 확인하지 못했으며, 공식 로드맵과 기존 ZIP의 `ANF-REQ-050` 기준으로 구현했습니다. Windows EXE/GUI·실제 로컬 LLM·Redis/Celery·pgvector 미검증. 원격 접속·원고 자동 승인·출판 없음.
- 다음 공식 단계: **86단계 — 30화 연속 생성 통합 테스트**.

---

# AI Novel Factory — 84/100단계 누적 개발본

**84단계 / ANF-REQ-049: 한 회차 확정 후 다음 회차 자동 진행.** 최신 `FINAL` 원고 버전과 호출자가 명시한 확정 확인, Story Arc·종료 회차를 검증한 뒤 다음 회차를 생성하고 오프라인 SQLite 작업 큐에 중복 없이 등록합니다. 완성된 다음 장면·컨텍스트가 제공되면 기존 70단계의 오프라인 작성 흐름을 한 번 실행해 **승인되지 않은 초고 미리보기**를 반환합니다. 종료 회차에서는 작업을 만들지 않습니다.

- 구현: `src/ai_novel_factory/episode_continuation.py`; 신규 테스트: `tests/test_stage84_episode_continuation.py`; 설명: `docs/stage84_episode_continuation.md`.
- 검증: `docs/stage84_test_results.json`, `docs/stage84_verification_log.txt`, `scripts/stage84_partitioned_regression.py` 및 회귀 테스트 실행 로그.
- 원본 기획안 TXT는 현재 첨부 파일에서 직접 확인하지 못했습니다. 사용자 제공 로드맵과 `docs/requirements.md`의 **ANF-REQ-049**를 준수했습니다.
- 호출자의 확정 확인은 독립적으로 인증하지 않습니다. `FINAL`은 출판 승인이 아니며, 자동 출판·업로드·외부 AI API 호출은 없습니다. 실제 Windows EXE/GUI·로컬 LLM·Redis/Celery·pgvector 실연동 미검증.
- 다음 공식 단계: **85단계 — 자동 집필 Scheduler/예약**.

---

# AI Novel Factory — 83/100단계 누적 개발본

**83단계: 초고·수정본·최종본 로컬 버전관리.** `src/ai_novel_factory/manuscript_versions.py`에 작품·회차별 append-only 스냅샷과 명시적 기존 원고 보존, 버전 조회·새 수정본 복원, SHA-256 무결성·낙관적 동시성 검사를 추가했습니다. 원고 버전과 회차 본문은 동일 SQLite 트랜잭션으로 저장합니다. `FINAL`은 출판 승인이나 인증된 사용자 확정이 아닙니다.

- 설명: `docs/stage83_manuscript_versions.md`; 신규 테스트: `tests/test_stage83_manuscript_versions.py`; 검증: `docs/stage83_test_results.json`, `docs/stage83_verification_log.txt`.
- 기존 82단계까지의 모든 파일과 숨김 파일을 보존했습니다. 버전 API 밖의 EpisodeStore 직접 수정은 자동 기록되지 않으며, 다음 버전 작업에서 충돌로 감지합니다.
- 원본 기획안 TXT 직접 미확인. 사용자 제공 공식 100단계 로드맵과 기존 요구사항으로 구현했습니다. 83단계에 직접 배정된 ANF-REQ ID는 기존 `docs/requirements.md`에 없습니다.
- Linux Python 회귀 테스트 기준. Windows EXE/GUI·실제 LLM·Redis/Celery·pgvector 실연동 미검증. 원격 저장소·클라우드 AI API 미사용.
- 다음 공식 단계: **84단계 — 다음 회차 자동 진행**.

---

# AI Novel Factory — 82/100단계 누적 개발본

**82단계 / ANF-REQ-058: 검토·승인된 Memory Delta를 로컬 Novel Bible DB에 반영.** 81단계 확정 원고의 주석 후보와 별도 검토 목록을 재검증한 뒤, 명시적 사용자 승인 주장이 포함된 선택 항목만 적용합니다. Character/World/Timeline에는 기존 항목을 덮어쓰지 않는 외래키 연결 사실을 저장하고, 관계·복선은 기존 회차 이력 테이블에 기록합니다. 동일 승인 재적용은 중복 기록 없이 건너뛰며 실패 시 해당 호출의 신규 변경을 모두 롤백합니다. 승인 주장은 **독립적으로 인증하지 않으며**, 원고 확정·출판 승인도 아닙니다.

- 구현: `src/ai_novel_factory/memory_application.py`; 신규 테스트: `tests/test_stage82_memory_application.py`.
- 설명: `docs/stage82_memory_application.md`; 실행·검증: `docs/stage82_test_results.json`, `docs/stage82_verification_log.txt`, `docs/stage82_*_groups.json`.
- `scripts/stage82_partitioned_regression.py`로 전체 95개 테스트 모듈을 8개 그룹에 나눠 재실행 가능. 외부 서버·GitHub·클라우드 AI API 사용 없음.
- 원본 기획안 TXT는 현재 접근 가능한 대화 첨부 목록에 없어 직접 검증하지 못함. 공식 로드맵과 기존 `docs/requirements.md` 기준. Windows EXE·GUI, 로컬 AI 모델, Redis/Celery·pgvector 실연동은 미검증.
- **다음 공식 단계: 83단계 — 초고·수정본·최종본 버전관리.**

---

# AI Novel Factory — 81/100단계 누적 개발본

**81단계 / ANF-REQ-057: 확정 원고에서 Memory Delta 검토 후보 추출·로컬 저장.** 49단계 EpisodeStore의 `final_text`와 회차 revision·SHA-256 및 **외부 호출자가 제공한 사용자 승인 주장**을 대조하고, 본문에 검토자가 명시한 `[[ANF_MEMORY|...]]` 주석으로부터 FACT/RELATIONSHIP/FORESHADOW 변경 후보를 추출합니다. 승인 주장의 진위는 아직 검증할 수 없으며 89단계 사용자 승인 게이트와 별개입니다. 자연어 전체 자동 추론 기능이 아닙니다.

- 구현: `src/ai_novel_factory/memory_delta.py`; 테스트: `tests/test_stage81_memory_delta.py`.
- 설명: `docs/stage81_memory_delta.md`; 테스트·검증: `docs/stage81_test_results.json`, `docs/stage81_verification_log.txt`.
- 검토 목록은 **별도 로컬 SQLite**에 `PENDING_HUMAN_REVIEW`로만 저장합니다. Novel Bible 및 원고는 수정하지 않으며, 원고 변경·검토 목록 위변조·다른 작품 혼입을 검증합니다. 사용자 명시 승인 없는 원고 확정·출판 금지.
- 원본 기획안 TXT 첨부파일은 이번 실행에서 직접 확인하지 못했습니다. 공식 로드맵과 누적 ZIP 요구사항을 기준으로 구현했습니다. Windows EXE·GUI·실제 LLM/Redis/Celery/pgvector 연동은 미검증. 외부 서버·GitHub·클라우드 AI API 사용 없음.
- **다음 공식 단계: 82단계 — 확정된 Memory Delta를 Character·World·Timeline 등 DB에 반영.**

---

# AI Novel Factory — 80/100단계 누적 개발본

**80단계 / ANF-REQ-056: 문제가 있는 Scene만 선택적으로 재작성·재검사.** 검토자가 표시한 원고 근거와 장면 SHA-256을 확인한 뒤 지정된 장면만 교체하며, 미선택 장면의 본문·해시·근거 사실 ID는 보존합니다. 변경된 전체 원고의 반복 표현 검사를 재실행하고, 입력이 제공되면 참고작 유사성 및 새로운 수동 Reader 지표도 재검사합니다. 모델을 자동 호출하거나 원고를 승인·확정·출판하지 않습니다.

- 소스: `src/ai_novel_factory/scene_revision.py`
- 테스트: `tests/test_stage80_scene_revision.py`
- 설명: `docs/stage80_scene_revision.md`
- 테스트·검증 기록: `docs/stage80_test_results.json`, `docs/stage80_verification_log.txt`
- **다음 공식 단계: 81단계 — 확정 원고에서 Memory Delta 자동 추출.**

---

# AI Novel Factory — 79/100단계 누적 개발본

**79단계 / ANF-REQ-055: Reader Simulation (몰입·전개·캐릭터·후킹 참고 지표).** 검토자가 원고의 각 Scene에 대해 목표·긴장·진행·인물 선택·결과·마지막 후킹을 참/거짓/미확인으로 표시하면, 검증된 Scene 위치·SHA-256 지문을 근거로 **투명한 가중 지표**를 계산합니다. 실제 독자의 감정·작품 품질을 예측하는 AI는 아닙니다. 표시가 누락된 지표는 점수 대신 `None`을 반환합니다.

- 구현: `src/ai_novel_factory/reader_simulation.py`, `reader_simulation_records.py`.
- 테스트: `tests/test_stage79_reader_simulation.py`, `tests/test_stage79_reader_simulation_records.py`.
- 설명·검증: `docs/stage79_reader_simulation.md`, `docs/stage79_test_results.json`, `docs/stage79_verification_log.txt`.
- 결과는 기본 읽기 전용이고, **명시적 호출 시에만** 원고 문장을 저장하지 않는 로컬 SQLite 참고 지표 기록을 생성합니다. 65단계 미승인 초고 Scene과 연결 가능. 승인·원고 확정·출판 없음.
- 원본 기획안 첨부파일은 이 실행에서 직접 확인하지 못했습니다. 공식 로드맵과 누적 ZIP의 `docs/requirements.md`를 기준으로 했습니다.
- Linux Python 로컬 테스트만 수행. Windows EXE/GUI, 실제 LLM 추론, Redis/Celery·pgvector 실연동 미검증. Novel Bible 우선, 참고작 원문 비복제, 사용자 승인 없는 출판 금지 및 원격/클라우드 접속 금지 유지.
- 다음: **80단계 — 문제 Scene 선택적 재작성 및 재검사**.

---

# AI Novel Factory — 78/100단계 누적 개발본

**78단계 / ANF-REQ-030: Reference Similarity Checker — 문장·장면·구조 유사성 검사.** 기존 38/39단계의 직접 복제·문단 유사성 검사에 원고-참고작 문장/장면 표면 유사성, 검토자가 지정한 추상 사건구조 비교, 등록 참고작 메타데이터 대조를 추가했습니다. 원고와 참고작 원문은 결과에 포함하지 않습니다. 비교 누락은 `inconclusive`, 유사성 발견은 `review`/`blocked`로 보고하며 법적 표절 판정이 아닙니다.

- 구현: `src/ai_novel_factory/reference_similarity_checker.py`, `reference_similarity_records.py`.
- 테스트: `tests/test_stage78_reference_similarity_checker.py`, `tests/test_stage78_reference_similarity_records.py`.
- 설명·검증: `docs/stage78_reference_similarity_checker.md`, `docs/stage78_test_results.json`, `docs/stage78_verification_log.txt`.
- 원고/참고작 지문에 결속된 **선택적 로컬 검토 기록**을 만들 수 있지만, 실제 원고 최종 확정·출판 기능은 아직 없으며 89단계 승인 게이트와의 완전한 통합은 미구현입니다. 원본 참고파일 바이트에서 추출된 텍스트의 진위 및 작품별 등록 참조목록 완전성도 호출자가 검증해야 합니다.
- Linux Python에서 로컬 테스트 수행; Windows EXE/GUI, 실제 AI 추론, Redis/Celery·pgvector 실연동은 미검증. Novel Bible 우선, 참고작 원문 비복제, 사용자 승인 없는 출판 금지 유지.
- 원본 기획안 첨부파일은 이 실행에서 직접 열지 못했으며 사용자 제공 로드맵 요약 및 ZIP 내부 요구사항을 기준으로 진행했습니다. 원격 저장소·GitHub·클라우드 API 사용 없음.
- 다음: **79단계 — Reader Simulation 몰입도·전개·캐릭터 평가**.

---

# AI Novel Factory — 76/100단계 누적 개발본

**76단계 / ANF-REQ-053: Style Checker 문체·시점 일관성 검사.** Style Bible의 명시적 금지 표현, 문장·문단 최대 글자수, 검토자가 수동 표시한 시점을 검사합니다. **Novel Bible의 동일 키가 우선**합니다. 자유형 문체 지시는 `unexamined_rules`로 보고하며 전체 자연어 분석이나 최종 품질 인증을 주장하지 않습니다.

- 구현: `src/ai_novel_factory/style_checker.py`; 테스트: `tests/test_stage76_style_checker.py`.
- 설명/검증: `docs/stage76_style_checker.md`, `docs/stage76_test_results.json`, `docs/stage76_verification_log.txt`.
- 읽기 전용 검사; 원고·설정 자동 변경, 확정·출판 없음. 참고소설 원문 미사용.
- Linux Python 로컬 검증만 수행; Windows EXE/GUI 및 실제 AI 추론 미검증, 기존 SQLite 연결 경고 남음.
- GitHub/원격 저장소/외부 서버/클라우드 AI API 사용 없음.
- 다음: **77단계 — 반복 표현과 유사 문장 사용 빈도 검사**.

---

# AI Novel Factory — 75/100단계 누적 개발본

**75단계 / ANF-REQ-052: 사건과 행동의 Logic Checker.** 검토자가 표시한 인물 동기·능력·원인·해결의 선행 전제와 원고의 행동을 이야기 속 명시적 시간순서대로 대조하고, 누락·후발·반증·동시점 불확실성을 원고 근거 위치와 해시로 보고합니다. 표시된 우연 요소는 객관적 오류 판정이 아닌 수동 검토 경고로 반환합니다.

- 구현: `src/ai_novel_factory/logic_checker.py`; 테스트: `tests/test_stage75_logic_checker.py`.
- 설명: `docs/stage75_logic_checker.md`; 결과/기록: `docs/stage75_test_results.json`, `docs/stage75_verification_log.txt`.
- **제한:** 자유서술 자동 논리 이해가 아니라 수동 근거에 대한 규칙 검사입니다. 전체 QC·자동 재작성/확정·출판 승인/출판·DB 변경 없음.
- Linux Python 환경 로컬 테스트. Windows EXE/GUI, 실제 AI 추론, Redis/Celery 실연동 미검증. 기존 SQLite 경고 남음.
- 기존 Novel Bible 우선, 참고작 원문 비복제, 출판 전 사용자 승인. 원격 저장소·외부 서버·클라우드 AI API 미사용.
- 다음: **76/100단계 — Style Checker 문체·시점 일관성 검사**.

---

# AI Novel Factory — 74/100단계 누적 개발본

**74단계 — 복선 설치·진행·회수 상태 검사.** 47단계 ForeshadowStore에 기록한 `INSTALL/REVISIT/RESOLVE/ABANDON` 사건 및 `OPEN/DEVELOPING/RESOLVED/ABANDONED` 상태를 검토자가 지정한 원고 근거와 대조하는 오프라인·읽기 전용 검사기를 추가했습니다. **자연어 자동 복선 추출/예정 회수 기한 판정은 구현하지 않았습니다.** 검사 결과는 검토용이며 원고 확정·출판 승인/출판이나 DB 변경을 수행하지 않습니다.

- 구현: `src/ai_novel_factory/foreshadow_checker.py`; 테스트: `tests/test_stage74_foreshadow_checker.py`.
- 범위/검증: `docs/stage74_foreshadow_checker.md`, `docs/stage74_test_results.json`, `docs/stage74_verification_log.txt`.
- 기존 Novel Bible 우선, 참고작 원문 비복제, 출판 전 사용자 승인 원칙 유지. GitHub·외부 서버·클라우드 AI API 사용 없음.
- Windows EXE/GUI, 실제 AI 추론 및 Redis/Celery 실연동은 미검증. 기존 SQLite 연결 `ResourceWarning` 재현.
- 다음 공식 단계: **75단계 — Logic Checker 사건과 행동의 논리 검사**.

---

# AI Novel Factory — 72/100단계 누적 개발본

**72단계: 등장인물 지식 범위 충돌 검사.** 기존 43단계 Character Knowledge의 작품별·회차별 획득·상실 이력을 **검토자가 원고에서 표시한 인물·지식 사용 근거**와 대조하여 `NOT_RECORDED`, `NOT_YET_LEARNED`, `NOT_KNOWN` 경고를 반환합니다. NLP 자유서술 자동 추론이나 완전한 품질 검사로 표시하지 않습니다.

- 구현: `src/ai_novel_factory/knowledge_checker.py`; 테스트: `tests/test_stage72_knowledge_checker.py`.
- 상세/검증: `docs/stage72_knowledge_checker.md`, `docs/stage72_test_results.json`, `docs/stage72_verification_log.txt`.
- `docs/requirements.md`에는 72단계 직접 매핑 ID가 없습니다. 43단계 `ANF-REQ-033`의 지식 DB를 연결한 로드맵 72단계 구현입니다.
- 결과는 읽기 전용이고 인물 비밀·원고 원문을 보고서에 넣지 않으며, 승인 없는 원고 저장·출판은 없습니다.
- GitHub·외부 서버·클라우드 AI API 사용 없음. Windows EXE/GUI와 실제 AI 의미 품질은 미검증입니다.
- 다음 공식 단계: **73단계 — Timeline 날짜·시간·사건 순서 검사**.

---

# AI Novel Factory — 71/100단계 누적 개발본

**71단계 ANF-REQ-051: Continuity Checker 설정·인물 일관성 검사.** 기존 Novel Bible/Character/World DB의 사용자 작성 설정에 대해 **원고에서 검토자가 명시적으로 표시한 주장값과 실제 원고 범위**를 대조하고, 충돌 시 위치·출처·SHA-256 근거를 포함한 경고를 반환합니다. 실제 자연어 의미 자동 추출이나 전체 품질 검사로 취급하지 않습니다.

- 구현: `src/ai_novel_factory/continuity_checker.py`; 테스트: `tests/test_stage71_continuity_checker.py`.
- 설명/검증: `docs/stage71_continuity_checker.md`, `docs/stage71_test_results.json`, `docs/stage71_verification_log.txt`.
- 기존 65/70단계 미승인 회차 초고를 검사하는 읽기 전용 어댑터 포함. 자동 수정, canon 변경, 원고 확정·출판 없음.
- 모든 테스트는 로컬에서 수행. Windows EXE/GUI, 실제 언어모델 추론, Redis/Celery 실연동 미검증. 참고소설 원문 복제 금지·Novel Bible 우선·출판 전 사용자 승인 유지.
- 다음 공식 단계: **72단계 — 인물 지식 범위 충돌 검사**.

---

# AI Novel Factory — 70/100단계 누적 개발본

**70단계: 한 회차 자동 집필 통합 테스트.** 오프라인 모의 모델을 이용한 한 회차의 계획·장면 작성·결합·기초 검사·사용자 검토 대기 흐름을 기존 로컬 작업큐에 연결하고, 69단계 체크포인트의 재시도·변조 차단을 통합 테스트로 확인했습니다. 작업 `COMPLETED`는 원고 승인·저장·출판 성공이 아닙니다.

- 구현: `src/ai_novel_factory/episode_integration.py`; 테스트: `tests/test_stage70_one_episode_integration.py`.
- 독립 실행 예시: `PYTHONPATH=src python scripts/stage70_one_episode_smoke.py`.
- 기록: `docs/stage70_single_episode_integration.md`, `docs/stage70_test_results.json`, `docs/stage70_verification_log.txt`.
- 실제 AI 모델의 소설 창작 품질, 전체 품질 검사, Redis/Celery 실연동, Windows EXE/GUI 미검증. 기존 SQLite 연결 경고 남음.
- 원고는 큐에 저장하지 않고 사람 검토 대기로 종료. GitHub·외부 서버·클라우드 AI API 미사용. 참고작 원문 비복제·Novel Bible 우선·출판 전 사용자 승인 유지.
- 다음은 **71단계 — Continuity Checker 설정·인물 일관성 검사**.

---

# AI Novel Factory — 68/100단계 누적 개발본

**68단계: 집필 진행률·일시정지·취소 화면 (ANF-REQ-004).** 기존 SQLite 로컬 작업큐에 상태·진행률·협력적 일시정지/취소 기능 및 Episodes UI의 진행률 탭을 추가했습니다. 진행 중인 작업을 강제로 정지하지 않으며 안전 지점의 핸들러 협력이 필요합니다. 모의/로컬 처리 상태는 원고 승인 및 출판을 의미하지 않습니다.

- 소스: `src/ai_novel_factory/task_monitor.py`, `src/ai_novel_factory/desktop/task_monitor_widget.py`, 기존 `local_task_queue.py`와 `desktop/app.py` 보강.
- 테스트·상세: `tests/test_stage68_task_monitor.py`, `docs/stage68_task_monitor.md`, `docs/stage68_test_results.json`, `docs/stage68_verification_log.txt`.
- 오프라인 로컬 SQLite만 테스트. Redis/Celery 실연동, 실제 GUI(PySide6 미설치), Windows EXE, 실제 LLM 추론은 검증하지 않음. 참고작 원문 비복제·Novel Bible 우선·출판 전 사용자 승인 유지.
- 다음: **69/100 — API 실패 재시도 및 작업 체크포인트 저장**.

---

# AI Novel Factory — 65/100단계 누적 개발본

**65단계 — 여러 Scene을 하나의 회차 초고로 결합.** 기존 64단계 미확정 장면 초고를 장면 계획 순서대로 합치고 누락·중복·작품/회차 혼합·원고 해시 변조·Novel Bible 출처 차이·제공자 혼용을 검사합니다. 결과는 **메모리 전용 미승인 회차 초고**이며 자동 저장·유사성 검사·출판은 하지 않습니다.

- 구현: `src/ai_novel_factory/episode_assembler.py`, 테스트: `tests/test_stage65_episode_assembler.py`.
- 설명/검증: `docs/stage65_episode_assembly.md`, `docs/stage65_test_results.json`, `docs/stage65_verification_log.txt`.
- 전체 회귀 테스트: `PYTHONPATH=src python -m unittest discover -s tests -q`.
- 참고작 원문 비복제, Novel Bible 우선, 출판 전 사용자 승인 원칙 유지. 외부 서버·클라우드 AI API·GitHub 사용 없음.
- Windows EXE와 실제 AI 모델·GUI 검증 미수행. 다음 단계: **66/100 — Planner·Writer·Checker 제어 Orchestrator 개발**.

---

# AI Novel Factory — 64/100단계 누적 개발본

**64단계: 장면 단위 소설 초고 생성(로컬 모델 계약 연동).** 63단계 Novel Bible 우선 프롬프트와 61단계 모의/로컬 실행형 모델 인터페이스를 연결하여 장면 하나의 **검토용·미저장 초고**를 생성합니다. 로컬 실행 파일은 생성 시 승인과 실행 호출 시 재승인이 필요합니다. 임의 제공자 차단, 작품/회차/장면 확인, 출처 필터링, 초고 지문 및 원점 표시를 포함합니다.

- 구현: `src/ai_novel_factory/scene_writer.py`; 테스트: `tests/test_stage64_scene_writer.py`.
- 설명/검증: `docs/stage64_scene_writer.md`, `docs/stage64_test_results.json`, `docs/stage64_verification_log.txt`.
- 검증 명령: `PYTHONPATH=src python -m unittest discover -s tests -q`.
- 실제 AI 소설 창작 품질은 검증되지 않았습니다. 승인된 외부 실행 파일의 자체 네트워크 동작을 강제 격리하지 못합니다. 파일·DB 저장 및 출판 승인/출판은 수행하지 않습니다.
- 참고작 원문 비복제·Novel Bible 우선·출판 전 사용자 승인 원칙 유지. GitHub, 외부 서버, 클라우드 AI API 사용 없음.
- 다음 단계: **65/100 — 여러 장면을 하나의 회차 초고로 결합**.

---

# AI Novel Factory — 49/100단계 누적 개발본

**ANF-REQ-039: 회차별 플롯·장면·초고·확정본·요약·수동 검사 기록을 로컬 SQLite에 저장하고 재시작 후 복원.** 작품별 회차 저장·수정·삭제, 장면 순서, 수정 버전 충돌 차단, 수동 검사 기록 및 이후 원고 변경에 따른 검사 결과 구버전 표시를 제공합니다.

- 구현: `src/ai_novel_factory/database/episodes.py`, `episode_cli.py`.
- 설명: `docs/stage49_episodes.md`; 검증: `docs/stage49_test_results.json`, `docs/stage49_verification_log.txt`.
- CLI: `PYTHONPATH=src python -m ai_novel_factory.database.episode_cli --help`.
- 저장된 회차 본문은 **로컬 SQLite 평문**이며 CLI 기본 출력은 비노출입니다. `--reveal`로만 본문을 로컬 출력합니다.
- 검사 기록은 **사용자가 명시적으로 등록하는 수동 기록**입니다. 자동 AI 품질 검사나 참고작 원문 유사성 자동 검사를 의미하지 않습니다.
- 확정본 저장은 출판 승인과 다르며, 조회 JSON은 `publication_approved: false`를 명시합니다. 자동 집필·출판·Windows EXE는 미구현입니다.
- 참고작 원문 자동 복사 없음, Novel Bible 우선, 사용자 승인 없는 출판 금지. GitHub/외부 서버/클라우드 AI API 사용 없음.
- 다음 단계: **50/100 — 실제 기획서에서 범위 확인 후 진행**.

---

# AI Novel Factory — 48/100단계 누적 개발본

**ANF-REQ-038: Style Bible 저장 및 생성 컨텍스트 반영.** 사용자 작성 작품별 문체 규칙을 기존 Novel Bible SQLite에 저장하고, 구조화된 오프라인 생성 컨텍스트에 반영합니다. 충돌 우선순위는 Novel Bible > Style Bible > 익명 참고 통계이며, 두 Bible 중 하나라도 비어 있으면 컨텍스트를 생성하지 않습니다.

- 구현: `src/ai_novel_factory/database/style_bible.py`, `style_cli.py`.
- 문서: `docs/stage48_style_bible.md`; 검증: `docs/stage48_test_results.json` 및 `docs/stage48_verification_log.txt`.
- CLI: `PYTHONPATH=src python -m ai_novel_factory.database.style_cli --help`.
- 전체 테스트: `PYTHONPATH=src python -m unittest discover -s tests -q`.
- 문체 지시문은 **로컬 DB 평문 저장**이며 CLI는 기본적으로 내용을 표시하지 않습니다.
- 참고작 원문 비복제, Novel Bible 우선, 사용자 승인 없는 출판 금지를 유지합니다. 실제 AI Writer·Windows EXE·출판 워크플로는 미구현입니다. GitHub·외부 서버·클라우드 AI API 사용 없음.
- 다음 단계: **49/100 ANF-REQ-039 회차별 플롯·장면·초고·확정본·요약·검사 기록 저장**.

---

# AI Novel Factory — 47/100단계 누적 개발본

**ANF-REQ-037: 복선 설치·재언급·회수·폐기 상태 관리.** 사용자가 작성한 복선과 회차별 기록을 로컬 SQLite에 저장합니다. 설치=OPEN, 재언급=DEVELOPING, 회수=RESOLVED, 폐기=ABANDONED이며, 종료 이후 재언급·회수·폐기를 거부합니다. 사건은 회차순(같은 회차는 입력순)으로 검사하며 잘못된 변경은 트랜잭션 롤백합니다. 설치 전 회차는 NOT_INSTALLED로 반환합니다.

- 구현: `src/ai_novel_factory/database/foreshadow.py`, `foreshadow_cli.py`.
- 문서: `docs/stage47_foreshadow.md`; 테스트: `docs/stage47_test_results.json`.
- 로컬 CLI: `PYTHONPATH=src python -m ai_novel_factory.database.foreshadow_cli --help`.
- 회귀 테스트: `PYTHONPATH=src python -m unittest discover -s tests -q`.
- 사용자 작성 제목·메모는 로컬 DB에 평문으로 저장됩니다. 참고소설 원문 자동 저장·외부 서버·클라우드 AI API·GitHub 접속·출판은 없습니다.
- Novel Bible 우선, 참고작 비복제, 출판 전 사용자 승인 원칙 유지. 자동 집필·Windows EXE·출판 워크플로는 아직 미구현/미검증입니다.
- 다음 단계: **48/100 ANF-REQ-038 작품 고유 문체 규칙을 Style Bible에 저장**.

---

# AI Novel Factory — 46/100단계 누적 개발본

**ANF-REQ-036: 주요 사건의 날짜·상대시간 및 상충되는 사건 순서 검출.** 사용자가 직접 입력한 주요 사건을 작품별 로컬 SQLite에 저장하며, ISO 날짜·시간대 포함 날짜시간·다른 사건으로부터의 상대 분 단위 시간과 명시적 선후관계를 관리합니다. 상대 참조 순환, 선후관계 순환, 동시 사건의 엄격한 선후관계 및 전이적으로 불가능한 날짜 순서를 검출하고 **충돌하는 변경은 롤백**합니다. 날짜만 있는 사건은 시각을 추정하지 않으며, 미정 사건은 미해결로 표시합니다.

- 구현: `src/ai_novel_factory/database/event_timeline.py`, `event_cli.py`.
- 설명: `docs/stage46_event_timeline.md`; 검증: `docs/stage46_test_results.json`.
- 로컬 CLI: `PYTHONPATH=src python -m ai_novel_factory.database.event_cli --help`.
- 누적 회귀 테스트: `PYTHONPATH=src python -m unittest discover -s tests -q`.
- 기존 Novel Bible 우선·참고작 원문 비복제·출판 전 사용자 승인 원칙을 유지합니다. 실제 자동 집필, Windows EXE 및 출판 워크플로는 아직 미구현/미검증입니다. GitHub/원격 서버/클라우드 AI API를 사용하지 않습니다.
- 다음 단계: **47/100 ANF-REQ-037 복선 설치·재언급·회수·폐기 상태 관리**.

---

# AI Novel Factory — 45/100단계 누적 개발본

**ANF-REQ-035: 인물 관계 변화를 회차별로 저장**하는 오프라인 Novel Bible SQLite 모듈을 추가했습니다. 인물 두 명의 공유된 관계를 회차별로 기록하고 과거/현재 시점에서 조회합니다. 상세 설명: `docs/stage45_relationship_timeline.md`. 테스트: `docs/stage45_test_results.json`.

`PYTHONPATH=src python -m unittest discover -s tests -q`로 전체 회귀 테스트를 실행할 수 있습니다. `python -m ai_novel_factory.database.relationship_cli --help`로 로컬 CLI를 확인할 수 있습니다. 기존 참고 원문 비복제 기능과 Novel Bible 우선 원칙을 유지하며, 자동 집필·출판·Windows EXE는 아직 구현되지 않았습니다. GitHub/외부 서버/클라우드 AI API 사용 없이 개발합니다.

---

# AI Novel Factory — 44/100단계 (오프라인 누적 소스)

**44단계: 세계관·조직·지역·능력·아이템 저장 (ANF-REQ-034).** 43단계
Novel Bible 작품별 로컬 SQLite에 다섯 종류의 사용자 작성 세계관 항목을 저장하고
32자리 식별자로 조회·수정·삭제한다. 수정/삭제는 revision 확인이 필수이며
작품별 격리, 삭제 연쇄, 기본 비노출 CLI를 제공한다.

- 구현: `src/ai_novel_factory/database/world_canon.py`, `world_cli.py`.
- 설명: `docs/stage44_world_canon.md`, 검증: `docs/stage44_test_results.json`.
- 사용자 작성 설정은 로컬 DB에 **평문 저장**된다. 참고소설 원문 자동 복사 없음.
- 기존 Novel Bible 우선 규칙·원문 비복제 검사 유지. 실제 Writer 연결/출판 기능 없음.
- GitHub·원격 서버·클라우드 AI 사용 없음. Windows 실기기/EXE/Python 3.12 미검증.
- 다음: 45/100 — 인물 관계 변화 시간별 저장 (ANF-REQ-035).

---
# AI Novel Factory — 43/100단계 (오프라인 누적 소스)

**43단계: 인물별 지식 범위를 회차별로 관리 (ANF-REQ-033).** 42단계
Novel Bible 인물 설정과 같은 SQLite에 작품별 지식 사실과 인물·회차별
앎/모름 이벤트를 저장한다. 회차 이전/이후 지식 변화, 망각, 재학습을
구분하며 인물이 모르는 사실 ID를 사용한 장면 검사는 오류로 처리한다.

- 구현: `src/ai_novel_factory/database/character_knowledge.py`, `knowledge_cli.py`.
- 설명: `docs/stage43_character_knowledge.md`, 검증: `docs/stage43_test_results.json`.
- **원고 자유 텍스트의 자동 의미 이해는 아직 불가능하다.** 검사 시 사용한 사실 ID를
  명시적으로 제공해야 하며, 오류 결과는 자동 출판 허가가 아니다.
- 사실 내용은 사용자가 직접 작성하고 로컬 SQLite에 **평문** 저장한다.
- GitHub/외부 서버/클라우드 AI 사용 없음. Windows 실기기/EXE/Python 3.12 미검증.
- 다음: 44/100 — 세계관·조직·지역·능력·아이템 저장 (ANF-REQ-034).

---
# AI Novel Factory — 42/100단계 (오프라인 누적 소스)

**42단계: 인물의 성격·목표·말투·비밀 저장 (ANF-REQ-032).** 41단계
Novel Bible 작품별 로컬 SQLite에 인물 생성·조회·목록·수정·삭제, 버전 충돌 방지,
작품별 격리, 기본 비노출 CLI를 추가했다. 직접 입력한 인물 설정은 로컬 DB에
**평문** 저장되며 참고작 원문을 자동 복사하지 않는다.

- 구현: `src/ai_novel_factory/database/characters.py`, `character_cli.py`.
- 사용법: `docs/stage42_characters.md`, 테스트: `docs/stage42_test_results.json`.
- 기존 Novel Bible 규칙 우선 원칙 유지. 인물 지식·관계·AI Writer 연결은 아직 없음.
- GitHub·원격 서버·클라우드 AI 사용 없음. Windows 실기기/EXE/Python 3.12 미검증.
- 다음 단계: 43/100 — 인물별 지식 범위 회차 관리 (ANF-REQ-033).

---
# AI Novel Factory — 41/100단계 (오프라인 누적 소스)

**41단계: Novel Bible 최우선 설정 저장(ANF-REQ-031).** 40단계 누적 ZIP을
압축 해제해 기존 1,030개 테스트(1,019 통과·11 건너뜀)를 재검증한 뒤
사용자 작품별 로컬 SQLite Novel Bible 저장소, 규칙 버전 관리, 참고 통계보다
사용자 설정을 우선하는 충돌 해결, 원문/설정 비노출 CLI를 추가했다.

- 소스: `src/ai_novel_factory/database/novel_bible.py`, `novel_bible_cli.py`.
- 문서: `docs/stage41_novel_bible.md`, 검증 기록: `docs/stage41_test_results.json`.
- 사용자가 직접 입력한 Novel Bible 텍스트는 로컬 DB에 **평문 저장**된다.
  참고작 원문·인용을 이 DB에 자동 저장하지 않는다. 집필·출판 기능은 아직 없다.
- GitHub·원격 서버·클라우드 AI 연결 없음. Windows 실기기/EXE/Python 3.12
  검증은 별도로 필요하다. 다음 계획: 42단계 인물 성격·목표·말투·비밀 저장.

---
# AI Novel Factory — 40/100단계 (오프라인 누적 소스)

**40단계: 참고소설 분석 통합 테스트 및 누적 ZIP 패키징 검증.** 39단계
ZIP을 별도 폴더에 풀어 확인하는 과정에서 누락된 `.gitignore` 때문에
기존 테스트 3개가 오류를 내는 문제를 발견해 복구했다.

- 신규 실제 통합 테스트 **28개**: TXT/Markdown/DOCX/PDF 가져오기, 6개 합성
  참고작의 SQLite 프로필·장르 패턴·강도·요소 선택·검색·사용 기록,
  비복제/유사성 게이트 및 오류 시 차단을 종단 간 확인.
- 신규 ZIP 검증 테스트 **14개** 및 `scripts/verify_release_bundle.py`:
  `.gitignore` 포함 여부, 파일 누락·손상·경로 탈출·개인 DB/비밀 파일 혼입 방지.
- **최종 압축 해제본 검증:** 1030개 중 1019개 통과, 11개 건너뜀, 실패·오류 0개.
  ZIP 검증·스모크·의존성·컴파일 검사 통과(Python 3.12 버전 경고).
- 자세한 실행/한계: `docs/stage40_reference_analysis_integration.md`;
  실행 결과: `docs/stage40_test_results.json`.
- 사용자 원문·GitHub·외부 서버·클라우드 AI 미사용. 테스트에 쓰인 문장은
  합성 문장이고 임시 폴더에서 생성 후 삭제된다.
- **아직 미완성:** 로컬 LLM Writer, Novel Bible 전체 기능, Windows EXE,
  Windows 실기기 GUI, Python 3.12 타깃 검증, 자동 출판. 사용자 승인 없는 출판 금지.
- 다음 단계는 **41/100단계**로, 이후 기획서에서 정확한 명칭을 확인해야 한다.

---
# AI Novel Factory — 39/100단계 (PC 오프라인 누적 개발본)

**39단계: 문단 단위 유사성 검사 기준선**. 38단계의 장문 원문 일치 보호를 유지하고, 정규화 5문자 shingle 기반 Jaccard/포함률 문단 비교를 추가했다.

- TXT/Markdown/DOCX/PDF 원고와 사용자가 선택한 참고작을 로컬 CLI에서 비교하며 결과에는 원문이나 발췌가 아닌 수치/문단 번호만 출력한다.
- 기준선 초과는 `review` 상태로 사용자 검토가 필요하다. 긴 직접 일치는 `blocked`, 비교 근거 부족은 `inconclusive`로 표시하고 자동 사용을 허용하지 않는다.
- **원문/유사도 결과 저장 없음**, 인터넷·GitHub·외부 서버·클라우드 AI 호출 없음.
- 실행 예시: `python -m ai_novel_factory.references.similarity_cli --draft draft.txt --reference source.txt`
- 자세한 내용: `docs/stage39_similarity_baseline.md`; 테스트 기록: `docs/stage39_test_results.json`.
- 의미 기반 독창성·표절·저작권의 최종 판정이 아니며 실제 Writer 연결/Windows EXE는 아직 미개발/미검증. 다음 단계: 40/100 참고 분석 통합 테스트.

---
# AI Novel Factory — 38/100단계 (PC 오프라인 누적 개발본)

**38단계: 원문 비복제 보호 게이트** 구현. 기존 37단계 누적 소스와 기능·SQLite 데이터를 변경하지 않고 다음을 추가했다.

- 후보 원고와 사용자가 제공한 참고 원문의 **연속 문자 직접 일치**를 로컬 메모리에서만 확인. Unicode NFKC, 대소문자·공백·문장부호 차이를 통일한다.
- 96자 이상 일치 **차단**, 48자 이상 **검토**, 16~47자 짧은 참고작의 전부 복제 **검토**. 자동 사용 게이트 `require_copy_safe_draft`는 검토·차단·검사 오류 시 통과시키지 않는다.
- TXT/Markdown/DOCX/PDF용 CLI `python -m ai_novel_factory.references.copy_protection_cli --draft ... --reference ...`; 네트워크·DB·파일 기록 없음. 결과에 원문/발췌/제목/경로를 저장·표시하지 않는다.
- **한계:** 지정된 원문에 대한 정확한 장문 중복만 검출하며, 변형·요약·번역·서사 유사성·저작권 적법성은 확인하지 않는다. 실제 Writer가 아직 없으므로 자동 출고 경로에 통합한 것은 아니다.
- 테스트 결과 및 한계 `docs/stage38_noncopy_protection.md`, `docs/stage38_test_results.json`.
- GitHub와 외부 서버의 실행 의존 없음. Windows 실기기/EXE 미검증, 프로젝트 Python 3.12 검증 미실시. 다음 단계: 39/100 유사성 검사 기준선.

---
# AI Novel Factory — 37/100단계 (PC 완전 로컬 누적 개발본)

- 신규 구현: **통계 패턴 사용 기록 관리**. 사용자 수동 선택 시 장르/선택 요소를 SQLite에 기록, 검색·열람 시 자동 기록하지 않음.
- 과거 기록은 보존하고 기존 참고작 구성·가중치·수치 등이 달라진 기록은 **재검토 필요** 상태로 표시. 특정 기록만 삭제 가능.
- 화면 버튼 및 `usage-add/list/show/delete` CLI 추가. 원문·인용·인물명·파일명·경로·자유 입력 텍스트 비저장.
- GitHub 연결, 외부 서버, 유료 AI API 없음. 로컬 Python·SQLite만으로 동작.
- 실제 자동 테스트 **886개 중 875개 통과, 11개 건너뜀, 실패 0개**. 스모크·의존성·컴파일 검사 통과.
- 사용법: `docs/stage37_pattern_usage.md`; 테스트 기록: `docs/stage37_test_results.json`.
- 아직 Windows 실기기 GUI·EXE 미검증, 로컬 AI 집필 미구현. 다음 단계: 38/100 원문 비복제 보호.

---

# AI Novel Factory — 36/100단계 (완전 로컬 누적 개발본)

- 신규 개발: **관련 통계 패턴 검색**. 사용자 지정 1~6개 참고 요소만 이용해 같은 가중치의 다른 장르 통계 패턴을 비교하고 근접도순으로 표시.
- 안전성: 참고작 2개 이상 및 단일 작품 비중 60% 이하 규칙을 후보별로 재검증. 오래된 패턴 및 편중된 후보 제외. 원문·파일명·고유 표현·검색 기록은 저장하지 않음.
- 명령줄 `pattern-related` 및 PySide6 참고작 화면의 수동 검색 버튼 추가. **SQLite, PC 단독, GitHub·외부 서버·클라우드 AI 불필요.**
- 수치는 단순 정규화 거리이며 서사 내용 이해, 집필 모델의 추천이나 작품 적합성 증거가 아님.
- 실제 테스트: 전체 **845개 중 835개 통과, 10개 건너뜀, 실패 0개**. 신규 42개 중 41개 통과/GUI 1개 건너뜀. 스모크·의존성 정책 검사 통과.
- 사용법 `docs/stage36_related_pattern_search.md`, 검증 기록 `docs/stage36_test_results.json`.
- Windows GUI 및 EXE 미검증, 로컬 AI 집필 미구현. 다음 단계: 37/100 패턴 사용 기록.

---

# AI Novel Factory — 35/100단계 (완전 로컬 누적 개발본)

- 신규 개발: 참고 요소 6개 중 사용자가 원하는 통계 항목 1~6개를 선택, SQLite에 저장, 재조회·초기화.
- 장르 패턴·참고작 강도 안전 기준(2개 이상 참여·단일 참고작 60% 이하)을 매번 확인하여 오래되거나 편중된 구성을 거부합니다.
- 명령줄 `elements-save/show/list/delete` 및 PySide6 참고작 화면 버튼 추가 (화면 실기기 테스트 미진행).
- 원문·문체 재현·원고 생성 없음. GitHub 연결 없음. 로컬 SQLite와 표준 Python만 사용.
- 실제 테스트: `docs/stage35_test_results.json`; 사용법: `docs/stage35_reference_element_selection.md`.
- 아직 Windows EXE 빌드와 로컬 AI Writer 기능 미구현. 다음 단계: 36/100 관련 패턴 검색.

---

# AI Novel Factory — 34/100단계 (로컬 전용 누적 개발본)

- 신규 개발: 참고 작품별 통계 패턴 강도 설정 0~100 및 오프라인 SQLite 저장·조회·초기화.
- 저장된 장르 레시피와 프로필에서 실효 영향 비율을 계산하고 60% 초과 집중/2개 미만 참여를 경고하는 미리보기.
- 명령줄 `strength-set/show/list/reset/preview` 및 참고작 PySide6 화면 조작 위젯 추가.
- 참고작 원문·파일명·작가명·원문 문구를 강도 DB/보고서에 저장하지 않음. 자동 집필·작가 문체 모방 없음.
- GitHub, 원격 DB, 원격 AI API 없이 **PC 안에서만 실행**. 실제 EXE 빌드 및 Windows GUI 검증은 아직 미완료.
- 검증: `docs/stage34_test_results.json`, 설명: `docs/stage34_pattern_strength.md`.

---

# AI Novel Factory — 33/100단계, 오프라인 Reference Pattern Library

32단계 누적 개발본을 기반으로 **로컬 SQLite에 저장한 장르 패턴을 검색·선택·비교하는 기능**을 추가했습니다.

- `references/pattern_library.py`: 장르 이름/코드/가중치 검색, 현재/변경됨 상태, 페이지 구분, 저장 패턴 상세·서로 다른 장르 2~12개 비교.
- `profile_cli.py`: `pattern-list`, `pattern-show`, `pattern-compare` 명령 추가.
- `desktop/reference_profile_browser.py`: 패턴 검색어 입력, 목록·상세·복수 선택 비교 버튼 추가(Windows GUI 실기기 미검증).
- DB에 새 원문 저장 테이블을 만들지 않고 **32단계 저장 선정 정보를 재사용**합니다. 원문 없이 통계만 재계산하며, 오래된 패턴은 재구축을 요구합니다.
- **GitHub, 외부 서버, 클라우드 AI 사용 없음.** 기존 저장소/작품 원문에 대한 읽기 이외 외부 작업은 하지 않습니다.
- 로컬 회귀 테스트: **716개 중 709개 통과, 7개 건너뜀, 실패 0개**. 신규 54개 중 53개 통과/GUI 1개 건너뜀.
- 사용법: `docs/stage33_pattern_library.md`, 검증 기록: `docs/stage33_test_results.json`.
- Windows EXE 빌드·실행 및 로컬 AI를 통한 실제 집필 기능은 아직 완료되지 않았습니다.
- 다음 개발: **34/100 — 참고 작품별 패턴 강도**.

---

# AI Novel Factory — 32/100단계, 로컬 Genre Pattern 구축

**실제 소스 + 자동 테스트 포함:** 31단계 누적 ZIP을 기반으로, 사용자가 명시적으로 지정한 장르별로 2~50개의 Reference Profile을 통합 분석하는 코드와 PC 로컬 SQLite 장르 선정 저장 기능을 추가했습니다.

- `genre_patterns.py`: 대사/서술·문장길이·어휘 다양도·감정 어휘·말미 단서·사건 어휘 밀도에 대한 장르별 관찰 범위/평균/표준편차, 5구간 곡선 포함.
- `database/genre_patterns.py`: 장르와 참고작 ID만 SQLite에 저장. 분류가 바뀌면 재구축을 요구하고, 기존 프로필 수치가 바뀌면 재집계.
- `profile_cli.py`: 장르 지정/해제, 구축, 재조회, 목록·삭제. 선택형 PySide6 UI에도 장르 버튼을 추가.
- **외부 서버/GitHub 실행·업로드·커밋·병합 없음.** 로컬 PC에서 통계 처리. 기존 외부 서비스용 미사용 선택 의존성 정리는 별도 후속 작업.
- **원문을 사용한 스타일 복제나 실제 서사 의미 분석 아님.** 현재는 통계 기반 참고 패턴.
- 테스트: `docs/stage32_test_results.json`, 사용법: `docs/stage32_genre_patterns.md`.
- 실제 Windows EXE 및 로컬 AI 집필은 아직 미구현, Windows GUI 실기기 검증도 보류.

---

# AI Novel Factory — 31/100 다수 참고작 프로필 통합 (오프라인)

30단계의 로컬 SQLite 프로필을 2~50개까지 선택하여 **원문 없이 통합 통계**를 비교합니다.
참고작 균등/글자 수 가중 평균, 수치 편차, 회차 위치별 5구간 변화, 사건·말미 단서 후보의
누적량을 제공합니다. 이 분석은 통계 지표일 뿐 유사 문체 복제나 서사 의미 이해가 아닙니다.

- 분석 엔진: `src/ai_novel_factory/references/profile_collection.py`
- 오프라인 CLI: `python -m ai_novel_factory.references.profile_cli --database <로컬DB> compare <ID1> <ID2> [--weighting characters]`
- 선택형 GUI: 저장 프로필 2~50개를 다중 선택 후 `선택한 작품들 통합 비교` 버튼
- 문서: `docs/stage31_multi_reference_profiles.md`
- 검증: `docs/stage31_test_results.json`
- DB/파일시스템 원문 비저장, GitHub 사용 없음, 외부 서버/AI API 사용 없음, 예약 작업 없음.
- 실제 Windows EXE와 로컬 LLM 집필 기능은 아직 완성되지 않았음.
- 다음은 **32/100단계 Genre Pattern 구축**.

---

# AI Novel Factory — 30/100 Reference Profile 저장·조회·표시 (완전 로컬)

29단계 오프라인 아키텍처 수정본을 이어받아 **원문 없는 분석 프로필**을 기존
SQLite 참고작 목록에 저장하고 CLI/선택형 PySide6 화면에서 확인하는 기능을 구현했습니다.
GitHub 서버, 원격 DB, 클라우드 API, 예약 작업, 자동 출판에 의존하지 않습니다.

- 저장: `src/ai_novel_factory/database/reference_profiles.py`
- 분석: `src/ai_novel_factory/references/reference_profile.py`
- 오프라인 일회성 가져오기: `src/ai_novel_factory/references/profile_pipeline.py`
- CLI: `python -m ai_novel_factory.references.profile_cli --help`
- GUI: 참고소설 선택 화면 아래에 `선택한 파일 분석·저장` / `저장된 프로필 새로고침` 버튼 추가
- 문서: `docs/stage30_reference_profiles.md`
- 검증 기록: `docs/stage30_test_results.json`

실제 Windows EXE와 로컬 LLM 의미 분석은 **아직 구현되지 않았습니다**.
다음 개발: 31/100단계 다수 참고작의 Reference Profile 통합.

---

# 로컬 PC 독립 실행 설계 정정 — 2026-10-12

**GitHub는 서버가 아닙니다.** 사용자는 소스 파일을 저장/병합하라고 했을 뿐
프로그램의 서버로 사용할 것을 요구하지 않았습니다. 이 개발본은 PC 단독 작동을
최우선 계약으로 지정합니다. 실행 단계에서 외부 서버/유료 AI API/GitHub를
요구해서는 안 됩니다. **실제 AI 집필과 Windows EXE는 아직 미완성입니다.**

- 설계 검증: `docs/architecture_decisions.json`, `src/ai_novel_factory/architecture.py`
- 로컬 환경 강제: `src/ai_novel_factory/settings.py`
- 추가 회귀 테스트: `tests/test_offline_runtime_policy.py`
- 정정 근거와 제한: `docs/OFFLINE_RUNTIME_AUDIT.md`

---

# AI Novel Factory — 대화 전용 오프라인 개발본 (29/100단계)

- 신규 `style_statistics.py`: 문장·문단 길이 분포, 토큰 다양도·반복 비율, 문장부호·문자 종류 통계.
- 공개 API: `analyze_style_text`, `analyze_reference_style`. 참고소설 제목·어휘·원문 반환/저장 없음.
- 신규 자동 테스트 55개 통과, 전체 510개(507개 통과/3개 건너뜀/실패 0개). 스모크 필수 통과.
- 문서: `docs/stage29_style_statistics.md`; 기록: `docs/stage29_test_results.json`.
- Python 3.13에서 검사했으며 프로젝트 권장 Python 3.12와 Windows EXE 검증은 미완료.
- GitHub 연결/커밋/PR/업로드/병합, 예약 자동화 사용 없음.
- 다음 단계: **30/100 Reference Profile 저장 및 표시**.

---

# AI Novel Factory — 대화 전용 오프라인 개발본 (28/100단계)

- 신규 `foreshadow_emotion.py`: 복선/공개 단서, 긍정/부정 감정 어휘와 5구간 감정곡선 **참고 지표**
- 텍스트 API: `analyze_foreshadow_emotion_text`; 회차별 분석 API: `analyze_reference_foreshadow_emotion`
- 신규 자동 테스트 45개, 누적 전체 455개 중 통과 452개/건너뜀 3개/실패 0개
- 문서: `docs/stage28_foreshadow_emotion.md`; 검증기록: `docs/stage28_test_results.json`
- GitHub 및 예약 연동 없음. 로컬·오프라인 분석, 원문 데이터 및 맞은 표현 저장/외부 전송 없음.
- **실제 의미적 복선 연결 및 감정 판단은 아직 미구현**. 다음 단계: 29/100 문체 통계 분석.

---

# AI Novel Factory — 대화 전용 오프라인 개발본 (27/100단계)

**2026-10-12 사용자 요청 변경:** GitHub 동기화/조회/업로드/PR/병합 및 예약 작업을 사용하지 않습니다.
개발 결과는 이 대화에 첨부한 ZIP 파일로 전달하며, Git 원격 저장소는 업데이트하지 않습니다.
빌드된 Windows EXE가 아니고, 사용자 PC에 아무것도 설치하지 않았습니다.

27단계 관계 변화 **단서 후보** 분석을 구현했습니다. 동일 문장 내 인물명 공동 언급,
지지·갈등 관련 고정 어휘의 회차별 빈도 및 두 연속 회차 간 신호 차이를 계산합니다.
실제 인물 관계의 성립·개선·악화를 판정하지 않습니다. API·네트워크 요청·원문 저장 없음.

- 소스: `src/ai_novel_factory/references/relationship_changes.py`
- 테스트: `tests/test_relationship_changes.py`
- 문서: `docs/stage27_relationship_changes.md`
- 실행: `PYTHONPATH=src python -m unittest discover -s tests -v`
- 참고소설 원문은 비복제, Novel Bible 우선의 원칙을 유지합니다.

---

# AI Novel Factory — 25단계 클리프행어 유형 후보 분석

- 말미의 어휘·문장부호 단서만 분석하며 실제 서사적 클리프행어를 인증하지 않습니다.
- 원문·매칭 문구 비보관, 완전 오프라인, 7개 고정 후보 유형.
- 상세: `docs/stage25_cliffhanger_types.md`; 테스트: `tests/test_cliffhanger_analysis.py`.

---

## 24/100단계 — 사건 후보 간격·밀도 분석

로컬 키워드 후보의 회차별 밀도, 5구간 밀도, 시작 위치 간 간격 통계를 추가했습니다. 실제 의미적 전개 속도 판단과는 구분합니다. 개발 및 검증: `docs/stage24_event_pacing.md`.

---

# 23단계 — 사건 시점 후보의 회차 내 위치 분석

- `references/event_timing.py`: 22단계 고정 어휘의 등장 위치·구간별 빈도(실제 주요 사건 판정 아님)
- `tests/test_event_timing.py`: 신규 33개 검증
- `docs/stage23_event_timing.md`: 한계와 검증 범위
- 원문은 반환 값/DB/네트워크에 저장·전송하지 않음; 로컬 AI 의미분석/Windows EXE는 미검증
- 예약은 사용자가 `예약`을 요청할 때까지 비활성 유지

---

## 22단계 — 회차 구조의 관측 지표 (2026-10-12)

- `references/episode_structure.py`: 회차별 위치 기반 3구간 분량·대사 비율·키워드 출현 수·말미 구두점 후보 분석
- `tests/test_episode_structure.py`: 신규 자동 테스트
- `docs/stage22_episode_structure.md`: 정량 지표의 한계 및 실행 지침
- 참고소설 원문 외부 전송/DB 저장 금지; AI의 서사 이해·의미 기반 사건 탐지는 **미구현**

---

# AI Novel Factory — 20단계 누적 개발 산출물

20단계: 로컬 참고소설 파일 → 파싱 → 회차 분리 → 기본 통계 → 메타데이터 DB 통합 기능 및 자동 테스트.

- 신규: `src/ai_novel_factory/references/import_pipeline.py`, `tests/test_import_pipeline.py`
- 사용: `PYTHONPATH=src python -m unittest discover -s tests -v`
- TXT/Markdown, DOCX, PDF 지원. EPUB는 파서 부재로 이번 단계에서 실패 처리.
- 원문 DB 저장·업로드·외부 AI API 호출 없음.
- Windows EXE 빌드 및 특정 PC 전용 최적화 없음.
- 12/14단계 누락 독립 산출물 등 이전 통합 검증은 후속 단계에서 해결 필요.
- 사용자의 요청에 따라 시간별 예약 작업은 비활성 유지.

# AI Novel Factory — 11단계 누적 개발 산출물

**11/100: 참고소설 파일 선택 UI** (10단계 ZIP 기반)

- PySide6 `Reference Novels` 화면에 다중 파일 선택·목록·취소·비우기 UI를 연결했습니다.
- 선택된 경로는 메모리에만 보관하고, 화면에는 파일 이름만 표시합니다.
- 원문 읽기·파싱·해시·업로드·DB 저장·AI 호출·출판은 수행하지 않습니다.
- 실제 Windows EXE는 빌드하지 않았습니다.
- 자세한 내용: `docs/stage11_reference_file_picker.md`; 실제 테스트: `docs/stage11_test_results.json`.
- 2·4·7단계 독립 산출물은 여전히 확인되지 않아 통합 검증이 보류되었습니다.

---

# AI Novel Factory — 8단계 누적 개발 산출물

**8/100: PySide6 데스크톱 기본 UI** (6단계 ZIP 기반)

- Qt 없이 검증 가능한 12개 메뉴 계약과 PySide6 기본 창을 구현했습니다.
- API/AI/출판은 비활성, 사용자의 PC를 수정하지 않습니다.
- 2·4·7단계 산출물은 확인되지 않아 이번 ZIP에 포함되지 않았습니다.
- 자세한 내용: `docs/stage08_desktop_ui.md`

## 검증

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m ai_novel_factory.desktop --check
```

PySide6가 설치되어 있는 환경에서만 `python -m ai_novel_factory.desktop`로 GUI를 실행할 수 있습니다.

---

# AI Novel Factory — 5단계 누적 개발 산출물

- 이번 단계: **5/100 — 의존성·버전관리**.
- 포함된 이전 단계: **1단계 요구사항**, **3단계 아키텍처**.
- **2단계 및 4단계 파일은 현재 작업 공간에서 확인되지 않아 포함하지 않았습니다.**
- 실행 가능한 제품/EXE가 아닌 설계·메타데이터 및 오프라인 검증 코드입니다.

## 이번 단계 추가 파일
- `pyproject.toml`: 배포 메타데이터, 직접 의존성 범위 및 선택 설치 그룹.
- `.python-version`: 개발용 Python 3.12 지정.
- `.gitignore`, `.gitattributes`, `.editorconfig`: 버전관리 및 파일 규칙.
- `docs/dependency_policy.md`: 버전·잠금 파일·승인 정책.
- `docs/pending_user_actions.md`: PC 켠 뒤 사용자 확인 항목.
- `scripts/check_dependencies.py`: 외부 라이브러리 설치 없이 메타데이터 검증.
- `tests/test_dependencies.py`: 자동 회귀 테스트.

## 지금 실행 가능한 명령 (Python 3.11+ 필요)
```powershell
python scripts/check_dependencies.py
python -m unittest discover -s tests -v
```

## 아직 미완료
- 의존성 실제 설치/호환성 검증 및 `uv.lock` 생성.
- Git 초기화/원격 저장소 연결, Windows CI 빌드.
- Windows GUI/API/DB/AI/EXE 기능 구현.
- 2단계/4단계 산출물 통합 확인.

**다음 6단계:** 환경설정·비밀키 규칙.


## 58단계 — 선택한 참고 통계를 회차 플롯 검토 메모에 반영

`ai_novel_factory.pattern_application.apply_reference_patterns`가 최신 사용 기록과 선택된 익명 통계를 회차 기획의 편집 검토 메모에 연결합니다. Novel Bible·원래 회차 플롯을 변경하지 않으며 자동 창작·출판은 하지 않습니다. 자세한 내용은 `docs/stage58_pattern_application.md`를 참고하세요.

### Stage 59 — Episodes 수동 플롯 편집 (2026-10-13)

기존 EpisodeStore를 연결한 PySide6 Episodes 페이지에서 로컬 SQLite 작품/회차 선택, 회차 플롯과 장면별 자유 텍스트 플롯의 명시적 저장 및 수정 충돌 방지를 지원합니다. Qt 없는 환경에서도 저장 로직은 테스트 가능합니다. GUI 실제 실행과 Windows EXE 빌드는 미검증입니다. 세부사항과 제한: `docs/stage59_plot_editor.md`.

### Stage 66 — Planner·Writer·Checker 오프라인 제어 (2026-10-13)

완성된 회차·장면 계획을 64단계 장면 초고 생성 및 65단계 결합기에 순차 전달하고, 제한적 텍스트 검사 후 사용자 검토 또는 수정 필요 상태를 기록합니다. **전체 품질 검사·실제 자동 수정·기억 DB 반영은 후속 단계**이며 구현하지 않았습니다. 상세 내용 및 테스트 기록은 `docs/stage66_orchestrator.md` 참조.

## Stage 67 — Offline local task queue (partial Redis/Celery roadmap milestone)

SQLite metadata-only queue and explicitly started local worker thread; loopback-only optional Celery configuration (no live Redis/Celery integration tested). See `docs/stage67_local_queue.md` for implementation, tests, and limitations. This does not grant manuscript approval or publication rights.

### Stage 69 — Local retry and checkpoint integrity (partial)

Stage 69 adds explicit bounded retry of classified transient local provider failures and metadata-only SQLite step checkpoints; the caller must restore and SHA-256 verify previously successful artifacts before resuming. Checkpoints contain **no manuscript text or secrets**. Final manuscript saves, remote API retries, automatic unattended recovery and Windows EXE validation are **not implemented**. See `docs/stage69_retry_checkpoint.md` and the recorded tests.

### Stage 73 — Timeline 원고 주장 검수 (2026-10-13)

73단계는 EventTimelineStore의 실제 사건 날짜·상대시간·명시적 선후관계를 **검토자가 표시한 원고 구간**과 대조하는 읽기 전용 검사기를 추가했습니다. 시간·순서 충돌과 판단 불가를 구분하며 문장 순서를 실제 사건 순서로 가정하지 않습니다. 자연어 사건 추출/자동 수정/승인/출판은 미구현입니다. 상세 내용: `docs/stage73_timeline_checker.md`.

### Stage 77 — Repetition and near-duplicate sentence checks (ANF-REQ-054)

Offline `ai_novel_factory.repetition_checker` checks explicitly watched phrases against allowed counts, repeated word n-grams, normalized duplicate sentences and approximate surface-similar sentences in unapproved drafts. It reports redacted offsets/hashes, bounded analysis and explicit incomplete-scope markers; no automatic rewriting, reference-source comparison, approval or publication. See `docs/stage77_repetition_checker.md` and recorded tests. **77/100 is a source-level milestone, not a validated Windows EXE.**

### 86/100 — 30화 연속 모의 초고 생성 통합 시험 (ANF-REQ-059)

`python scripts/stage86_run_30_episode_trial.py --output docs/stage86_trial_report.json`으로
기존 Planner→Context→오프라인 Mock Writer→Scene Assembly→기초 문자 검사→로컬 작업 큐→DRAFT 버전 저장을
30회 연속 시험한다. 보고서에는 회차별 SHA-256·오류 개수·초고 상태만 저장하며 원고 본문은 저장하지 않는다.
이것은 **30화 실제 AI 집필 성공 또는 최종 원고 승인 테스트가 아니다.** 최종본·승인·출판·메모리 갱신·
Windows EXE/GUI·실제 로컬 LLM·전체 품질검사 자동 통합은 이 시험 범위에 없다.
세부 범위·실패 주입·회귀 테스트 결과는 `docs/stage86_thirty_episode_integration.md` 참조.

### 87/100 — 120화 오프라인 모의 장기 기억 안정성 시험 (ANF-REQ-060)

`python scripts/stage87_run_long_memory_trial.py --output docs/stage87_long_memory_trial_report.json`으로
120화 연속 모의 초고 생성, Novel Bible/Character/World 규칙 유지, 과거 1화 요약 장기 검색,
SQLite 재개방 무결성 및 **명시적 구조화 설정 충돌 건수**를 시험한다.
`--conflict-episode 73`은 1건의 시험용 충돌을 검출하고 73화 초고 저장을 차단한다.
**실제 LLM 장편 집필·자연어 의미 충돌 탐지·사용자 승인·메모리 자동 적용·Windows EXE 검증은 아니다.**
상세 내용: `docs/stage87_long_memory_stability.md`.

### 88단계 — 완결 검토: 복선·갈등·시간선 (ANF-REQ-061)

`src/ai_novel_factory/ending_audit.py`의 `EndingReviewStore`는 기존 로컬
Novel Bible SQLite 파일의 복선 상태·사건 시간선·회차 최종 원고 후보와
검토자가 명시적으로 등록한 갈등을 확인합니다. 검토 범위 확인이 누락되거나
OPEN/DEVELOPING 복선, 미해결 갈등, 폐기 항목, 불확실한 시간선, 누락 원고,
완결 이후 기록이 있으면 **완결 준비를 차단**합니다. 보고서에는 원고와 제목을
포함하지 않고 식별자·검사 코드·SHA-256 근거 지문만 남깁니다.

`ready_for_human_review=True`는 사람이 검토할 준비 상태일 뿐 **원고 확정·
출판 승인·실제 독자 품질 보증이 아닙니다**. 검토 근거가 변경되면
`require_current_review`가 이전 결과를 거절합니다. 실제 최종 승인 상태를
변경하는 API/GUI 연동은 구현하지 않았습니다. 원본 기획안 TXT 미확인;
사용자 제공 100단계 로드맵과 기존 `docs/requirements.md` 기준입니다.

검증: `PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage88_ending_audit.py' -v`
및 `python scripts/stage88_partitioned_regression.py --prefix docs/stage88_worktree`;
전체 회귀 테스트는 `--aggregate`로 8개 그룹을 합산합니다.
자세한 한계와 실행 기록은 `docs/stage88_ending_audit.md`,
`docs/stage88_test_results.json`, `docs/stage88_verification_log.txt`를 참조하세요.

### 89/100 — 출판 전 로컬 검수·명시적 승인 게이트 (ANF-REQ-067)

`src/ai_novel_factory/publication_approval.py`는 88단계 완결 검토, 83단계 최신 FINAL 후보,
78단계 현재 참고작 유사성 검사 및 로컬 영수증을 대조한 뒤, 사용자의 **명시적 로컬 확인 문구**로만
`PENDING` → `APPROVED`/`REJECTED` 상태를 기록합니다. 변경된 원고·설정·검사 근거와 철회된 승인은
`require_current_publication_approval`에서 차단합니다. 실제 사용자 신원 인증, 외부 출판/업로드,
기존 모든 외부 호출 경로의 게이트 강제 연동, Windows EXE 검증은 **아직 구현하지 않았습니다**.
원본 기획안 TXT는 미확인입니다. 상세 내용: `docs/stage89_publication_approval.md`.

### 90/100 — 작업 로그·비용·오류 모니터링 UI (ANF-REQ-069)

기존 로컬 SQLite 작업큐의 상태와 예약 실행 이력, 명시적으로 제출된 비용·시간·토큰 사용 및 오류 코드 기록을 PySide6 Episodes 메뉴의 **작업 로그·비용·오류** 탭에서 조회합니다. 비용의 `UNKNOWN`/`ESTIMATED`/`REPORTED`를 분리하고 미보고 비용을 0으로 가정하지 않습니다. 원고·프롬프트·비밀키/예외 원문은 모니터링 DB에 저장하지 않으며, UI만 열어서는 작업을 시작하거나 승인·출판하지 않습니다. **기존 모든 Writer 호출의 자동 계측은 구현하지 않았고 PySide6/Windows 실 GUI 실행도 미검증입니다.** 상세는 `docs/stage90_operations_monitor.md`를 참조하세요. 원본 기획안 TXT 첨부는 이번 실행에서 직접 확인하지 못했습니다.

### 91/100 — 독창적인 표지·썸네일 생성 (ANF-REQ-062)

- `src/ai_novel_factory/cover_art.py`와 `cover_cli.py`: 외부 참고작 이미지 없이 **기하학적 절차 생성 + 로컬 폰트 렌더링**으로 표지/썸네일 JPEG(`cover.jpg` 1600×2560, `thumbnail.jpg` 400×640) 생성. `pyproject.toml`에 선택 `graphics`/Pillow 의존성을 추가. 기존 파일 절대 덮어쓰지 않음, 불완전 저장 롤백.
- 실제 시범 결과: `docs/stage91_demo/cover.jpg`, `docs/stage91_demo/thumbnail.jpg` (가상 저자/제목, 출판용이 아님). 생성기/CLI 사용방법·독창성 한계·폰트 확인 사항: `docs/stage91_cover_art.md`.
- 테스트: `tests/test_stage91_cover_art.py`, `scripts/stage91_partitioned_regression.py`, `docs/stage91_test_results.json`, `docs/stage91_verification_log.txt`. 이전 모든 모듈 포함 전체 회귀와 ZIP 독립 추출 재검증 결과를 보존한다.
- 원본 기획안 TXT는 이번 실행에서 직접 확인하지 못해 사용자 제공 공식 100단계 및 누적 요구사항을 기준으로 개발했다. 표지의 법적 독창성, Windows GUI/EXE, 실제 로컬 LLM·Redis/Celery·pgvector 실연동은 검증되지 않았다. 참고작 표지 복제·외부 서버·출판 실행 없음.
- 다음 공식 단계: **92단계 — 제목·소개·키워드·가격 메타데이터**.


## 단계 92 — 출판용 메타데이터 초안 (ANF-REQ-063)

사용자 원본 제목·필명·소개·카테고리·키워드·가격을 검증하고 게시/승인되지 않은 UTF-8 JSON 초안을 로컬에 작성합니다.
`PYTHONPATH=src python -m ai_novel_factory.metadata_cli --input user_metadata.json --directory existing_output`
필드와 제한 및 테스트 지침은 `docs/stage92_publication_metadata.md`를 참조하세요.
참고소설 원문을 읽지 않으며 가격을 임의 추정하거나 원고 확정/게시/외부 접속하지 않습니다.

## 단계 93 — EPUB3 전자책 생성 및 구조 검증 (ANF-REQ-064)

92단계 미승인 메타데이터 초안과 사용자 작성 회차 텍스트로 EPUB3 `book.epub` 검토 파일을 로컬 생성합니다.
EPUB3 OCF/OPF/목차/XHTML/선택적 로컬 JPG 표지, 파일 구조·CRC·경로·외부 자산 차단 검사를 제공합니다.
`PYTHONPATH=src python -m ai_novel_factory.epub_cli --metadata meta.json --chapters chapters.json --output-dir EXISTING_DIR`
자세한 스키마·테스트·한계는 `docs/stage93_epub3.md`를 참조하세요. EPUBCheck/실제 리더/Windows 실검증은 수행하지 않았고
이는 원고 확정·검수 완료·사용자 승인·출판을 의미하지 않습니다.

## 단계 94 — 웹소설 회차별 업로드 **초안 파일** (ANF-REQ-065)

직접 제공한 회차 제목·본문·작가의 말을 각각 별도 UTF-8/LF 텍스트 파일로 생성하고,
SHA-256·바이트 수·스키마를 명시한 `upload_drafts/manifest.json`과 대조 검증합니다.
92단계 **미승인** 메타데이터 초안을 입력받되, 플랫폼 규격은 추정하지 않습니다.

```bash
PYTHONPATH=src python -m ai_novel_factory.upload_draft_cli \
  --metadata /local/publication_metadata.json \
  --episodes /local/owner_episodes.json \
  --output-dir /existing/private/directory
```

회차 JSON은 `[ {"episode_number":1,"title":"제1화","body":"사용자 직접 작성 원고","author_note":"작가의 말"} ]` 형태입니다.
오직 로컬 `upload_drafts/episode_0001_title.txt`, `_body.txt`, `_author_note.txt`와 `manifest.json`을 생성합니다.
파일 덮어쓰기·참고작 인용·업로드·게시·원고 확정·승인 상태 변경은 수행하지 않습니다.
`docs/stage94_upload_drafts.md`에 형식, 보안/무결성 한계, 재현 명령을 설명합니다.

### Stage 95 — Offline continuation: publisher asset review binding (still partial)

`src/ai_novel_factory/publisher_asset_review.py` provides a separate explicit **local**
review challenge for the stage 92 metadata file and stage 94 titles/author notes,
anchored to the current stage 89 manuscript approval and stage 95 offline dry-run.
It stores only hashes and local review status; invalidated drafts or approvals
block **reviewed offline simulations**. All real upload paths remain disabled.
**ANF-REQ-066 official API sandbox upload acceptance is NOT MET.** No platform
selected, no official API verified, no external access, no publisher account.
Details: `docs/stage95_continuation_asset_review.md`.

## 공식 100단계 — 릴리스 문서·설명서·인수 기준 (ANF-REQ-072)

- `docs/stage100_user_manual.md`: **개발자 인계용 오프라인 사용자 설명서**. EXE 미생성, 참고작 및 사용자 데이터 주의, 실제 AI/GUI 및 출판 검증 한계 설명.
- `docs/stage100_release_and_acceptance.md`: 95~99단계 미충족 인수 기준을 보존한 실제 최종 릴리스 체크리스트와 알려진 문제.
- `scripts/stage100_release_audit.py`: 과거 오프라인 증거와 필수 문서 SHA-256을 검사하지만 **출시를 자동 승인하지 않는** 읽기 전용 도구. `python scripts/stage100_release_audit.py --report local_release_audit.json` 사용 가능(기존 파일 덮어쓰기 금지).
- **RELEASE_BLOCKED**: 공식 95 API·96 플랫폼 검증·97 Windows EXE 실빌드·99 Windows 종합 GUI가 미검증이며, 100단계 문서화로 해당 조건이 충족되었다고 주장하지 않는다.
- 공식 기획안 원본 TXT는 직접 확인하지 못했다. 대화에 제공된 로드맵과 `docs/requirements.md` 기준이며, ANF-REQ ID를 새로 만들지 않았다.
- 외부 연결/원고 확정/업로드/설치/계정 연결 없이 로컬 코드·문서·회귀 테스트만 수행한다. **정식 Windows EXE 출시판이 아니다.**
