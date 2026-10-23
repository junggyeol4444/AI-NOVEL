"""Windows PySide6 manual evidence file selector and structured finding view."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFileDialog,
)
from ai_novel_factory.evidence_review_workflow import (
    plan_evidence_review, review_saved_evidence, write_empty_evidence_manifest,
    EvidenceReviewWorkflowError,
)


class EvidenceReviewPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('회차 원고 근거 · 인물 지식·복선·시간선·세계관', parent)
        self.authoring = authoring
        self._expected = None
        self._bound = None
        root = QVBoxLayout(self)
        notice = QLabel('작가가 직접 표시한 근거만 확인합니다. 표시하지 않은 문장과 문학 품질은 '
                        '검증되지 않으며, 자동 합격·출판 승인은 없습니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.source = QComboBox()
        self.source.addItem('저장된 최종본', 'final')
        self.source.addItem('저장된 초고', 'draft')
        self.source.setObjectName('evidenceReviewSource')
        root.addWidget(self.source)
        self.manifest = QLineEdit()
        self.manifest.setReadOnly(True)
        self.manifest.setObjectName('evidenceManifestFile')
        row = QHBoxLayout()
        row.addWidget(self.manifest)
        choose = QPushButton('작가 근거 JSON 선택')
        choose.setObjectName('evidenceChooseManifest')
        choose.clicked.connect(self.choose_manifest)
        row.addWidget(choose)
        root.addLayout(row)
        template = QPushButton('빈 근거 JSON 템플릿 새 파일 저장 (기존 파일 보존)')
        template.setObjectName('evidenceCreateTemplate')
        template.clicked.connect(self.create_template)
        root.addWidget(template)
        self.inspect = QPushButton('현재 원고 근거 확인 (명시적 실행)')
        self.inspect.setObjectName('evidenceInspectSaved')
        self.inspect.clicked.connect(self.inspect_evidence)
        root.addWidget(self.inspect)
        self.status = QLabel('원고·근거 미선택: NOT_EXAMINED')
        self.status.setObjectName('evidenceReviewStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.source.currentIndexChanged.connect(self.invalidate)

    def invalidate(self, *_args):
        self._expected = None
        self._bound = None
        self.status.setText('현재 원고·근거를 다시 선택해야 합니다. NOT_EXAMINED')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None or not session.episode_number:
            raise EvidenceReviewWorkflowError('먼저 로컬 작품과 회차를 선택하세요.')
        return session, session.project_id, session.episode_number

    def choose_manifest(self):
        filename, _ = QFileDialog.getOpenFileName(self, '기존 로컬 근거 JSON', '', 'JSON (*.json)')
        if filename:
            self.manifest.setText(filename)
            self.invalidate()

    def create_template(self):
        filename, _ = QFileDialog.getSaveFileName(self, '새 근거 JSON 템플릿', '', 'JSON (*.json)')
        if not filename:
            return
        try:
            session, project, episode = self._current()
            write_empty_evidence_manifest(
                session.store, project, episode, source=self.source.currentData(),
                destination=filename)
        except (ValueError, OSError):
            self.status.setText('근거 템플릿 저장 실패. 기존 파일은 덮어쓰지 않습니다.')
            return
        self.manifest.setText(filename)
        self.invalidate()
        self.status.setText('빈 근거 템플릿 생성. 작가가 근거 위치를 입력해야 합니다. 자동 합격 아님.')

    def inspect_evidence(self):
        self.invalidate()
        try:
            session, project, episode = self._current()
            source = self.source.currentData()
            plan = plan_evidence_review(session.store, project, episode, source=source)
            result = review_saved_evidence(
                session.store, session.path, project, episode, source=source,
                manifest_path=self.manifest.text(), expected=plan)
        except (ValueError, OSError):
            self.status.setText('근거 확인 불가 또는 변경 감지. 검사 합격으로 기록하지 않았습니다.')
            return
        self._expected = plan
        self._bound = (project, episode, source)
        labels = {'continuity': '설정', 'character_knowledge': '인물 지식',
                  'foreshadowing': '복선', 'timeline': '시간선'}
        lines = []
        for item in result.sections:
            lines.append(f'{labels.get(item.category, item.category)}: '
                         f'표시 {item.examined}건 / 발견 {item.findings}건 / {item.status}')
        self.status.setText('\n'.join(lines) + '\n표시한 범위만 확인됨 · '
                            '원고 전체 검사/출판 승인 아님 · 사람 검수 필수')
