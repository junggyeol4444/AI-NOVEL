# 17단계: 회차 자동 분리

TXT·Markdown·DOCX·PDF로 추출된 ParsedReference 객체의 독립 회차 표제(제1화, 2화, Episode 3, Chapter 4)를 기준으로 분리합니다.

서문은 preface로 따로 보존하며, 회차 표제가 없다면 단일 회차로 처리합니다. 중복·역순 회차 번호는 거부합니다. 원문 파일은 수정·전송하지 않습니다.

실행: `PYTHONPATH=src python -m unittest discover -s tests -v`

전체 Windows 실기기 검증은 보류 중입니다.
