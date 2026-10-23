"""Windows PySide6 UI for author-approved private EPUB3 volume creation."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from ai_novel_factory.epub_volume_workflow import (
    EpubVolumeError, create_private_epub_volume, plan_epub_volumes,
)


class EpubVolumePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('EPUB3 1~1000화 권별 비공개 미리보기 · 출판 아님', parent)
        self.authoring = authoring
        self._stamp = None
        self._volumes = ()
        root = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(250)
        root.addWidget(self.through)
        self.preview = QPushButton('현재 저장 최종본의 EPUB3 권별 분할 계획 조회')
        self.preview.setObjectName('epubVolumePlan')
        self.preview.clicked.connect(self.show_plan)
        root.addWidget(self.preview)
        self.volume_index = QSpinBox()
        self.volume_index.setRange(1, 1)
        root.addWidget(self.volume_index)
        self.metadata = self._file_row(root, '기존 EPUB 메타데이터 JSON', 'JSON (*.json)',
                                       'metadata')
        self.toc = self._file_row(root, '작가 목차 JSON (선택)', 'JSON (*.json)', 'toc')
        self.cover = self._file_row(root, 'JPEG 표지 (선택)', 'JPEG (*.jpg *.jpeg)', 'cover')
        row = QHBoxLayout()
        row.addWidget(QLabel('현재 권 전용 기존 출력 폴더'))
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        row.addWidget(self.output)
        choose = QPushButton('선택')
        choose.clicked.connect(self._choose_output)
        row.addWidget(choose)
        root.addLayout(row)
        self.consent = QCheckBox('선택한 이 한 권의 비공개 EPUB 새 파일 생성을 직접 승인합니다')
        root.addWidget(self.consent)
        self.create = QPushButton('선택 권 비공개 EPUB3 새 파일 생성 (출판/업로드 없음)')
        self.create.setObjectName('epubVolumeCreate')
        self.create.clicked.connect(self.create_volume)
        root.addWidget(self.create)
        self.status = QLabel('먼저 현재 작품과 권별 분할 계획을 조회하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.through.valueChanged.connect(self.invalidate)
        self.volume_index.valueChanged.connect(self._revoke_consent)

    def _file_row(self, layout, label, filter_text, name):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setReadOnly(True)
        row.addWidget(edit)
        choose = QPushButton('선택')
        choose.clicked.connect(lambda: self._choose_file(edit, label, filter_text))
        row.addWidget(choose)
        layout.addLayout(row)
        return edit

    def _choose_file(self, edit, label, filter_text):
        path, _ = QFileDialog.getOpenFileName(self, label, '', filter_text)
        if path:
            edit.setText(path)
            self._revoke_consent()

    def _choose_output(self):
        path = QFileDialog.getExistingDirectory(self, '현재 권의 기존 로컬 출력 폴더')
        if path:
            self.output.setText(path)
            self._revoke_consent()

    def _revoke_consent(self, *_args):
        self.consent.setChecked(False)

    def invalidate(self, *_args):
        self._stamp = None
        self._volumes = ()
        self._revoke_consent()
        self.status.setText('작품 또는 범위가 변경되었습니다. 권별 계획을 다시 조회하세요.')

    def show_plan(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품을 먼저 열어야 합니다.')
            return
        try:
            plan = plan_epub_volumes(session.store, str(session.project_id),
                                     through_episode=self.through.value())
        except (EpubVolumeError, ValueError, OSError):
            self.status.setText('현재 저장된 최종본의 권별 계획을 읽지 못했습니다.')
            return
        self._stamp = (str(session.project_id), plan.through_episode,
                       plan.source_sha256)
        self._volumes = plan.volumes
        self.volume_index.setMaximum(max(1, len(plan.volumes)))
        self.status.setText(
            f'{plan.through_episode}화 / {len(plan.volumes)}권 / '
            f'최종본 누락 {len(plan.missing_final)}화 / '
            f'권당 크기 초과 {len(plan.oversized_final)}화. '
            '각 권은 기존의 별도 출력 폴더를 직접 선택해야 합니다. '
            '생성 결과는 비공개 미검수 EPUB이며 출판 승인이 아닙니다.')

    def create_volume(self):
        session = self.authoring.session
        stamp = self._stamp
        if (stamp is None or session.store is None or
                str(session.project_id) != stamp[0] or
                not self.consent.isChecked()):
            self.status.setText('현재 작품의 권별 계획과 이번 한 권 생성 승인이 필요합니다.')
            return
        self._revoke_consent()
        try:
            result = create_private_epub_volume(
                session.store, stamp[0], through_episode=stamp[1],
                volume_index=self.volume_index.value(),
                expected_source_sha256=stamp[2],
                metadata_file=self.metadata.text(),
                output_directory=self.output.text(),
                cover_file=self.cover.text() or None,
                toc_manifest_file=self.toc.text() or None,
                explicit_private_preview=True)
        except (EpubVolumeError, ValueError, OSError):
            self._stamp = None
            self.status.setText('권별 EPUB 생성이 완료되지 않았습니다. '
                                '현재 원고·메타데이터·출력 폴더를 다시 확인하세요.')
            return
        self._stamp = None
        if not result.source_current_after_export:
            self.status.setText('비공개 EPUB 파일은 새로 생성되었지만 생성 중 원고가 변경되어 '
                                '이 파일은 과거 버전입니다. 출판 승인 아님.')
            return
        self.status.setText(
            f'{result.volume.index}권 ({result.volume.first_episode}~'
            f'{result.volume.last_episode}화) 비공개 EPUB3 새 파일 생성. '
            '기존 로컬 Reader에서 직접 열어 확인하세요. 출판 승인·업로드 없음.')
