# 94단계: 웹소설 회차별 업로드 원고 파일 생성 (ANF-REQ-065)

## 공식 범위 / 출처

- 사용자 직접 제공 **공식 Windows EXE 100단계 로드맵 중 94단계** 및 기존 `docs/requirements.md`의 `ANF-REQ-065`: **“플랫폼 업로드용 회차 제목·본문·작가의 말 파일을 만든다. 파일을 생성하고 내용 인코딩을 검증한다.”**
- 원본 기획안 텍스트 `붙여넣은 텍스트(1)(7)(1).txt`는 현재 접근 가능한 대화 첨부/로컬 파일에서 찾지 못해 직접 재열람하지 못했습니다. 공식 사용자 로드맵+누적 ZIP 요구사항 문서만 사용했습니다.
- 95단계 공식 API Publisher Adapter, 96단계 플랫폼별 규격/업로드 검사는 **범위 밖**입니다. 특정 플랫폼 규격을 준수한다거나 실제 게시 가능하다고 주장하지 않습니다.

## 실제 로컬 기능

- 기존 단계 92 `publication_metadata.json`의 **사용자 제공/미승인** 작품 메타데이터를 검증한 뒤, 사용자가 직접 작성한 회차를 수동/CLI 입력받습니다. 참고작 원문, 클라우드 AI/LLM, 외부 API를 호출하지 않습니다.
- 각 회차 `episode_0001_title.txt`, `episode_0001_body.txt`, `episode_0001_author_note.txt` 파일 3개씩 생성하며, 작업 폴더에 자동으로 새 `upload_drafts/` 디렉터리를 **배타적으로** 생성합니다.
- 원고 Unicode는 변경하지 않고 **CRLF/CR을 LF로 정규화한 결과**를 UTF-8 **BOM 없이** 저장합니다. 입력 전·저장 후 엄격한 UTF-8 검증을 수행하며 저장 파일을 SHA-256 해시/바이트 크기와 비교합니다. 제목은 단일 행, 앞뒤 공백 거부합니다. 작가의 말은 빈 문자열 가능.
- `manifest.json`: 프로젝트 ID/메타데이터 버전/회차 번호/각 파일 이름/UTF-8 바이트 수/해시/검토 필요 상태만 포함. 제목·본문·작가의 말 평문, 키, 가격, Reference Profile, 플랫폼 계정 정보는 매니페스트에 저장하지 않습니다.
- 1~200개 회차, 각 회차 번호 1~9999의 고유 정수, 회차 본문 최대 2MB, 작가의 말 최대 50KB, 전체 TXT 크기 최대 25MB. 원본 회차 번호를 유지하고 매니페스트에서 오름차순으로 정렬하므로 일부 회차만 내보내기도 가능합니다.
- 기존 `upload_drafts/` 디렉터리나 심볼릭 링크가 있으면 **덮어쓰기 금지**; 쓰기/검증 실패 시 이번 호출에서 생성한 새 디렉터리만 롤백합니다.
- `verify_upload_drafts`는 manifest의 정확한 필드, 경로/중복/파일 수, 서명되지 않은 미승인 상태, UTF-8 원문 및 SHA-256을 검사합니다. 최초 생성 직후 자체 검증을 수행합니다.
- 다운로드/업로드/외부 네트워크/사용자 승인·원고 확정·플랫폼 업로드 실행은 전혀 없습니다.

## Python API 및 실행

```python
from ai_novel_factory.episode_upload_files import UploadEpisode, export_from_metadata_file, verify_upload_drafts
result = export_from_metadata_file('/local/publication_metadata.json', [
    UploadEpisode(episode_number=1, title='제1화', body='사용자가 작성한 첫 회차', author_note='작가의 말')
], '/existing/private/directory')
verify_upload_drafts(result.directory, expected_manifest_sha256=result.manifest_sha256)
```

```bash
PYTHONPATH=src python -m ai_novel_factory.upload_draft_cli \
    --metadata /local/publication_metadata.json \
    --episodes /local/owner_episodes.json \
    --output-dir /existing/private/directory
```

`owner_episodes.json`은 `[ {"episode_number":1,"title":"제1화","body":"독창적인 원고","author_note":"안녕하세요"} ]` 배열이며 항목 필드는 네 가지로 고정합니다.

## 검증/안전 한계

- 이 생성기는 **어느 실제 플랫폼의 업로드 규격도 자동으로 가정하거나 인증하지 않습니다**. 플랫폼별 파일명·본문 포맷·용량 제한은 96단계의 별도 작업입니다.
- SHA-256은 변조 감지용 **서명이 아닙니다**. 공격자가 파일과 매니페스트를 동시에 교체할 수 있으므로 `expected_manifest_sha256`을 별도로 보관할 때에만 그 기준에서 변경을 탐지합니다.
- 무결성 검사는 업로드 초안 구조와 원문 바이트 검증이지, 참고작 유사성/저작권/실제 사용자 승인/문학적 품질 인증이 아닙니다. 78·89단계의 결과는 출판 전에 별도로 검토해야 합니다.
- 출력 폴더의 동시 적대적 교체(TOCTOU), 파일 시스템 레벨 권한·암호화, 사용자 신원 인증 및 실제 Windows GUI/EXE는 검증되지 않았습니다. POSIX/Linux 오프라인 Python 환경에서만 검증합니다.
- Windows 앱, EPUBCheck, 실제 Redis/Celery·pgvector, 로컬 LLM 추론 및 출판 서비스 연결을 검증하지 않습니다.

## 테스트/산출물

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_stage94_upload_drafts.py -v
python scripts/stage94_partitioned_regression.py --prefix docs/stage94_worktree --start 1 --end 8
python scripts/stage94_partitioned_regression.py --prefix docs/stage94_worktree --aggregate
```

위 명령의 stdout·stderr·exit-code 및 그룹 커버리지, 최종 누적 ZIP 별도 압축 해제 재검증은 `docs/stage94_*`와 별도 독립 검증 JSON에 포함합니다.
