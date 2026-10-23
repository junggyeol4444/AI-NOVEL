"""기존 Windows PySide6 화면에서 EPUB3 자료를 직접 대조·인계한다."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)
from ai_novel_factory.author_epub_materials_lease import (
    EpubMaterialsLeaseError, preview_epub_materials, require_current_epub_materials,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError


class AuthorEpubMaterialsPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('EPUB3 메타데이터·목차·표지 직접 대조·인계', parent)
        self.authoring = authoring
        self._identity = None
        self._lease = None
        root = QVBoxLayout(self)
        note = QLabel('선택한 기존 자료를 읽기 전용으로 확인합니다. '
                      '검수 합격·출판 승인·EPUB 생성은 하지 않습니다.')
        note.setWordWrap(True)
        root.addWidget(note)
        self.through = QSpinBox()
        self.through.setObjectName('authorEpubMaterialsThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        root.addWidget(QLabel('마지막 회차'))
        root.addWidget(self.through)
        self.metadata = self._file_row(root, '기존 메타데이터 JSON', 'JSON (*.json)')
        self.toc = self._file_row(root, '작가 목차 JSON (선택)', 'JSON (*.json)')
        self.cover = self._file_row(root, 'JPEG 표지 (선택)', 'JPEG (*.jpg *.jpeg)')
        actions = QHBoxLayout()
        self.preview_button = QPushButton('현재 저장 원고·검수·자료 직접 대조')
        self.preview_button.setObjectName('authorEpubMaterialsPreview')
        self.preview_button.clicked.connect(self.preview)
        actions.addWidget(self.preview_button)
        self.handoff_button = QPushButton('대조 자료를 기존 EPUB3 다권 화면에 인계')
        self.handoff_button.setObjectName('authorEpubMaterialsHandoff')
        self.handoff_button.setEnabled(False)
        self.handoff_button.clicked.connect(self.handoff)
        actions.addWidget(self.handoff_button)
        root.addLayout(actions)
        self.status = QLabel('작품과 기존 자료를 선택하고 조회하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.through.valueChanged.connect(self.invalidate)

    def _file_row(self, layout, label, filter_text):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.textChanged.connect(self.invalidate)
        row.addWidget(edit)
        button = QPushButton('선택')
        button.clicked.connect(lambda: self._choose(edit, label, filter_text))
        row.addWidget(button)
        layout.addLayout(row)
        return edit

    def _choose(self, edit, label, filter_text):
        path, _ = QFileDialog.getOpenFileName(self, label, '', filter_text)
        if path:
            edit.setText(path)

    def invalidate(self, *_args):
        self._identity = None
        self._lease = None
        self.handoff_button.setEnabled(False)
        self.status.setText('작품·자료·회차를 다시 조회하세요.')

    def preview(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            lease = preview_epub_materials(
                session.store, identity[1], through_episode=self.through.value(),
                metadata_file=self.metadata.text(), toc_file=self.toc.text(),
                cover_file=self.cover.text())
        except (BatchScopeBridgeError, EpubMaterialsLeaseError, OSError, ValueError):
            self.status.setText('현재 작품·미저장 원고·자료를 확인한 뒤 다시 조회하세요.')
            return
        self._identity, self._lease = identity, lease
        self.handoff_button.setEnabled(
            lease.missing_final == 0 and lease.oversized_final == 0)
        self.status.setText(
            f'{lease.through_episode}화 / {lease.volume_count}권 / '
            f'최종본 누락 {lease.missing_final} / 크기 초과 {lease.oversized_final} / '
            f'QC 확인 {lease.qc_actions} / 수동 검수 {lease.human_review_actions} / '
            f'참고작 확인 {lease.reference_actions}. '
            '이 조회는 검수·저작권·출판 승인이나 EPUB 생성이 아닙니다.')

    def handoff(self):
        lease, identity = self._lease, self._identity
        self._lease = self._identity = None
        self.handoff_button.setEnabled(False)
        if lease is None or identity is None:
            self.status.setText('먼저 현재 자료를 직접 조회하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise EpubMaterialsLeaseError('현재 작품이 변경됐습니다.')
            require_current_epub_materials(lease, session.store, identity[1])
            if lease.missing_final or lease.oversized_final:
                raise EpubMaterialsLeaseError('최종본 누락·크기 초과로 인계 보류')
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'epub_volume_panel', project_identity=identity):
                raise EpubMaterialsLeaseError('기존 EPUB 화면을 열지 못했습니다.')
            panel = getattr(self.authoring, 'epub_volume_panel', None)
            if panel is None or not hasattr(panel, 'accept_author_materials'):
                raise EpubMaterialsLeaseError('기존 EPUB 인계 기능이 없습니다.')
            panel.accept_author_materials(lease, identity)
        except (BatchScopeBridgeError, EpubMaterialsLeaseError, OSError, ValueError):
            self.status.setText('원고·검수·자료가 변경됐거나 인계하지 못했습니다. 다시 조회하세요.')
            return
        self.status.setText('기존 다권 화면에 파일 선택만 전달했습니다. '
                            '권별 계획·출력 폴더·한 권 생성 승인은 다시 직접 선택하세요.')
