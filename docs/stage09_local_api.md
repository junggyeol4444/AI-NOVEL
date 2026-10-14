# 9단계 — FastAPI 상태 확인·데스크톱 연동

## 목적
8단계 PySide6 관리자 창에서 버튼을 눌렀을 때에만 로컬 FastAPI의 `/health` 엔드포인트를 검사한다. API는 AI, DB, Redis, 출판 플랫폼에 접근하지 않는다.

## 변경 파일
- `src/ai_novel_factory/api/health.py`: `health_payload()` 및 `create_app()`.
- `src/ai_novel_factory/api/__main__.py`: 로컬 서버 진입점, `--check` 지원.
- `src/ai_novel_factory/desktop/api_client.py`: 표준 라이브러리 기반 명시적 로컬 상태 확인.
- `src/ai_novel_factory/desktop/app.py`: 버튼 연결 및 상태 표시.
- `tests/test_api_health.py`, `tests/test_api_client.py`: 상태 계약과 실패 처리 검사.

## 실행 및 테스트 (프로젝트 루트에서)
```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m ai_novel_factory.api --check
python -m ai_novel_factory.desktop --check
```

선택 의존성을 **사용자 승인 후 설치한 환경에서만** 아래를 수행한다.
```powershell
python -m ai_novel_factory.api
# 별도 터미널에서
python -m ai_novel_factory.desktop
# UI에서 '로컬 API 연결 확인' 버튼 클릭
```

## 안전 및 제한
- 실행 초기에는 네트워크 요청이 없고, 버튼 클릭 시에만 로컬 API에 접속한다.
- API 서버는 `127.0.0.1`, `localhost`, `::1` 이외 바인딩을 거부한다.
- 클라이언트는 동일한 루프백 주소 외 연결을 거부하고 프록시 환경 변수를 사용하지 않는다.
- `/health` 응답은 고정된 서비스 식별자·버전·상태만 반환하며 API 키·DB 정보·원고를 포함하지 않는다.
- Novel Bible 우선, 참고소설 비복제, 유사성 검사 및 출판 전 승인 정책은 변경하지 않는다.
- 이 단계는 단순한 **프로세스 생존 상태**만 검증한다. DB/AI/출판 기능의 정상 동작을 의미하지 않는다.
- Windows EXE 빌드, 로컬 PC 수정, 실제 외부 서비스 연결은 수행하지 않았다.
- 2·4·7단계 산출물은 현재 확인할 수 없어 통합 검증 보류.
