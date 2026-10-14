# 61단계 — AI 모델 제공자 API 연동 (로컬 전용 계약)

## 범위 근거

- 원본 100단계 로드맵: **61단계 AI 모델 제공자 API 연동**.
- `docs/requirements.md`의 `ANF-REQ-046`: AI 모델 호출을 통한 장면 초고 생성; **모의 모델 계약 검증, 실제 호출은 별도 승인 후 시험**.
- 최신 입력 ZIP: `AI_Novel_Factory_stage60_local.zip` (286개 파일; 전체 테스트 1,926개, 통과 1,912/건너뜀 14/실패 0).
- 기존 조건: GitHub·외부 서버·클라우드 AI API 접근 금지. 오프라인 Windows 실행 지향. 참고작 원문 비복제, Novel Bible 우선, 출판 전 승인 유지.

## 구현

`src/ai_novel_factory/local_models.py`:

- `SceneDraftRequest`/`SceneDraftResult`: 작품, 회차, 장면 식별자, **Novel Bible**, 장면 목표·갈등·장소, 인물, Style Bible을 담는 제한된 계약. `reference_novel`/원문/원격 API 키 필드 없음.
- `SceneDraftProvider` 프로토콜과 `draft_scene`: 독립적인 생성 호출. 입력 텍스트·길이 검사, 결과 상태는 항상 `DRAFT_REQUIRES_USER_APPROVAL`, `persisted=False`. DB/승인/출판 동작 없음.
- `MockSceneProvider`: 모의 초고를 결정적으로 반환. **실제 언어모델 아님**.
- `LocalExecutableProvider`: 명시적으로 허용된 **절대 경로의 로컬 실행 파일**을 `shell=False`로 시작하고, stdin/stdout UTF-8 JSON 프로토콜로 통신. 타임아웃·응답 길이·프로토콜 버전·종료 코드 검사. 비밀키처럼 불필요한 환경변수를 전달하지 않고 stderr를 에러 메시지에 노출하지 않음. 원격 HTTP 엔드포인트, API 키, 네트워크 라이브러리를 사용하지 않음.

### 로컬 실행 파일 계약

stdin JSON 예시 (고유한 작품 정보만 보낼 것):

```json
{"protocol":"anf-local-scene-v1","task":"scene_draft","request":{"novel_bible":"작품 고유 설정","project_id":"work-1","episode_number":1,"scene_number":1,"scene_goal":"비밀 찾기","scene_conflict":"닫힌 문","scene_location":"서재","characters":["주인공"],"style_bible":"3인칭"}}
```

stdout JSON:

```json
{"protocol":"anf-local-scene-v1","draft":"로컬 모델이 반환한 장면 초고"}
```

호출 예시:

```python
from ai_novel_factory.local_models import SceneDraftRequest, MockSceneProvider, draft_scene
request = SceneDraftRequest('my-book', 1, 1, '고유한 세계관', '문을 연다', '문이 잠겨 있다', '서재', ('주인공',))
result = draft_scene(request, MockSceneProvider())
assert result.status == 'DRAFT_REQUIRES_USER_APPROVAL' and not result.persisted
```

기존 60단계 `PlanningPipelinePreview`는 빈 장면 슬롯을 생성하므로 실제 생성 호출 시 사람이 확인한 장면 정보와 Novel Bible을 명시적으로 제공해야 함. 아직 장면·기억·원고 DB 및 UI와 자동 연결하지 않음.

## 테스트

`tests/test_stage61_local_models.py`: 23개 테스트. 모의 제공자·필드 검증·Novel Bible 순서·작품 식별·최소 입력 필드·총량 상한·로컬 워커 JSON 왕복·비밀 환경변수 격리·타임아웃·잘못된 응답·대형 응답·오류 메시지 비노출 검사. 테스트 워커는 로컬 임시 Python 파일이며 실제 LLM 모델을 실행하지 않음.

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage61*.py' -q
PYTHONPATH=src python -m unittest discover -s tests -q
```

## 확인하지 않은 것 / 보안·제품 한계

1. 실제 GGUF/ONNX/Transformers 등 **모델 추론은 실행하지 않음**. 생산용 모델 바이너리, 모델 가중치, 품질·성능 검증도 없음. 실제 클라우드 제공자 연동은 기존 금지 조건에 의해 미구현.
2. 임의의 로컬 실행 파일이 내부적으로 네트워크를 사용하지 않는지 Python 부모 프로세스에서 **강제 보장할 수 없음**. 사용자가 신뢰·검토한 완전 오프라인 실행 파일만 명시적으로 허용해야 함. 방화벽/OS 샌드박스 수준 차단은 미구현.
3. 로컬 프로세스 stdout을 종료 후 검사하므로 악의적인 바이너리의 무한 출력으로 인한 메모리 사용량은 OS 수준에서 제한하지 못함. **신뢰할 수 없는 실행 파일을 실행하면 안 됨**.
4. Novel Bible을 요청 JSON의 첫 항목으로 보내지만 **LLM이 실제로 설정을 지키는지 검증하지 않음**. 이 단계는 프롬프트 조합(63), 원고 생성(64), 품질 검사(71+)보다 앞선 계약 개발임.
5. 참고작 원문 비복제는 **API에 원문 전용 필드가 없다는 계약** 차원의 제한이며, 호출자가 Novel Bible 등에 참고작 원문을 넣는 것을 자동으로 판별할 수 없음.
6. 모델 반환 본문의 유사성 검사/표절 방지/안전성 확인은 아직 미구현. 사용자 승인 없이 원고 확정·출판하지 않음.
7. Linux Python 3.13.x에서 테스트. Windows, Python 3.12, GUI, PyInstaller EXE 미검증. 기존 SQLite 연결 ResourceWarning이 있을 수 있음.

다음 단계: 62단계 API 키 안전 저장 및 연결 관리. 기존 오프라인 조건에 맞춰 불필요한 클라우드 키 수집을 강제하지 않아야 함.
