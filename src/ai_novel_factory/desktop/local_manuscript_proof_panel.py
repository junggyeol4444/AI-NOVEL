"""Author-approved private TXT/MD final-text proofing UI, never publishes."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QLabel, QPushButton,
    QSpinBox, QVBoxLayout,
)

from ai_novel_factory.local_manuscript_proof import (
    ManuscriptProofError, create_manuscript_proof, plan_manuscript_proof,
)


class LocalManuscriptProofPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('최종 원고 TXT/MD 비공개 교정본 (출판 아님)', parent)
        self.authoring = authoring
        self._plan = None
        self._directory = ''
        root = QVBoxLayout(self)
        label = QLabel('저장된 최종본 1~1000화를 로컬 교정용 새 폴더에만 출력합니다. '
                       '미검수·QC 미완료 상태를 명시하며 외부 업로드·자동 출판하지 않습니다.')
        label.setWordWrap(True)
        root.addWidget(label)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate)
        root.addWidget(self.through)
        self.format = QComboBox()
        self.format.addItem('UTF-8 TXT', 'txt')
        self.format.addItem('Markdown MD', 'md')
        self.format.currentIndexChanged.connect(self.invalidate)
        root.addWidget(self.format)
        preview = QPushButton('현재 최종본·검수 상태 읽기 전용 계획')
        preview.setObjectName('privateProofPreview')
        preview.clicked.connect(self.preview)
        root.addWidget(preview)
        choose = QPushButton('기존 로컬 교정본 출력 폴더 선택')
        choose.clicked.connect(self.choose_folder)
        root.addWidget(choose)
        self.approved = QCheckBox('현재 원고의 비공개 TXT/MD 교정본을 새 폴더에 저장하는 이번 1회를 승인합니다')
        root.addWidget(self.approved)
        save = QPushButton('새 비공개 교정본 생성 (원본·기존 파일 덮어쓰기 없음)')
        save.setObjectName('privateProofExplicit')
        save.clicked.connect(self.export)
        root.addWidget(save)
        self.status = QLabel('현재 작품을 열고 회차 범위를 선택하세요. 출판 승인이 아닙니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def invalidate(self, *_args):
        self._plan = None
        self.approved.setChecked(False)
        self.status.setText('원고/회차/형식 선택 변경: 이전 계획과 승인을 폐기했습니다.')

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '기존 로컬 교정본 출력 폴더')
        if folder:
            self._directory = folder
            self.approved.setChecked(False)
            self.status.setText('출력 폴더를 선택했습니다. 현재 교정본 계획을 확인하고 승인하세요.')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            raise ManuscriptProofError('기존 작품을 먼저 열어야 합니다.')
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            raise ManuscriptProofError('AI 집필 중에는 교정본을 만들 수 없습니다.')
        return session.store, str(session.project_id)

    def preview(self):
        self.invalidate()
        try:
            store, project_id = self._current()
            self._plan = plan_manuscript_proof(
                store, project_id, through_episode=self.through.value())
            self.status.setText(f'{self._plan.through_episode}화 최종본 확인 · '
                                f'인간 검수 미완료 {self._plan.unreviewed}화 · '
                                f'QC 미완료 {self._plan.qc_incomplete}화. '
                                '비공개 교정본이며 출판 승인이 아닙니다.')
        except (ManuscriptProofError, OSError, ValueError):
            self.status.setText('현재 선택 범위에 저장된 최종본이 모두 있는지 확인하세요.')

    def export(self):
        plan = self._plan
        approved = self.approved.isChecked()
        self._plan = None
        self.approved.setChecked(False)
        if plan is None or not approved:
            self.status.setText('현재 최종본 계획과 이번 출력의 별도 승인이 필요합니다.')
            return
        try:
            store, project_id = self._current()
            receipt = create_manuscript_proof(
                store, project_id, plan, self._directory,
                file_format=self.format.currentData(), explicit_author_export=True)
            self.status.setText(f'로컬 비공개 교정본 {receipt.chapter_count}화 생성. '
                                f'상태: {receipt.status}. '
                                '출판/외부 전송/품질 합격 아님.')
        except (ManuscriptProofError, OSError, ValueError):
            self.status.setText('교정본 생성이 완료되지 않았습니다. 원고와 출력 폴더를 다시 확인하세요.')
