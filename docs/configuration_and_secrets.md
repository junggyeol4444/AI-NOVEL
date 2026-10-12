# 6단계 — 환경설정 및 비밀키 관리 정책

## 범위
- 5단계 `pyproject.toml`의 Python 3.12 기준과 `pydantic-settings`의 후속 도입 가능성을 유지한다.
- 이번 단계는 **표준 라이브러리만으로 검증 가능한 최소 설정 로더**를 작성한다.
- 실행 환경은 `development`, `test`, `production`으로 구분한다.
- **외부 연결과 유료 AI 호출은 기본적으로 비활성화**한다. 기본 AI 제공자는 `disabled`다.

## 설정 우선순위
1. 프로세스 환경변수(`ANF_` 접두사)
2. 명시적으로 전달한 개발용 `.env` 파일 (`env_file=` 지정 시에만 읽음)
3. 코드의 안전한 기본값

`.env`를 자동 검색하지 않는다. 개발용 파일은 셸 스크립트로 실행하지 않고 단순 `KEY=VALUE` 형식으로만 파싱한다. `${...}` 확장이나 코드 평가를 하지 않는다.

## 지원 설정
| 이름 | 기본값 | 설명 |
|---|---|---|
| `ANF_ENV` | `development` | 개발/테스트/운영 |
| `ANF_API_HOST` | `127.0.0.1` | API 바인딩 주소(실제 바인딩은 9단계) |
| `ANF_API_PORT` | `8000` | API 포트 |
| `ANF_LOG_LEVEL` | `INFO` | 로그 수준 |
| `ANF_AI_PROVIDER` | `disabled` | AI 공급자(실제 연동은 61단계) |
| `ANF_AI_API_KEY` | 비어 있음 | 공급자 인증 키, 출력 금지 |
| `ANF_DATABASE_URL` | 비어 있음 | DB URL, 비밀번호 포함 가능 |
| `ANF_REDIS_URL` | 비어 있음 | 큐 URL, 비밀번호 포함 가능 |

## 비밀정보 보호
- `.env`, `.env.*`(단 `.env.example` 제외), `*.key`, `*.pem`, `secrets/`는 `.gitignore` 대상이다.
- 예제 파일에는 실제 인증정보를 넣지 않는다.
- 비밀 필드는 `repr=False`이며 진단 정보에는 값 대신 설정 여부만 표시한다.
- 오류 메시지에는 사용자 입력값이나 연결 URL을 포함하지 않는다.
- 로그·오류 추적·스크린샷·이슈 첨부 시 API 키, 토큰, DB/Redis 비밀번호, 원고 및 참고작 원문을 제거한다.
- Git 이력에 한 번이라도 유출된 키는 즉시 폐기·재발급한다. `.gitignore`만으로 이미 커밋된 비밀정보를 보호할 수 없다.
- 최종 EXE 안에 키를 하드코딩하거나 함께 패키징하지 않는다. 운영 단계에서는 Windows 자격 증명 저장소 또는 서버 측 비밀관리 도입 여부를 사용자 승인 후 결정한다.

## 향후 개발 단계와의 관계
- 7단계: 비밀정보를 마스킹하는 로깅 정책 연결.
- 9단계: FastAPI 바인딩/설정 연동.
- 61~62단계: AI 제공자 연결 및 Windows 안전 저장소 통합.
- 실제 DB·Redis 연결, 외부 서버 사용, 유료 API 이용은 사용자 승인 전 실행하지 않는다.

## 테스트
```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m ai_novel_factory.settings
```
`python -m ai_novel_factory.settings`는 비밀값이 아닌 설정 여부만 출력한다.