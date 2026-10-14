"""UI navigation contract. No Qt dependency; testable without a display."""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Section:
    key: str
    label: str
    description: str

SECTIONS: tuple[Section, ...] = (
    Section('novels', '작품', '새 장편소설을 기획하고 관리합니다.'),
    Section('bible', 'Novel Bible', '작품의 최상위 설정 기준을 관리합니다.'),
    Section('characters', 'Characters', '등장인물의 프로필과 지식을 관리합니다.'),
    Section('world', 'World', '세계관과 조직·지역·능력을 관리합니다.'),
    Section('timeline', 'Timeline', '사건의 시간 순서를 확인합니다.'),
    Section('relationships', 'Relationships', '인물 관계 변화를 관리합니다.'),
    Section('foreshadowing', 'Foreshadowing', '복선 설치 및 회수를 관리합니다.'),
    Section('references', 'Reference Novels', '참고소설을 구조적 특징만 분석합니다.'),
    Section('patterns', 'Reference Patterns', '재사용 가능한 일반 패턴을 관리합니다.'),
    Section('episodes', 'Episodes', '회차별 기획·원고·검수 상태를 확인합니다.'),
    Section('similarity', 'Similarity Reports', '원문·장면·설정 유사성 검사를 확인합니다.'),
    Section('publication', 'Publication', '사용자 승인 후 출판 절차를 진행합니다.'),
)

def section_for_key(key: str) -> Section:
    for section in SECTIONS:
        if section.key == key:
            return section
    raise KeyError(key)
