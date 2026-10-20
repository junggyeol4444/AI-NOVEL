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
    QPushButton, QListWidget, QComboBox, QFileDialog, QMessageBox, QCheckBox,
)
from PySide6.QtCore import QThread, Signal
from ai_novel_factory.wordpress_draft_api import post_private_draft

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.references.pattern_library import ReferencePatternLibrary
from ai_novel_factory.references.genre_patterns import render_genre_pattern
from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, check_reference_similarity,
)
from .reference_profile_browser import default_local_catalog_path
from .reference_coverage import read_reference_coverage
from .cover_draft_widget import CoverDraftWidget


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
        self.coverage_button = QPushButton('로컬 등록 참고작 범위 확인 (읽기 전용)')
        self.coverage_button.setObjectName('similarityReferenceCoverageButton')
        root.addWidget(self.coverage_button)
        self.coverage_status = QLabel('전수 유사성 검사 NOT_RUN · 등록 참고작 범위 미확인')
        self.coverage_status.setObjectName('similarityReferenceCoverageStatus')
        self.coverage_status.setWordWrap(True)
        root.addWidget(self.coverage_status)
        self.coverage_button.clicked.connect(self._read_coverage)
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

    def _read_coverage(self):
        # Only metadata counts. Do not initialize the catalog or read novels.
        coverage = read_reference_coverage(default_local_catalog_path())
        self.coverage_status.setText(coverage.label)

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


class _WordPressDraftWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, site, username, app_password, title, final_text, parent=None):
        super().__init__(parent)
        self.site, self.username, self.app_password = site, username, app_password
        self.title, self.final_text = title, final_text

    def run(self):
        try:
            receipt = post_private_draft(
                self.site, self.username, self.app_password,
                title=self.title, approved_final_text=self.final_text,
                explicitly_authorized=True)
            self.completed.emit('WordPress 비공개 초안 저장 확인: 게시물 ID ' + str(receipt.post_id))
        except Exception:
            self.failed.emit('WordPress 초안 전송 실패. 주소·권한·네트워크 상태를 확인하세요.')
        finally:
            self.app_password = ''
            self.final_text = ''


