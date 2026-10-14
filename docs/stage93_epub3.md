# 93단계: EPUB3 제작·오프라인 구조 검증 (ANF-REQ-064)

## 원본 기준과 범위

- 사용자가 제공한 **공식 100단계 로드맵 93단계**와 기존 `docs/requirements.md`의 **ANF-REQ-064**(EPUB 파일 생성 및 구조 검증 통과)에만 해당합니다.
- 원본 기획안 TXT (`붙여넣은 텍스트(1)(7)(1).txt`)는 현재 도구가 접근하는 파일에 없어 실제 원문을 재열람하지 못했습니다. 로드맵/기존 요구사항 문서를 기준으로 했습니다.
- 92단계 **사용자가 작성한 미승인 메타데이터 초안**과 **직접 전달한 회차 제목·원고**를 사용하여 별도 폴더에 `book.epub`를 생성합니다. 참고작 원문이나 Profile, Novel Bible을 EPUB로 직접 복사하지 않습니다.
- 91단계 로컬 `cover.jpg`를 선택적으로 포함할 수 있으며, 저작권 독창성 검증 기능은 아닙니다.
- 이미 존재하는 `book.epub`는 덮어쓰지 않고, 기록 실패 시 생성 중인 파일만 삭제합니다.

## 실제 기능

- EPUB3 OCF: ZIP 첫 엔트리 `mimetype`(비압축, 지정 값), `META-INF/container.xml`, EPUB3 OPF package/manifest/spine/DC 메타데이터, `dcterms:modified` UTC 타임스탬프.
- XHTML 1.1 스타일의 XML 문서로 각 회차 HTML 이스케이프 및 단락 처리, `epub:type="toc"` 목차(회차 순서 일치), 내장 스타일시트, 선택적 JPG 표지 페이지.
- **자체 생성 형식의 범위 제한 검증기**: ZIP CRC·경로·중복·크기·XML parse·OPF/manifest/spine/TOC/필수 자산·외부 참조·스크립트 탐지. 생성 결과 SHA-256 반환 및 선택적인 해시 대조.
- API: `ai_novel_factory.epub3.create_epub`, `create_epub_from_metadata_file`, `verify_epub`, `Chapter`.
- CLI: `python -m ai_novel_factory.epub_cli --metadata PATH --chapters PATH --output-dir EXISTING_DIR [--cover PATH]`.
- 챕터 JSON은 **사용자가 제공하는 원본 텍스트**: `[ {"title": "제1화", "text": "사용자 원고"} ]`. 1~200개, 회차 UTF-8 최대 2MB, 전체 20MB. 메타데이터는 92단계 `publication_metadata.json` 파일로 검증된 것만 입력합니다.

```bash
PYTHONPATH=src python -m ai_novel_factory.epub_cli \
  --metadata /path/to/publication_metadata.json \
  --chapters /path/to/user_chapters.json \
  --output-dir /existing/private/folder
```

## 검증 범위와 제한

- EPUBCheck 같은 독립 EPUB 표준 적합성 검증기를 설치하거나 구동하지 않았으며 **모든 출판 플랫폼·모든 EPUB 리더에서 정상 렌더링을 보증하지 않습니다**. 자체 생성기용 부분 검증입니다.
- 실제 Kindle/국내 플랫폼 업로드나 배포, 최종 원고 확정, 사용자 승인 상태 변경을 수행하지 않습니다.
- 사용자 제공 원고가 참조 소설을 복제했는지 확인하는 검사(78단계)와 **이 EPUB 생성은 자동 게이트로 완전히 연결되지 않았습니다**. 실제 배포 전에 사용자 검토와 78·89단계 확인이 필요합니다.
- 사용 가능한 로컬 커버는 JPG 서명 검사로 제한되며 이미지 인코딩의 전면 검증은 하지 않습니다.
- Windows EXE/GUI, 실제 로컬 LLM 및 Redis/Celery/pgvector 실연동은 이번 단계에서 검증하지 않았습니다. Linux/Python 오프라인 테스트만 검증합니다.
- 어떠한 외부 서버, GitHub, 원격 저장소, 출판 플랫폼, 클라우드 AI API에도 연결하지 않습니다.

## 검증/재현

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_stage93_epub3.py -v
python scripts/stage93_partitioned_regression.py --prefix docs/stage93_worktree --start 1 --end 8
python scripts/stage93_partitioned_regression.py --prefix docs/stage93_worktree --aggregate
```

실행 명령·stdout/stderr·exit code·그룹 범위는 `docs/stage93_*` 로그와 JSON으로 제공하고, 누적 ZIP 독립 해제 후 전체 재검사 결과는 외부 최종 검증 JSON 및 ZIP에 기록합니다.
