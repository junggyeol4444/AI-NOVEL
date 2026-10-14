# 84/100 — 한 회차 확정 후 다음 회차 자동 진행 (ANF-REQ-049)

## 원본 및 범위

공식 100단계 로드맵의 **84단계**와 기존 `docs/requirements.md`의 **ANF-REQ-049**(한 회차 확정 후 다음 회차 자동 시작, 설정된 종료 회차에서 중지)를 기준으로 구현했다. 사용자가 언급한 원본 기획안 TXT는 이번 환경에 제공된 파일 목록에서 확인되지 않아 **직접 검증하지 못했다**. 제공된 로드맵/기획 요약과 기존 83단계 ZIP의 코드/테스트/검증 기록을 사용했다.

## 구현된 동작

`src/ai_novel_factory/episode_continuation.py`:

- `EpisodeContinuationStore`는 83단계 `ManuscriptVersionStore`를 상속한다. 명시적인 `confirmation_asserted=True`, 현재 회차의 마지막 `FINAL` 버전 ID·revision·원고 스냅샷 무결성, 작품 ID, 유효한 Story Arc, 설정된 마지막 회차, 다음 EpisodePlan의 회차·Arc·초고 검토 상태를 모두 확인한다. `FINAL`은 **최종본 후보**이며 `confirmation_asserted`의 실제 사용자 신원/승인 여부는 인증하지 못한다.
- 해당 회차가 마지막 회차이면 `STOPPED_AT_END`만 기록하고 다음 회차나 작업을 생성하지 않는다. 종료 회차 설정은 작품별로 저장되며 기존 설정을 암묵적으로 변경할 수 없다.
- 마지막 회차가 아니면 **기존 다음 회차를 덮어쓰지 않고** 비어 있는 다음 회차 레코드를 Novel Bible SQLite에 생성하고, 별도 로컬 `LocalTaskQueue`에 `QUEUED` 초고 작업을 등록한다. 큐에는 원고·설정·프롬프트·비밀정보를 저장하지 않는다. 큐 작업은 자동 출판이나 사용자 승인 상태가 아니다.
- Novel Bible DB와 큐 DB는 **서로 다른 트랜잭션**이다. 먼저 내구성 있는 `PENDING_QUEUE` 인텐트를 기록하고, SHA-256 기반 결정적 task ID로 enqueue한다. 큐 등록 실패 또는 등록 직후 중단되면 동일 입력으로 재시도해 중복 작업 없이 `QUEUED_DRAFT`로 복구할 수 있다. 큐는 외부 Redis/Celery가 아닌 기존 67단계 오프라인 SQLite 구현이다.
- `continue_episode`는 다음 회차의 완성된 ScenePlan·EpisodeContext·로컬 제공자·검사기를 호출자가 제공했을 때 기존 70단계 `run_one_episode`를 **한 번 실행**한다. `MockSceneProvider`는 AI가 아닌 고정 모의 초고를 만들고, `LocalExecutableProvider`는 별도 명시적 실행 허가를 요구한다. 반환 초고는 메모리 내 검토 후보일 뿐 DB에 저장·확정하지 않는다. 실행 이후 상태는 `AWAITING_HUMAN_REVIEW` 또는 `REWRITE_REQUIRED_NOT_IMPLEMENTED` 등 기존 워크플로 상태다.
- 모든 기능은 로컬이다. 외부 서버, 원격 저장소, 클라우드 API, 출판 플랫폼을 호출하지 않는다.

## 예시

```python
from ai_novel_factory.episode_continuation import EpisodeContinuationStore, continue_episode
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.orchestrator import OfflineLiteralChecker

with EpisodeContinuationStore('novel_bible.sqlite3') as store:
    queue = LocalTaskQueue('local_jobs.sqlite3')
    # project_id, episode_number, end_episode, arc_plan, next_plan, next_scenes,
    # next_context, final_version 은 사용자가 사전에 준비한 검토 자료이다.
    result = continue_episode(
        store, project_id, episode_number,
        end_episode=end_episode, expected_revision=final_version.episode_revision,
        expected_version_id=final_version.version_id,
        confirmation_asserted=True, arc_plan=arc_plan, next_plan=next_plan,
        queue=queue, next_scenes=next_scenes, next_context=next_context,
        provider=MockSceneProvider(), checker=OfflineLiteralChecker())
    # result.run.workflow.preview 는 모의 원고, 실제 승인·출판은 불가
```

## 보안/제약/미검증

- `confirmation_asserted=True`는 **호출자가 주장한 확인**일 뿐 독립적인 사용자 인증이나 법적 출판 승인 증빙이 아니다. 89단계의 승인 워크플로가 필요하다. 출판 승인·플랫폼 업로드는 어떤 경로에서도 하지 않는다.
- `QUEUED_DRAFT`는 작업을 대기열에 넣었다는 의미이며 집필이 성공했음을 뜻하지 않는다. `continue_episode` 호출 시에만 검증된 기존 오프라인 작성 흐름을 실행한다. 모의 제공자 결과를 실제 AI 추론 결과로 간주하지 않는다.
- 다음 회차 기획과 장면 상세·Novel Bible 컨텍스트는 호출자가 명시적으로 준비해야 한다. 82단계 기억 반영의 완료 여부를 자동 인증하거나, 전체 품질 검사/Reference Similarity/Memory Delta를 이 단계에서 한 번에 연결하지 않는다. 기존 70단계의 `OfflineLiteralChecker`는 전체 품질 검사가 아니다.
- 원고 수정 후 이미 큐에 들어간 작업을 자동 취소하는 기능은 없다. 실제 디스패치 전 최신 확정본·검토 상태를 다시 확인하는 운영 통합은 향후 필요하다. 재시도 시 원고 revision이 바뀌면 새 작업 등록을 차단한다.
- 저장된 SQLite 파일 자체의 악의적 조작에 대한 암호화/인증 보호는 아니다. 동시 실행·다중 프로세스 작업 배포·Windows EXE/GUI·실제 로컬 LLM·Redis/Celery·pgvector는 검증하지 않았다.
- 검증: `tests/test_stage84_episode_continuation.py` 신규 테스트, 기존 전체 회귀 테스트, 별도 ZIP 압축 해제 후 동일 범위 재실행. SQLite 연결 ResourceWarning은 기존 코드 경로에서 발생할 수 있다.
