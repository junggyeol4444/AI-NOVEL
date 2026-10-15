"""UI navigation contract. No Qt dependency; testable without a display."""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Section:
    key: str
    label: str
    description: str

SECTIONS: tuple[Section, ...] = (
    Section('novels', '작품 홈', '작품을 만들고 현재 작업과 회차 진행을 확인합니다.'),
    Section('bible', '작품 설정', '작품의 최상위 설정 기준을 관리합니다.'),
    Section('characters', '등장인물', '등장인물의 프로필과 지식을 관리합니다.'),
    Section('world', '세계관', '세계관과 조직·지역·능력을 관리합니다.'),
    Section('timeline', '시간선', '사건의 시간 순서를 확인합니다.'),
    Section('relationships', '인물 관계', '인물 관계 변화를 관리합니다.'),
    Section('foreshadowing', '복선 관리', '복선 설치 및 회수를 관리합니다.'),
    Section('references', '참고소설', '참고소설을 구조적 특징만 분석합니다.'),
    Section('patterns', '참고 패턴', '재사용 가능한 일반 패턴을 관리합니다.'),
    Section('episodes', '회차 기획', '회차별 기획·원고·검수 상태를 확인합니다.'),
    Section('similarity', '유사성 검사', '원문·장면·설정 유사성 검사를 확인합니다.'),
    Section('publication', '내보내기·출판', '사용자 승인 후 출판 절차를 진행합니다.'),
)

def section_for_key(key: str) -> Section:
    for section in SECTIONS:
        if section.key == key:
            return section
    raise KeyError(key)
