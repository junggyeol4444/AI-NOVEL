# 19단계 — 참고소설 메타데이터·목록 DB

## 범위

11단계 참고소설 파일 선택, 13/15/16단계 파서, 17단계 회차 분리, 18단계 통계를 바탕으로 **참고 파일의 식별정보와 분석 상태만** 지속 저장할 수 있는 로컬 메타데이터 레지스트리를 개발했습니다.

- 라이브러리: Python 표준 라이브러리 `sqlite3`. 외부 유료 AI API 없음
- 저장 필드: UUID, 파일명(전체 경로 제외), 형식, 바이트 수, SHA-256, 분석 상태, UTC 등록·수정 시각
- 파일 해시는 호출자가 사전에 계산해 전달하며(12단계 연동 예정), 원문 파일을 DB로 복사하지 않습니다
- SHA-256 중복 등록 방지, 상태 변경 `registered → analyzing → analyzed/failed` 및 재시도 지원
- 정렬·필터·페이지네이션 조회와 카운트, 트랜잭션 저장
- 소설 원문, 장면, 인물 데이터, 비밀 키, 전체 파일 경로는 저장하지 않습니다
- SQLite는 Windows 단일 사용자의 **메타데이터용 로컬 어댑터**입니다. 기존 기획안의 PostgreSQL/pgvector 장편 기억 구조를 대체하는 결정은 아닙니다
- 자료가 로컬에서만 처리되므로 네트워크 요청이 없습니다

## 사용법

```python
from ai_novel_factory.database import ReferenceCatalog

with ReferenceCatalog('reference_catalog.sqlite3') as catalog:
    entry = catalog.register(file_name='sample.txt', source_format='txt',
                             byte_count=123, sha256='a' * 64)
    catalog.change_status(entry.reference_id, 'analyzing')
    print(catalog.list(status='analyzing'))
```

등록 시 SHA-256 값을 임의로 사용하지 말고 실제 파일에서 계산한 해시를 제공해야 합니다. 12단계 입력 검증기와의 실연동은 보류입니다.

## 테스트

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

기존 2·4·7·12·14단계 독립 산출물은 확인되지 않았으며 실제 Windows EXE의 DB 저장 시험은 아직 실시하지 않았습니다. GitHub에는 PR로 병합하고 CI 상태를 별도로 기록합니다.