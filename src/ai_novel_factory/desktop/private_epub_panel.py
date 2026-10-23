"""Existing Windows/PySide6 authoring screen: private EPUB3 cover/export/reader.

No automatic export or publication; every file selection and export is manual.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)
from ai_novel_factory.private_epub_workflow import (
    PrivateEpubWorkflowError, create_private_epub_from_saved_finals,
    plan_private_epub,
)


class PrivateEpubPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('비공개 EPUB3 · 사용자 원고·표지·로컬 리더', parent)
        self.authoring = authoring
        self._source_stamp = None
        root = QVBoxLayout(self)
        self.notice = QLabel(
            'SQLite에 저장된 실제 최종본만 사용합니다. 원고가 누락되면 중단합니다. '
            '비공개 미리보기는 문학 품질 합격·출판 승인·업로드가 아닙니다.')
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        self.last_episode = QSpinBox()
        self.last_episode.setObjectName('privateEpubLastEpisode')
        self.last_episode.setRange(1, 1000)
        self.last_episode.setValue(1)
        root.addWidget(self.last_episode)
        self.metadata = QLineEdit()
        self.metadata.setObjectName('privateEpubMetadataPath')
        self.metadata.setReadOnly(True)
        self.cover = QLineEdit()
        self.cover.setObjectName('privateEpubCoverPath')
        self.cover.setReadOnly(True)
        self.output = QLineEdit()
        self.output.setObjectName('privateEpubOutputPath')
        self.output.setReadOnly(True)
        for label, edit, handler in (
            ('기존 로컬 메타데이터 JSON', self.metadata, self._choose_metadata),
            ('작가가 선택한 JPEG 표지 (선택)', self.cover, self._choose_cover),
            ('기존 로컬 출력 폴더', self.output, self._choose_output)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(edit)
            button = QPushButton('선택')
            button.clicked.connect(handler)
            row.addWidget(button)
            root.addLayout(row)
        self.preview = QPushButton('저장된 최종본 누락·검수 상태 미리보기')
        self.preview.setObjectName('privateEpubPlan')
        self.preview.clicked.connect(self.show_plan)
        root.addWidget(self.preview)
        self.consent = QCheckBox('이번 한 번만 비공개 EPUB3 미리보기 파일 생성을 승인합니다')
        self.consent.setObjectName('privateEpubConsent')
        root.addWidget(self.consent)
        self.create = QPushButton('비공개 EPUB3 새 파일 생성 (출판 아님)')
        self.create.setObjectName('privateEpubCreate')
        self.create.clicked.connect(self.create_preview)
        root.addWidget(self.create)
        self.status = QLabel('먼저 현재 작품을 열고 EPUB 미리보기 상태를 확인하세요.')
        self.status.setObjectName('privateEpubStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.last_episode.valueChanged.connect(self._invalidate)

    def _invalidate(self, *_args):
        self._source_stamp = None
        self.consent.setChecked(False)

    def _choose_metadata(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, '기존 로컬 EPUB 메타데이터', '', 'JSON (*.json)')
        if filename:
            self.metadata.setText(filename)
            self._invalidate()

    def _choose_cover(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, 'JPEG 표지 선택', '', 'JPEG (*.jpg *.jpeg)')
        if filename:
            self.cover.setText(filename)
            self._invalidate()

    def _choose_output(self):
        filename = QFileDialog.getExistingDirectory(self, '기존 로컬 출력 폴더')
        if filename:
            self.output.setText(filename)
            self._invalidate()

    def show_plan(self):
        session = self.authoring.session
        self._invalidate()
        if session.store is None or session.project_id is None:
            self.status.setText('먼저 로컬 작품을 열어 주세요.')
            return
        try:
            plan = plan_private_epub(
                session.store, session.project_id,
                through_episode=self.last_episode.value())
        except (PrivateEpubWorkflowError, ValueError, OSError):
            self.status.setText('현재 작품의 EPUB 계획을 읽을 수 없습니다.')
            return
        self._source_stamp = (session.project_id, plan.source_sha256)
        self.status.setText(
            f'대상 {plan.through_episode}화 / 최종본 {plan.chapters}화 / '
            f'누락 {len(plan.missing_final)}화 / 검수 기록 {plan.reviewed_current}화 / '
            f'검수 미완료 {len(plan.unreviewed)}화. 출판 미승인.')

    def create_preview(self):
        session = self.authoring.session
        stamp = self._source_stamp
        if (stamp is None or session.store is None or
                session.project_id != stamp[0] or not self.consent.isChecked()):
            self.status.setText('현재 작품 미리보기 상태 확인과 이번 실행 승인이 필요합니다.')
            return
        self.consent.setChecked(False)
        try:
            result = create_private_epub_from_saved_finals(
                session.store, stamp[0],
                through_episode=self.last_episode.value(),
                metadata_file=self.metadata.text(),
                output_directory=self.output.text(),
                cover_file=self.cover.text() or None,
                expected_source_sha256=stamp[1], explicit_private_preview=True)
        except (PrivateEpubWorkflowError, ValueError, OSError):
            self.status.setText('EPUB3 생성 실패 · 기존 파일을 덮어쓰지 않았습니다.')
            self._source_stamp = None
            return
        self._source_stamp = None
        self.status.setText(
            f'비공개 EPUB3 {result.chapters}화 새 파일 생성 · '
            '기존 로컬 EPUB 읽기 메뉴에서 확인하세요. 출판 승인·업로드 없음.')
