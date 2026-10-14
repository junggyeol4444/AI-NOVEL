# 13/100단계 — TXT·Markdown 파서

## 목표와 범위

11단계의 참고소설 파일 선택 기능 이후, TXT(`.txt`) 및 Markdown(`.md`, `.markdown`) 문서를 **로컬 메모리에서만** 읽어 문단·제목·코드 블록을 구분합니다. `ANF-REQ-006`(한국어 본문과 줄바꿈 추출)의 기초 구현입니다. 문서 원문은 디스크·DB·네트워크·AI 프롬프트로 복사하지 않습니다.

현재 작업 공간에 **12단계(입력 검증·인코딩·해시) 산출물이 없어** 그 단계와의 통합은 미실시입니다. 따라서 본 파서의 확장자 검사·크기 제한·디코딩 검사는 임시 방어책이며, 12단계의 검증·해시 기능을 구현한 것으로 간주하지 않습니다. 기존 선택 UI와 파서의 자동 연결도 보류합니다.

## 파일별 변경

| 경로 | 내용 |
| --- | --- |
| `src/ai_novel_factory/references/__init__.py` | 파서 공개 API |
| `src/ai_novel_factory/references/plaintext_parser.py` | TXT·Markdown 파서, 안전한 읽기와 디코딩 |
| `tests/test_plaintext_parser.py` | 인코딩·줄바꿈·제목·오류·원본 불변 테스트 |
| `docs/stage13_txt_markdown_parser.md` | 실행·제한·인수 기준 |
| `docs/stage13_test_results.json` | 자동 검증 결과 |

## 동작 계약

- `parse_text(text, format='txt'|'markdown')`: 이미 디코딩된 텍스트를 메모리에서 파싱합니다. 원본의 줄바꿈은 LF로 통일해 `ParsedReference.text`에 유지하고, 문단/제목/코드 블록을 `blocks`에 기록합니다.
- `parse_reference_file(path, encoding=None, max_bytes=16*1024*1024)`: `.txt`, `.md`, `.markdown` 파일만 최대 16 MiB까지 읽습니다. UTF-8(BOM 포함) 및 UTF-16(BOM 필수)을 자동 처리하고, CP949는 `encoding='cp949'` 명시 시에만 처리합니다. 유효하지 않은 바이트·제어문자·빈 문서는 오류로 거절합니다.
- 반환 객체와 블록의 `repr()`에 원문은 노출되지 않습니다. 원본 파일은 수정하지 않으며, 파서는 파일을 새로 생성하거나 외부로 전송하지 않습니다.
- Markdown 지원 범위는 ATX(`##`)·Setext(`===`, `---`, 여러 줄 제목 포함) 제목, 빈 줄로 구분된 문단, fenced code block입니다. 표·인라인 마크업·복합 중첩 구조는 **완전한 CommonMark 구현이 아니며** 추후 확장 검토 대상입니다.
- 메모리에 보관한 원문을 생성 모델에 직접 전달하거나, 새 소설의 문장·고유 설정으로 재사용해서는 안 됩니다. Novel Bible 우선, 유사성 검사, 출판 전 승인 원칙은 기존대로 유지합니다.

## Windows PowerShell 실행 명령

프로젝트 루트에서 Python 3.12 환경을 권장합니다.

```powershell
$env:PYTHONPATH = 'src'
python -m unittest tests/test_plaintext_parser.py -v
python -m unittest discover -s tests -v
python scripts/smoke_test.py
python -m compileall -q src tests
```

독립적인 가상 입력 예제(참고소설 원문 아님):

```powershell
$env:PYTHONPATH = 'src'
python -c "from ai_novel_factory.references import parse_text; doc=parse_text('# 가상 제목\n\n가상 본문', format='markdown'); print(doc.format, len(doc.blocks))"
```

## 완료 판정

- [x] 한국어 TXT 본문·문단·줄바꿈 추출
- [x] Markdown 제목(다중 줄 Setext 포함)·문단·코드 블록 분리
- [x] UTF-8 BOM, UTF-16 BOM, 명시적 CP949 처리
- [x] 손상된 입력·크기 초과 안전한 오류 처리
- [x] 파일 읽기 전후 원본 불변 테스트
- [ ] 12단계 정식 입력 검증/해시와 통합 (산출물 미확인)
- [ ] PySide6 GUI 및 Windows 실기기 테스트 (미실시)

**다음 단계(14): EPUB 파서.** 본 단계에서는 EPUB 처리를 구현하지 않습니다.
