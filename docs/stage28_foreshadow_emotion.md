# 28/100단계 — 복선·감정곡선 단서 분석

## 범위

27단계까지의 오프라인 문서 분석을 기반으로, 각 회차의 본문에서 **복선 설치/정보 공개 후보 단어**와 **긍정/부정 감정 관련 단어**의 위치 구간별 빈도를 셉니다. 분석은 Python 표준 라이브러리만 사용하며 로컬 AI 엔진·API·외부 네트워크가 필요하지 않습니다.

이 단계의 결과는 **실제 복선, 복선 회수, 인물의 감정 또는 서사의 감정 곡선을 의미적으로 판정한 것이 아닙니다.** 구체적인 서사 의미 분석은 후속 로컬 AI 단계의 검증을 받아야 합니다.

## 소스·공개 함수

- `src/ai_novel_factory/references/foreshadow_emotion.py`
- `analyze_foreshadow_emotion_text(text, number=1, max_cues=20000)`
- `analyze_reference_foreshadow_emotion(document, split=None, max_cues=20000)`
- 출력: `CueTotals`, `EmotionWindow`, `EpisodeForeshadowEmotion`, `ReferenceForeshadowEmotion`

## 계산 정의

1. 복선 설치 후보(`setup`): `복선`, `단서`, `암시`, `예언`, `징조`, `수상`, `비밀`, `숨겨` 등의 **어휘 출현**.
2. 정보 공개 후보(`reveal`): `진실`, `밝혀`, `드러`, `알고 보니`, `정체`, `폭로`, `회수` 등의 **어휘 출현**.
3. 긍정·부정 감정 어휘(`positive`, `negative`): 고정 한국어 어휘 사전의 출현. 실제 긍정·부정 감정을 확정하지 않으며 반어법·부정문·사람/관점 구분을 지원하지 않습니다.
4. `emotion_balance = (positive - negative) / (positive + negative)` (4자리 반올림). 두 값 모두 0이면 균형값은 0이며 방향은 `no_cues`로 표시합니다. 균형값 0이 감정이 중립이라는 뜻은 아닙니다.
5. `emotion_curve`는 회차 본문 문단 순서를 5개의 위치 구간으로 나눈 어휘 균형 시퀀스입니다. 문단 수가 적으면 빈 구간이 생깁니다. 문단 번호를 사용하므로 균등 글자 수 구간은 아닙니다.
6. `prior_setup_before_reveal_candidate`는 **앞선 회차 어딘가에 설치 어휘가 등장한 이후**, 현 회차에 정보 공개 어휘가 나타났다는 순서 표시입니다. **동일 복선 연결이나 복선 회수가 증명된 것은 아닙니다.** 같은 회차 안의 두 단서만으로는 참으로 표시하지 않습니다.
7. 참고소설은 회차 제목, 서문, Markdown 코드블록을 본문 분석 대상에서 제외합니다. `split`을 직접 제공하면 기존 18단계 분리 결과 검증을 다시 거칩니다. 원고는 수정하지 않습니다.
8. 최대 입력 2,000,000 문자 및 전체 분석 건당 총 어휘 단서 20,000개 제한을 적용합니다. 초과하면 원문/경로를 포함하지 않는 `ReferenceParseError`를 발생시킵니다.

## 보호·한계

- 데이터는 로컬 프로세스의 메모리에서만 분석됩니다. 반환 값에는 텍스트·원문 문장·매칭한 실제 문자열·파일명·파일 경로가 없고 고정 분류 라벨과 숫자만 있습니다.
- 이 코드 자체에는 원문 저장, 네트워크 요청, GitHub 업로드, 외부 AI API 호출, 자동 출판 기능이 없습니다.
- 한국어 형태소 분석이나 문맥/부정형/인용 화자/동일 단서 추적은 수행하지 않습니다. 어휘 기반 카운트는 오인식·미탐지가 있을 수 있습니다.
- 참고 작품 원문을 문장 생성 모델의 출력으로 복제하지 않습니다. 창작 과정에는 사용자 Novel Bible을 우선 적용해야 하며, 원문 유사성 검사는 별도의 후속 단계입니다.
- Windows 실행 및 EXE 생성은 아직 검증되지 않았습니다. Python 3.12 호환성도 Windows 실기기로 확인해야 합니다.

## 재현 명령

```bash
# 프로젝트 압축 해제 후 최상위 폴더에서
PYTHONPATH=src python -m unittest discover -s tests -p 'test_foreshadow_emotion.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/smoke_test.py
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = 'src'
py -3.12 -m unittest discover -s tests -v
py -3.12 scripts/smoke_test.py
```

## 실제 검증과 완료 범위

- 신규 45개 테스트 통과.
- 누적 455개 테스트 실행: 452개 통과, GUI 의존성에 따른 3개 건너뜀, 실패 0개.
- 스모크 검사 필수 항목 통과, Python 버전 안내 1건 (테스트 환경 Python 3.13, 개발 기준 Python 3.12).
- 산출물: `docs/stage28_test_results.json`, 누적 로컬 ZIP.
- 원본 계획상 다음 작업: **29단계 문체 통계 분석**.
