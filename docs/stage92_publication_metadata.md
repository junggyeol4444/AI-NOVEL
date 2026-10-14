# 단계 92: 제목·소개·키워드·가격 메타데이터 — ANF-REQ-063

## 정확한 범위와 완료 기준
공식 100단계 로드맵의 92단계 및 `docs/requirements.md`의 **ANF-REQ-063**: 작품 설명·키워드·카테고리 등 필수 메타데이터 작성 및 검증. 현재 프로그램의 **로컬 초안 계약**이며 플랫폼별 확정 규격이 아닙니다(96단계에서 별도 검사).

## 구현
- `publication_metadata.py`: 사용자 자신의 제목·필명·소개·카테고리·1~12개 키워드·명시적 가격·통화·언어 검증. NFC 및 공백 정규화, 제어/방향 문자 거절, 중복 키워드·길이·미지원 통화·음수/부정확한 소수 가격 거절. KRW/JPY는 정수, USD/EUR는 소수 2자리 이하. 허용 금액은 0~10,000,000(통화 단위).
- `draft_from_original_premise`: 사용자 자신이 작성한 로그라인을 설명으로 그대로 옮기는 편집 가능한 메타데이터 초안. Reference Profile/원작 원문·문구·유사 표지로부터 생성하지 않음.
- `save_metadata`: 현존하는 디렉터리에 `publication_metadata.json`을 O_EXCL로 새로 생성, 기존 파일을 덮어쓰지 않음. SHA-256은 실수 변경 탐지용이지 신원 인증/서명은 아님. 승인/출판 상태는 항상 false.
- `load_metadata`: JSON 파일의 체크섬·허용 필드·형식 재검증. 확정/게시/승인으로 상태를 바꾼 파일은 로드 거부.
- `metadata_cli`: 로컬 유저 소유 JSON을 읽어 초안을 생성. 출력은 파일명·SHA만 표시하며 소개 문구를 콘솔/로그에 출력하지 않음.
- 표지 일치 선택 검사: cover_title/cover_author를 제공하면 title/author 불일치 거절. 실제 이미지 화소 확인이 아니라 문자열 계약 검사임.

## CLI 입력 예시 (이것은 독립적인 사용자 원본 텍스트임)
`user_metadata.json`:
```json
{"project_id":"novel-01","title":"새벽의 지도","author":"필명","original_logline":"미지의 세계를 탐사하는 모험 이야기.","category":"판타지","keywords":["모험","성장"],"price_amount":"0","currency":"KRW","language":"ko"}
```
실행: `PYTHONPATH=src python -m ai_novel_factory.metadata_cli --input user_metadata.json --directory EXISTING_DIR`
출력: `publication_metadata.json` (유저가 직접 선택한 폴더). 해당 파일에는 사용자 제공 설명과 가격이 *평문으로* 저장됩니다. 배포/업로드에 자동 전달되지 않습니다.

## 한계 / 승인 정책
- 메타데이터만 생성·검사: 완성된 플랫폼 규격, 저작권/표절·상표 검증, 가격 정책 적정성, 사용자 인증, 최종 원고 확정, 실제 게시/업로드는 지원하지 않음.
- 외부 서버·API·GitHub·원격 저장소·클라우드 AI·외부 모델을 호출하지 않음. 원본 기획안 TXT 미접근. 요구사항/100단계 제공 원문만 사용.
- JSON 본문은 암호화 저장이 아님. 저장 경로는 사용자가 관리해야 함. 해시 검증은 악의적 위조 방지가 아니라 손상 탐지용.
- Linux Python 3.13에서 테스트; 목표 Python 3.12, Windows EXE/GUI 및 실제 게시 기능 미검증.

## 테스트
`PYTHONPATH=src python -m unittest discover -s tests -p test_stage92_publication_metadata.py -v`
`python scripts/stage92_partitioned_regression.py --prefix docs/stage92_worktree --start 1 --end 8`
`python scripts/stage92_partitioned_regression.py --prefix docs/stage92_worktree --aggregate`
최종 수치, 명령 및 stdout/stderr/exit은 docs/stage92_* 파일 참조.
