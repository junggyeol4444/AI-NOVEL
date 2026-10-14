# 20단계 — 참고소설 가져오기 통합 테스트

## 범위

로컬 참고소설 등록의 실제 실행 경로를 검사한다.

1. 확장자 확인(TXT, MD, Markdown, DOCX, PDF)
2. 일반 파일만 제한된 바이트 수만큼 한 번 읽음
3. 읽은 바이트에 SHA-256 계산
4. 문서 형식별 메모리 파싱
5. 독립 표제 기반 회차 분리
6. 전체/회차별 기본 통계 계산
7. 분석에 성공한 경우에만 SQLite `reference_files`에 파일명·크기·해시·상태 저장

데이터베이스에는 원문/추출 텍스트/본문 통계가 저장되지 않는다. 통계는 호출 결과에만 남는다. 외부 서버·유료 AI API·로컬 AI 모델 모두 호출하지 않는다.

## 실행

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p "test_import_pipeline.py" -v
```

## 확인 사항

- 중복 해시 등록 시 기존 ID와 상태 유지
- 잘못된 인코딩·바이너리 TXT·회차 번호 오류·손상된 파일은 등록하지 않음
- 오리지널 문서 변경 없음, 경로 비노출, 소설 원문 DB 비저장
- 기존 파서 및 메타데이터 DB와 통합
- 누락된 14단계 EPUB 파서는 연결되지 않았으므로 확장자를 명시적으로 거부
- 12단계 독립 검증 모듈 통합·Windows/EXE 실기기 검증은 보류
- 메타데이터 DB는 기존 19단계 SQLite 임시 어댑터; PostgreSQL 연동은 후속 개발 단계
- 이 단계는 품질/참고작 유사성 분석 단계가 아님; Novel Bible 우선·복제 금지 정책 유지
