# 5단계 — 의존성·버전관리 정책

## 범위와 상태
- 기준 프로젝트: 1단계 요구사항 + 3단계 아키텍처. 2단계·4단계 결과는 현재 파일로 확인되지 않음.
- Python **3.12.x, Windows x64**를 잠정 개발 기준으로 채택한다. 실제 사용자 Windows 버전/CPU 확인 후 변경 가능.
- `pyproject.toml`의 범위 지정은 **설치 버전 고정(lock)이 아니다**. 실제 설치 및 호환성 검증은 아직 수행하지 않았다.
- **`uv.lock` 미생성**. 설치/네트워크/승인 없이 잠금 파일을 지어내지 않는다.

## 패키지 분리
- `desktop`: PySide6 GUI + HTTP 클라이언트
- `api`: FastAPI, Pydantic, ASGI 서버
- `database`: PostgreSQL 클라이언트, SQLAlchemy, pgvector 연동
- `queue`: Celery + Redis
- `documents`: EPUB/DOCX/PDF 파서 (TXT/Markdown은 표준 라이브러리부터 시작)
- `quality`: 문자열 유사도 보조 라이브러리 (저작권·장면 유사성 검사의 충분조건 아님)
- `dev`: pytest, ruff
- `build`: PyInstaller. **Windows EXE는 Windows 빌드 환경에서만 검증 가능**.

## 버전 정책
1. Python 마이너 버전은 `.python-version`과 `requires-python`으로 통제한다.
2. 직접 의존성은 하한과 다음 메이저 버전 상한을 명시한다. 이것은 호환성 가정이며 테스트 결과가 아니다.
3. 승인된 환경에서 `uv lock`을 실행하여 **전이 의존성까지** 잠그고, 생성된 `uv.lock`을 Git에 커밋한다.
4. 설치 시 `uv sync --locked --extra ...`를 사용하여 lock과 manifest 일치를 강제한다.
5. 새 패키지 추가·버전 갱신은 별도 변경 기록과 테스트 통과 후 반영한다.
6. Windows EXE 릴리스는 Windows CI에서 빌드·테스트·아티팩트 해시를 남긴다.
7. `.env`, API 키, 업로드 원문, 원고 및 개인 DB는 Git에 커밋하지 않는다.
8. Git 저장소 초기화/원격 연결/CI 계정 설정은 사용자 승인 전 수행하지 않는다.

## 향후 사용자 승인 후 명령 예시 (지금 실행하지 않음)
```powershell
# uv, Python 3.12 설치/준비 후 프로젝트 루트에서
uv lock
uv sync --locked --extra desktop --extra api --extra database --extra queue --extra documents --extra quality --extra dev --extra build
uv run --locked python -m pytest -q
# lockfile이 생성되면 검토 후 버전관리 저장소에 추가
# git add pyproject.toml .python-version uv.lock
```

## 현재 설치 없이 실행 가능한 검증
```powershell
python scripts/check_dependencies.py
python -m unittest discover -s tests -v
```
이 검증은 선언된 메타데이터와 Git 무시 규칙만 확인하며, 외부 패키지 설치·Windows 빌드의 성공을 증명하지 않는다.

## 기획안의 필수 통제
- 참고작 원문을 Writer 입력으로 직접 복제하지 않음.
- Novel Bible이 Reference Profile보다 우선함.
- 참고작 등록 시 Similarity Checker 검증이 원고 확정의 전제임.
- 실제 출판 및 비용 발생 서비스는 사용자 승인 후 수행함.