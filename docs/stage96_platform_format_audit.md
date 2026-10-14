# 96/100 — 플랫폼별 형식·업로드 가능성 검사 (오프라인 부분 구현)

공식 사용자 제공 100단계 로드맵의 **96단계**만 다룬다. `docs/requirements.md`에는 **96단계 전용 ANF-REQ 번호가 존재하지 않는다**. 임의 번호는 만들지 않았다.

## 목표 및 완료 기준과 인수 보류
- 목표: 사용자가 제공한 가상/임시 플랫폼 규칙과 92단계 메타데이터, 93단계 EPUB3, 94단계 회차별 TXT 형식을 **로컬 비교**한다.
- 확인 가능한 완료 범위: 파일 해시 결속 검증, 원고의 UTF-8·EPUB3 내부 구조 검증, 작품·회차 제목 글자수/본문 바이트 수/작가의 말·회차 수·언어·키워드 제한 검사, 차이 코드만 포함한 로컬 감사 기록.
- `LOCAL_DECLARED_MATCH_ONLY`는 **사용자가 입력한, 검증되지 않은 제한과의 일치**만 뜻하며 업로드 가능성을 뜻하지 않는다.
- `LOCAL_DECLARED_MISMATCH` 역시 실제 특정 플랫폼의 업로드 불가능 판정이 아니다.
- 공식 API와 플랫폼별 규격/계정, 업로드 성공을 검증하지 않았으므로 **95단계 ANF-REQ-066 공식 인수 조건 및 96단계 실플랫폼 검증 조건은 미충족**.
- 해당 런타임에는 네트워크 호출, 외부 플랫폼 목록/규정, 공식 플랫폼 이름, 계정 토큰, 게시 실행이 없다.
- 공식 업로드는 기존 95단계에서 의도적으로 차단된다.

## 사용 예시 (오직 테스트용 사용자 정의 제한)

```python
from ai_novel_factory.platform_format_audit import (
    UnverifiedPlatformRules, check_platform_format, write_local_audit_report,
)
rules = UnverifiedPlatformRules(
    profile_id='local_example', accepted_formats=('TXT_EPISODES',),
    max_title_characters=100, max_body_bytes=250000,
    max_author_note_bytes=5000, max_episodes=200,
    languages=('ko',),
)
result = check_platform_format(
    rules, draft_directory='.../upload_drafts',
    expected_draft_sha256='<기존 매니페스트 SHA256>',
    metadata_file='.../publication_metadata.json',
    expected_metadata_sha256='<메타데이터 파일 전체의 SHA256>',
)
# result.actual_upload_possible == 'UNKNOWN' (항상)
# write_local_audit_report(result, '<기존 출력 디렉터리>')
```

주의: 92단계 `save_metadata()`의 `MetadataOutput.sha256`는 내부 metadata **body** 체크섬이다. `expected_metadata_sha256`에는 `sha256(metadata_path.read_bytes()).hexdigest()`로 계산한 **전체 파일 해시**를 사용해야 한다.

EPUB3 비교 때는 `content_format='EPUB3'`, 실제 EPUB 파일 경로와 SHA-256을 명시하고, 93단계의 로컬 EPUB 부분집합 검증을 수행한다. EPUBCheck나 실제 리더 호환성 검사는 미수행.

## 안전성·한계

- `source`는 강제로 `USER_SUPPLIED_UNVERIFIED`이고 변경 불가. 보고서의 공식 검증·실제 업로드 가능·게시 여부 필드는 모두 False/UNKNOWN으로 고정.
- 재검증용 외부에서 보관한 SHA256 값이 없다면, 유효한 기존 원고/메타데이터였는지 인증할 수 없다. SHA-256 자체는 서명이 아니며 동일 공격자가 데이터·기대 해시를 바꾸면 위변조 방지를 보증할 수 없다.
- 임시 형식 제한은 공식 정책이 아니다. 규칙의 사실성은 별도 확인이 필요하다.
- 출판 승인·신원 인증·원고 최종 확정 기능과 무관하며 어느 원고도 업로드하지 않는다.
- Linux Python 3.13 테스트; Windows 실기기, 플랫폼 샌드박스, 로컬 LLM, Redis/Celery/pgvector는 미검증.
- 원본 기획안 TXT 실제 첨부에 접근하지 못했다. 사용자 제공 로드맵 요약과 누적 소스의 `docs/requirements.md`를 사용했다.