class PublicationWorkspace(QWidget):
    """Private draft/final exports; opt-in WordPress draft REST only."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        root = QVBoxLayout(self)
        label = QLabel(
            '원고를 로컬 TXT·EPUB로 비공개 출력합니다.\n'
            'WordPress 비공개 초안 전송은 최종본과 별도 사용자 승인이 필요합니다. 공개 출판은 지원하지 않습니다.')
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
        self.cover_panel = CoverDraftWidget(self.session, self.directory.text, self)
        self.cover_panel.setObjectName('publicationCoverDraft')
        root.addWidget(self.cover_panel)
        self.include_cover = QCheckBox(
            '이 로컬 폴더의 cover.jpg를 이번 EPUB3에 포함합니다 (직접 승인, 비공개)')
        self.include_cover.setObjectName('publicationIncludeGeneratedCover')
        self.include_cover.setChecked(False)
        root.addWidget(self.include_cover)
        self.price = QLineEdit('0')
        self.price.setObjectName('publicationLocalMetadataPrice')
        root.addWidget(QLabel('가격 메타데이터 (KRW, 명시적 입력)'))
        root.addWidget(self.price)
        self.export_button = QPushButton('TXT + EPUB 비공개 내보내기')
        self.export_button.setObjectName('publicationLocalExport')
        root.addWidget(self.export_button)
        self.final_export_button = QPushButton('직접 검수한 최종본만 TXT + EPUB 비공개 출력')
        self.final_export_button.setObjectName('publicationReviewedFinalExport')
        root.addWidget(self.final_export_button)
        self.final_export_button.clicked.connect(self._export_final)
        self.status = QLabel('초고 저장 후 별도 폴더에 안전하게 내보낼 수 있습니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addWidget(QLabel(
            '선택적 공식 WordPress REST API 초안 전송 (한국 웹소설 플랫폼 자동 출판 아님). '
            '완성한 최종본만 사용하며 실제 인터넷 전송 전 별도 확인합니다.'))
        self.wordpress_site = QLineEdit()
        self.wordpress_site.setObjectName('publicationWordPressSite')
        self.wordpress_site.setPlaceholderText('https://내-워드프레스-사이트.example')
        root.addWidget(self.wordpress_site)
        self.wordpress_username = QLineEdit()
        self.wordpress_username.setObjectName('publicationWordPressUser')
        self.wordpress_username.setPlaceholderText('WordPress 계정 아이디')
        root.addWidget(self.wordpress_username)
        self.wordpress_app_password = QLineEdit()
        self.wordpress_app_password.setObjectName('publicationWordPressAppPassword')
        self.wordpress_app_password.setEchoMode(QLineEdit.Password)
        self.wordpress_app_password.setPlaceholderText('WordPress Application Password (저장되지 않음)')
        root.addWidget(self.wordpress_app_password)
        self.wp_episodes = QComboBox()
        self.wp_episodes.setObjectName('publicationApprovedFinalEpisode')
        root.addWidget(self.wp_episodes)
        self.wp_owner_consent = QCheckBox(
            '선택한 최종 원고의 권리자이며 내 WordPress 사이트에 비공개 초안 업로드를 승인합니다')
        self.wp_owner_consent.setObjectName('publicationWordPressOwnerConsent')
        root.addWidget(self.wp_owner_consent)
        self.wp_send_button = QPushButton('WordPress 비공개 초안 전송 (추가 확인)')
        self.wp_send_button.setObjectName('publicationWordPressCreateDraft')
        root.addWidget(self.wp_send_button)
        self.wp_send_button.clicked.connect(self._send_wp_draft)
        self.wp_worker = None
        root.addStretch(1)
        self.export_button.clicked.connect(self._export)

    def refresh(self):
        s = self.session()
        self.cover_panel.refresh()
        prev = self.wp_episodes.currentData()
        self.wp_episodes.clear()
        if s is None or s.project_id is None:
            self.status.setText('작품 메뉴에서 먼저 소설을 생성하거나 열어 주세요.')
            return
        for item in s.store.list_episodes(s.project_id):
            if item.final_text.strip():
                self.wp_episodes.addItem(str(item.episode) + '화 최종본', item.episode)
        i = self.wp_episodes.findData(prev)
        if i >= 0:
            self.wp_episodes.setCurrentIndex(i)

    def _send_wp_draft(self):
        if self.wp_worker is not None and self.wp_worker.isRunning():
            return
        session = self.session()
        number = self.wp_episodes.currentData()
        if session is None or session.store is None or number is None:
            self.status.setText('먼저 최종 원고를 저장하고 회차를 선택하세요.')
            return
        if not self.wp_owner_consent.isChecked():
            self.status.setText('권리 보유 및 비공개 초안 업로드 승인이 필요합니다.')
            return
        self.wp_owner_consent.setChecked(False)
        episode = session.store.get_episode(session.project_id, number)
        if not episode.final_text.strip():
            self.status.setText('초고는 전송하지 않습니다. 검수 후 최종본을 저장하세요.')
            return
        # A second, synchronous user confirmation for the actual remote POST.
        answer = QMessageBox.question(
            self, '외부 서버 전송 확인',
            f'선택한 {number}화 최종본을 입력한 WordPress 서버로 전송합니다. '
            '공개 게시가 아니라 비공개 초안을 새로 작성합니다. 전송할까요?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            self.status.setText('외부 전송 취소됨. 원고는 로컬에 유지됩니다.')
            return
        self.wp_worker = _WordPressDraftWorker(
            self.wordpress_site.text(), self.wordpress_username.text(),
            self.wordpress_app_password.text(),
            session.store.get_project(session.project_id).title + ' — ' + str(number) + '화',
            episode.final_text, self)
        self.wordpress_app_password.clear()
        self.wp_send_button.setEnabled(False)
        self.wp_worker.completed.connect(self.status.setText)
        self.wp_worker.failed.connect(self.status.setText)
        self.wp_worker.finished.connect(self._wp_finished)
        self.status.setText('공식 WordPress API로 비공개 초안 전송 요청 중...')
        self.wp_worker.start()

    def _wp_finished(self):
        self.wp_send_button.setEnabled(True)
        if self.wp_worker is not None:
            self.wp_worker.deleteLater()
            self.wp_worker = None

    def _choose(self):
        path = QFileDialog.getExistingDirectory(self, '비공개 내보내기 폴더 선택')
        if path:
            self.directory.setText(path)

    def _cover_source(self):
        if not self.include_cover.isChecked():
            return None
        # Explicit opt-in only; never silently include another user's image.
        parent = Path(self.directory.text())
        if not parent.is_absolute() or parent.is_symlink() or not parent.is_dir():
            raise ValueError('기존 로컬 폴더만 지원합니다.')
        source = parent / 'cover.jpg'
        if source.is_symlink() or not source.is_file():
            raise ValueError('선택된 로컬 폴더에 표지 파일이 없습니다.')
        return source

    def _export_final(self):
        s = self.session()
        if s is None or s.project_id is None:
            self.status.setText('먼저 작품과 직접 검수한 최종 원고를 저장하세요.')
            return
        try:
            txt, epub = s.export_final(self.directory.text(), self.price.text(),
                                       cover_path=self._cover_source())
            self.status.setText(
                '검수 최종본 로컬 출력 완료: ' + txt.name + ', ' + epub.name
                + ' (reviewed_final 폴더, 게시·업로드 없음)')
        except (ValueError, OSError):
            self.status.setText(
                '검수본 출력 실패. 최종 원고·기존 출력 폴더·중복 파일·가격을 확인하세요.')

    def _export(self):
        s = self.session()
        if s is None or s.project_id is None:
            self.status.setText('작품 메뉴에서 먼저 소설을 생성하거나 열어 주세요.')
            return
        try:
            txt, epub = s.export(self.directory.text(), self.price.text(),
                                 cover_path=self._cover_source())
            self.status.setText('로컬 파일 생성 완료: ' + txt.name + ', ' + epub.name +
                                ' (게시·업로드하지 않았음)')
        except (ValueError, OSError):
            self.status.setText('내보내기 실패. 기존 폴더·원고·중복 파일·가격을 확인하세요.')
