"""Validation-only existing-engine GUI surfaces, deliberately not a release claim.

The pattern page reads built local pattern recipes. The similarity page runs an
explicit bounded manual comparison against a locally supplied excerpt, NOT a
comprehensive reference corpus or copyright verdict. Publication only writes
private draft exports; it cannot access platforms or approve publication.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QListWidget, QComboBox, QFileDialog,
)

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.references.pattern_library import ReferencePatternLibrary
from ai_novel_factory.references.genre_patterns import render_genre_pattern
from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, check_reference_similarity,
)
from .reference_profile_browser import default_local_catalog_path


class PatternWorkspace(QWidget):
    """Search/read real locally persisted patterns, not dummy pattern cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.addWidget(QLabel('기존 참고작 분석에서 생성한 저장 패턴을 조회합니다.'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('장르 검색어 (선택)')
        self.search.setObjectName('patternLibrarySearch')
        root.addWidget(self.search)
        self.refresh_button = QPushButton('로컬 패턴 목록 불러오기')
        self.refresh_button.setObjectName('patternLibraryRefresh')
        root.addWidget(self.refresh_button)
        self.entries = QListWidget()
        self.entries.setObjectName('patternLibraryEntries')
        root.addWidget(self.entries)
        self.show_button = QPushButton('선택 패턴 상세 보기')
        self.show_button.setObjectName('patternLibraryShow')
        root.addWidget(self.show_button)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setObjectName('patternLibraryDetail')
        root.addWidget(self.report)
        self.keys = []
        self.refresh_button.clicked.connect(self.refresh)
        self.show_button.clicked.connect(self._show)

    def refresh(self):
        try:
            path = default_local_catalog_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with ReferenceCatalog(path) as catalog:
                page = ReferencePatternLibrary(GenrePatternStore(catalog)).search(
                    query=self.search.text(), limit=100)
            self.keys = [(p.genre, p.weighting) for p in page.entries]
            self.entries.clear()
            for p in page.entries:
                self.entries.addItem(
                    f'{p.genre} / {p.weighting}: {p.reference_count} 참고작')
            self.report.setPlainText(
                f'저장된 패턴 {len(self.keys)}개. 새 패턴 구축 및 강도 설정은 참고소설 메뉴에서 실행하세요.')
        except (ValueError, OSError) as exc:
            self.keys = []
            self.entries.clear()
            self.report.setPlainText('로컬 패턴 조회 실패: ' + type(exc).__name__)

    def _show(self):
        i = self.entries.currentRow()
        if i < 0 or i >= len(self.keys):
            self.report.setPlainText('패턴을 한 개 선택하세요.')
            return
        try:
            path = default_local_catalog_path()
            with ReferenceCatalog(path) as catalog:
                genre, weighting = self.keys[i]
                pattern = ReferencePatternLibrary(GenrePatternStore(catalog)).get(
                    genre, weighting=weighting)
            self.report.setPlainText(render_genre_pattern(pattern))
        except (ValueError, OSError):
            self.report.setPlainText('패턴이 변경됐거나 최신 자료가 아닙니다.')


class SimilarityWorkspace(QWidget):
    """Opt-in local passage check; no automatic pass if reference coverage absent."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            '참고 텍스트를 직접 입력해 현재 저장된 초고와 비교합니다.\n'
            '전체 참고소설 검사·저작권 판정·출판 승인이 아닙니다.'))
        self.episodes = QComboBox()
        self.episodes.setObjectName('similarityEpisodeSelector')
        root.addWidget(self.episodes)
        self.reference_text = QPlainTextEdit()
        self.reference_text.setObjectName('similarityLocalReferenceText')
        self.reference_text.setPlaceholderText('사용권한 있는 비교 문장/장면을 로컬에서 입력')
        root.addWidget(self.reference_text)
        self.compare_button = QPushButton('선택 회차의 저장 초고와 로컬 비교')
        self.compare_button.setObjectName('similarityCompareDraft')
        root.addWidget(self.compare_button)
        self.status = QPlainTextEdit()
        self.status.setObjectName('similarityLocalReport')
        self.status.setReadOnly(True)
        root.addWidget(self.status)
        self.compare_button.clicked.connect(self._compare)

    def refresh(self):
        self.episodes.clear()
        s = self.session()
        if not s or s.store is None or s.project_id is None:
            self.status.setPlainText('작품 메뉴에서 먼저 소설을 생성하거나 열어 주세요.')
            return
        for episode in s.store.list_episodes(s.project_id):
            if episode.draft.strip():
                self.episodes.addItem(f'{episode.episode}화', episode.episode)
        self.status.setPlainText(
            f'저장된 원고 {self.episodes.count()}개. 비교 참고작 범위는 사용자가 직접 제공한 텍스트로 한정됩니다.')

    def _compare(self):
        s = self.session()
        number = self.episodes.currentData()
        text = self.reference_text.toPlainText()
        if not s or s.store is None or s.project_id is None or number is None:
            self.status.setPlainText('비교할 저장 초고를 먼저 선택하세요.')
            return
        if not text.strip():
            self.status.setPlainText('사용권한이 있는 비교할 문장을 입력하세요.')
            return
        try:
            draft = s.store.get_episode(s.project_id, number).draft
            ref = ReferenceMaterial(
                reference_id=uuid4().hex,
                source_sha256=sha256(text.encode('utf-8')).hexdigest(),
                text=text)
            result = check_reference_similarity(
                s.project_id, number, draft, references=(ref,))
            self.status.setPlainText(
                '로컬 비교 결과: ' + result.status + '\n'
                + f'문장 매치 {result.sentence_matches}, '
                + f'장면 매치 {result.scene_matches}, '
                + f'구조 매치 {result.structure_matches}\n'
                + '참고작 전수 검사·출판 안전판정이 아니며 실제 적용에는 추가 검증이 필요합니다.')
        except (ValueError, OSError):
            self.status.setPlainText('비교를 완료하지 못했습니다. 입력 범위와 원고를 확인하세요.')


class PublicationWorkspace(QWidget):
    """Private TXT/EPUB preparation only; no platform publishing capability."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        root = QVBoxLayout(self)
        label = QLabel(
            '로컬 원고 내보내기만 지원합니다.\n'
            '공식 플랫폼 게시·자동 업로드·출판 승인 연동은 현재 검증되지 않아 비활성화되어 있습니다.')
        label.setWordWrap(True)
        root.addWidget(label)
        self.directory = QLineEdit()
        self.directory.setObjectName('publicationLocalDirectory')
        self.directory.setPlaceholderText('기존 로컬 출력 폴더의 절대 경로')
        row = QHBoxLayout()
        row.addWidget(self.directory)
        choose = QPushButton('폴더 선택')
        choose.clicked.connect(self._choose)
        row.addWidget(choose)
        root.addLayout(row)
        self.price = QLineEdit('0')
        self.price.setObjectName('publicationLocalMetadataPrice')
        root.addWidget(QLabel('가격 메타데이터 (KRW, 명시적 입력)'))
        root.addWidget(self.price)
        self.export_button = QPushButton('TXT + EPUB 비공개 내보내기')
        self.export_button.setObjectName('publicationLocalExport')
        root.addWidget(self.export_button)
        self.status = QLabel('초고 저장 후 별도 폴더에 안전하게 내보낼 수 있습니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)
        self.export_button.clicked.connect(self._export)

    def refresh(self):
        s = self.session()
        if s is None or s.project_id is None:
            self.status.setText('작품 메뉴에서 먼저 소설을 생성하거나 열어 주세요.')

    def _choose(self):
        path = QFileDialog.getExistingDirectory(self, '비공개 내보내기 폴더 선택')
        if path:
            self.directory.setText(path)

    def _export(self):
        s = self.session()
        if s is None or s.project_id is None:
            self.status.setText('작품 메뉴에서 먼저 소설을 생성하거나 열어 주세요.')
            return
        try:
            txt, epub = s.export(self.directory.text(), self.price.text())
            self.status.setText('로컬 파일 생성 완료: ' + txt.name + ', ' + epub.name +
                                ' (게시·업로드하지 않았음)')
        except (ValueError, OSError):
            self.status.setText('내보내기 실패. 기존 폴더·원고·중복 파일·가격을 확인하세요.')
