# 17단계 — 회차 자동 분리

ParsedReference 블록의 독립적인 회차 제목(1화, 제2화, Episode 3)을 기준으로 본문을 분리합니다. 본문 저장·외부 전송은 하지 않습니다.

테스트: PYTHONPATH=src python -m unittest discover -s tests -v

회차 미표시 시 단일 회차로 취급하고, 서문은 별도 보관합니다. 중복·역순 회차 번호는 거부합니다.
