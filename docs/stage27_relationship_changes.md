# 27단계: 캐릭터 관계 변화 단서 분석

## 목적
26단계에서 사용자가 지정한 등장인물 식별자·이름·별칭을 재사용해, 각 회차의 **동일 문장 내 공동 언급**을 관측하고 그 인접 문장의 고정 키워드 단서를 집계합니다. **실제 인물 관계 추론이 아닌 탐색용 지표**입니다.

## 파일 및 API
- `src/ai_novel_factory/references/relationship_changes.py`
- `analyze_relationship_text(text, characters, number=1, max_observations=20000)`
- `analyze_reference_relationships(document, characters, split=None, max_observations=20000)`
- 결과: `EpisodeRelationships`, `PairEvidence`, `PairSummary`, `RelationshipChange`, `ReferenceRelationships`

## 계산 규칙
1. 26단계와 동일한 인물명/별칭 매칭 및 겹침 제거 규칙을 적용합니다. 반환 객체에는 원문 이름이 아니라 호출자가 부여한 영문 식별자만 들어갑니다.
2. 한 문장 내 두 인물의 언급 거리가 240문자 이하일 때만 해당 두 인물의 `joint_sentences`를 1 증가합니다. 세 인물이 등장하면 최대 세 쌍을 측정하되, 한 문장에서 같은 쌍은 한 번만 셉니다.
3. 동일 문장 내 긍정·협력 단서(`도와/도왔/협력/화해/감사/믿었...`)와 부정·갈등 단서(`공격/배신/위협/다퉜/증오...`)의 유무를 각각 셉니다. 두 단서가 동시에 있을 수 있습니다. 아무 단서도 없으면 중립 관측으로 셉니다.
4. 회차별 단서 균형은 `(긍정 관측 - 부정 관측) / 공동 언급 문장 수`입니다. 2개 회차에서 동일 쌍의 균형을 비교하고, 신규 공동 언급/중단/긍정 단서 증가/부정 단서 증가/변화 없음으로 분류합니다.
5. 서문·회차 제목·Markdown 코드블록을 제외하고, 회차 번호가 연속적이지 않아도 실제 파일 순서의 인접 회차를 비교합니다.

## 한계
- 고정 단어와 동시 출현만으로 **실제 대화, 관계, 신뢰, 적대, 감정 변화는 증명할 수 없습니다.** 이름이 가까이 나열되는 설명문도 포함될 수 있습니다.
- 3인 이상의 문장에서는 단서 키워드가 누구의 행동인지를 판별하지 못하므로 각 쌍에 같은 단서가 적용될 수 있습니다. 결과를 **검토 후보**로만 사용해야 합니다.
- 문장 분리는 줄바꿈 및 문장부호 기반 휴리스틱이며, 한국어/인용문 전체 문법을 처리하지 않습니다.
- 로컬 AI 모델을 이용한 감정/상호작용 의미 분석은 별도 미래 단계입니다. 원문 추출·출판 승인/유사성 검사도 기존 로드맵에 따라 후속 개발합니다.

## 보안·개발 정책
- 로컬 메모리에서만 분석하며 소스 파일을 수정·전송·DB에 저장하지 않습니다.
- 결과·예외 메시지에 원문 이름/별칭/일치 문구/로컬 경로를 포함하지 않습니다. 단, `CharacterSpec` 입력 자체에는 별칭이 존재하므로 호출부 로깅/직렬화를 금지해야 합니다.
- 인물 사전 및 별칭 제한은 26단계를 재사용합니다. 본문 200만 문자, 쌍-문장 관측 20,000회 초과 시 안전하게 실패합니다.
- GitHub/원격 서비스/유료 AI API 호출 없이, 대화에 첨부한 누적 소스 ZIP 안에서만 개발합니다.

## 테스트
```bash
# 프로젝트 최상위 폴더에서 실행
PYTHONPATH=src python -m unittest discover -s tests -p 'test_relationship_changes.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/smoke_test.py
```
Windows PowerShell:
```powershell
$env:PYTHONPATH = 'src'
py -3.12 -m unittest discover -s tests -v
```

완료 기준: 신규 테스트 및 전체 회귀 테스트 통과, ZIP 무결성 확인. Windows 실제 실행, EXE 빌드, AI 의미 판정은 미완료입니다.
