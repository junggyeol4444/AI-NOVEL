# 91/100 — 독창적인 표지·썸네일 생성 (ANF-REQ-062)

## 권위 있는 기준과 제한

공식 100단계 로드맵 **91단계: 독창적인 표지·썸네일 생성**. 최신 누적 `docs/requirements.md`의 **ANF-REQ-062**는 “새 작품의 표지·썸네일을 생성한다. cover.jpg와 thumbnail.jpg를 생성하고 참고 표지 복제를 금지한다.”이다. 기준 `AI_Novel_Factory_stage90_local.zip`은 1,300개 항목, CRC 정상, 이전 검증 2,944개 통과·21개 건너뜀·실패 0으로 기록되어 있다. **원본 기획안 TXT 첨부는 이번 실행에서도 열 수 없었으므로 직접 미확인**이며, 공식 사용자 제공 로드맵과 기존 요구사항 문서를 따른다.

## 실제 구현

- `src/ai_novel_factory/cover_art.py`: 완전 로컬 `CoverSpec`을 사용해 `cover.jpg` **1600×2560**과 `thumbnail.jpg` **400×640** JPEG를 생성한다. 기하학적 궤도/수평선/프리즘과 별빛을 난수 시드로 직접 합성하며, 세 가지 색상 팔레트를 제공한다. 제목·작가·장르 글자를 로컬 폰트로 렌더링한다. 결과는 입력 문자열에 대해 결정적이다. Pillow(선택 `graphics` 의존성)가 있어야 실행되며 Windows는 `malgun.ttf`, Linux는 Nanum/Noto, macOS는 AppleSDGothicNeo 등 OS 제공 폰트를 사용한다. 폰트를 찾지 못하면 명시적 `font_path`가 필요하며 성공으로 위장하지 않는다.
- **참고작 비복제:** 참고 이미지/원작 표지/책 본문을 받거나 불러오는 코드 경로가 없다. 단지 지정한 텍스트와 추상 기하 요소를 사용한다. **전 세계의 기존 디자인과 우연히 유사하지 않음을 증명할 수 없다.** 사용자/권리자 수동 검토가 필요하다. 기존 참고작 표지·캐릭터·기존 세계관 자산의 자동 재사용 없음.
- **안전한 파일 쓰기:** 사용자가 선택한 *이미 존재하는* 디렉터리만 사용. 기존 `cover.jpg` 또는 `thumbnail.jpg`는 절대 덮어쓰지 않는다. `O_EXCL`로 이름을 예약하고 부분 파일 실패 시 현재 호출이 만든 파일을 제거한다. 그러나 두 파일에 대한 OS 수준의 다중 파일 원자적 트랜잭션은 아니다.
- **프라이버시:** 모델 키·원고·참고작·외부 서버 접속 필요 없음. JPEG EXIF 메타데이터 없음. CLI 성공 출력에는 파일 지문만 표시하며 작품 제목·작가·전체 경로는 출력하지 않는다. JPG에는 의도적으로 제목/작가 문자열이 **이미지 픽셀로** 삽입된다. 저장 디렉터리는 OS 권한 정책에 따른다.
- `src/ai_novel_factory/cover_cli.py`: 명시적으로 로컬 렌더링만 실행하는 CLI. GUI 연결 및 편집은 91단계 완료 기준에 포함되지 않으며 Windows 데스크톱 연결은 검증하지 않았다.
- `docs/stage91_demo/cover.jpg`, `docs/stage91_demo/thumbnail.jpg`: **가상 제목/가상 작가의 시범용 정적 출력. 판매·출판·업로드가 아닌 생성 검증용**. 외부 이미지/표지를 가져오지 않았다. 그림에 사용된 OS 폰트 바이너리는 ZIP에 포함하지 않는다.

## 사용 예시 (오프라인)

```bash
# 사용할 폴더를 미리 생성해 두어야 합니다. 덮어쓰지 않습니다.
python -m pip install --no-index --find-links /path/to/local-wheels 'Pillow>=10.4,<13'
PYTHONPATH=src python -m ai_novel_factory.cover_cli \
  --title '별빛 아래의 지도' --author '시범 작가' --genre '오리지널 판타지' \
  --palette nocturne --style orbital --output-dir /path/to/existing/directory
```

설치 예시는 **로컬에 이미 준비된 wheel만 사용**한다. 소프트웨어가 외부 패키지를 자동 다운로드하거나 설치하지는 않는다. GUI·Windows EXE·폰트 호환성을 검증했다고 주장하지 않는다.

## 품질 한계·승인 게이트

합성 그래픽은 일러스트/LLM 이미지 생성과 다르며 텍스트 가독성·독창성·상표권 문제·성인/민감 내용은 사람이 판단해야 한다. 기능이 원고·출판 플랫폼에 연결되지 않아 사용자 승인 없이 출판·최종 확정·업로드하지 않는다. 출판 전 참고작 유사성 검사와 89단계 로컬 승인 게이트는 별도로 필요하다. `originality_reviewed=False` 및 `published=False`를 결과에 기록하며 법적 안전을 보증하지 않는다.

## 검증

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage91_cover_art.py' -v
python scripts/stage91_partitioned_regression.py --prefix docs/stage91_worktree --start 1 --end 8
python scripts/stage91_partitioned_regression.py --prefix docs/stage91_worktree --aggregate
```

실제 모든 테스트 모듈은 8개 겹치지 않는 그룹으로 분할하고 명령·stdout·stderr·종료코드를 별도 기록한다. 누적 ZIP의 이전 1,300개 경로 보존(의도적으로 갱신한 `README.md`, `pyproject.toml`은 예외), ZIP CRC, 별도 폴더 압축 해제 후 전체 테스트 재실행 결과도 따로 기록한다.
