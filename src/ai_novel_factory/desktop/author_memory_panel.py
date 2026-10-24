"""Windows PySide6 author-only memory delta editor; no auto approvals."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QLabel, QLineEdit, QPushButton,
                               QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..author_memory_final_alignment import (
    AuthorMemoryFinalAlignmentError, build_author_memory_final_alignment,
    require_current_author_memory_final_alignment,
    read_author_memory_episode_evidence,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode
from ..author_memory_delta import (AuthorMemoryDeltaError,
                                   add_author_memory_delta, retract_author_memory_delta,
                                   list_author_memory_deltas, memory_delta_fingerprint)


class AuthorMemoryPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 기록 장편 기억 변화', parent)
        self.authoring = authoring
        self.folder: Path | None = None
        self.approved_fingerprint: str | None = None
        self._final_alignment = None
        self._final_identity = None
        self._final_evidence = None
        root = QVBoxLayout(self)
        info = QLabel('근거가 되는 기존 최종 원고를 직접 읽고 기억 변화를 기록하세요. '
                      '저장·철회는 각각 별도 승인하며 원고/SQLite는 변경하지 않습니다.')
        info.setWordWrap(True)
        root.addWidget(info)
        self.choose = QPushButton('기존 로컬 기억 기록 폴더 선택')
        self.choose.clicked.connect(self.choose_folder)
        root.addWidget(self.choose)
        self.to_context = QPushButton('선택한 기억 폴더를 기존 통합 집필 문맥 화면에 인계')
        self.to_context.clicked.connect(self.open_in_context_composer)
        root.addWidget(self.to_context)
        form = QFormLayout(); root.addLayout(form)
        self.source = QSpinBox(); self.source.setRange(1, 999)
        self.start = QSpinBox(); self.start.setRange(2, 1000)
        self.end = QSpinBox(); self.end.setRange(2, 1000); self.end.setValue(1000)
        self.category = QComboBox()
        for value, title in (('character', '인물'), ('relationship', '인물 관계'),
                             ('plot', '사건'), ('foreshadow', '복선'),
                             ('timeline', '시간선'), ('world', '세계관'),
                             ('style', '서술·말투')):
            self.category.addItem(title, value)
        self.subject = QLineEdit(); self.subject.setMaxLength(60)
        self.change = QPlainTextEdit(); self.change.setMaximumHeight(100)
        form.addRow('근거 최종본 회차', self.source)
        form.addRow('적용 시작 회차', self.start)
        form.addRow('적용 마지막 회차', self.end)
        form.addRow('기억 유형', self.category)
        form.addRow('대상', self.subject)
        form.addRow('작가 직접 작성 변화', self.change)
        self.save_agree = QCheckBox('위 기억 변화 기록을 이번 클릭에 한해 새 파일에 저장합니다')
        form.addRow(self.save_agree)
        self.add_btn = QPushButton('기억 변화 기록 추가')
        self.add_btn.clicked.connect(self.add)
        form.addRow(self.add_btn)
        self.existing = QComboBox()
        form.addRow('기존 기록 직접 선택', self.existing)
        self.retract_agree = QCheckBox('선택한 기억 기록의 철회를 이번 클릭에 한해 승인합니다')
        form.addRow(self.retract_agree)
        self.retract_btn = QPushButton('기록 철회 (원본 기록 삭제 안 함)')
        self.retract_btn.clicked.connect(self.retract)
        form.addRow(self.retract_btn)
        self.refresh_btn = QPushButton('현재 로컬 기록 다시 읽기')
        self.refresh_btn.clicked.connect(self.refresh)
        root.addWidget(self.refresh_btn)
        self.batch_consent = QCheckBox('현재 로컬 기억 기록 지문을 이번 AI 집필 배치 문맥에 1회 사용하는 데 동의합니다')
        self.batch_consent.toggled.connect(self._approve)
        root.addWidget(self.batch_consent)
        self.status = QLabel('기억 기록을 작성해도 모델 실행/품질 검사/출판 승인은 자동으로 일어나지 않습니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        # 저장된 최종본과 기존 기억 변화 원장 전체의 별도 읽기 전용 대조.
        self.final_scope = QSpinBox()
        self.final_scope.setRange(1, 1000)
        self.final_scope.setValue(30)
        self.final_scope.valueChanged.connect(self.invalidate_final_alignment)
        root.addWidget(QLabel('기억 변화·저장 최종본 전체 대조 범위 (1~1000화)'))
        root.addWidget(self.final_scope)
        self.final_read = QPushButton('작가 기억 변화·저장 최종본 전수 대조 (읽기 전용)')
        self.final_read.setObjectName('authorMemoryFinalReadOnly')
        self.final_read.clicked.connect(self.preview_final_alignment)
        root.addWidget(self.final_read)
        self.final_table = QTableWidget(0, 8)
        self.final_table.setHorizontalHeaderLabels([
            '회차', '최종본 글자', '적용 기억', '근거 변경',
            '대상 출현', '변화 문구 출현', '변화 문구 미출현', '최종본 누락',
        ])
        self.final_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.final_table.setMaximumHeight(250)
        root.addWidget(self.final_table)
        self.final_evidence_button = QPushButton(
            '선택 회차의 저장 최종본·적용 기억 원문 직접 열람 (읽기 전용)')
        self.final_evidence_button.setObjectName('authorMemoryFinalEvidence')
        self.final_evidence_button.clicked.connect(self.preview_final_evidence)
        root.addWidget(self.final_evidence_button)
        self.final_evidence_text = QPlainTextEdit()
        self.final_evidence_text.setReadOnly(True)
        self.final_evidence_text.setMaximumHeight(280)
        root.addWidget(self.final_evidence_text)
        self.final_table.itemSelectionChanged.connect(self._clear_final_evidence)
        self.final_status = QLabel('NOT_RUN: 작가가 먼저 전수 대조를 직접 실행하세요.')
        self.final_status.setWordWrap(True)
        root.addWidget(self.final_status)
        self.final_open = QPushButton('선택한 저장 회차를 기존 원고 편집기로 이동 (별도 클릭)')
        self.final_open.setEnabled(False)
        self.final_open.clicked.connect(self.open_final_alignment)
        root.addWidget(self.final_open)
        for control in (self.source, self.start, self.end, self.category):
            signal = control.currentIndexChanged if isinstance(control, QComboBox) else control.valueChanged
            signal.connect(self._clear_approval)
        self.subject.textChanged.connect(self._clear_approval)
        self.change.textChanged.connect(self._clear_approval)

    def _clear_approval(self, *_):
        self.approved_fingerprint = None
        self.batch_consent.blockSignals(True)
        self.batch_consent.setChecked(False)
        self.batch_consent.blockSignals(False)

    def invalidate(self):
        self.invalidate_final_alignment()
        self._clear_approval()
        self.folder = None
        self.existing.clear()
        self.subject.clear(); self.change.clear()
        self.save_agree.setChecked(False)
        self.retract_agree.setChecked(False)
        self.status.setText('작품 변경으로 이전 기억 폴더/동의가 무효화되었습니다.')

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, '기존 로컬 기억 기록 폴더 선택')
        if chosen:
            self.invalidate_final_alignment()
            self.folder = Path(chosen)
            self._clear_approval()
            self.save_agree.setChecked(False)
            self.retract_agree.setChecked(False)
            self.refresh()

    def open_in_context_composer(self):
        """Explicit selection handoff only; no model call or batch consent."""
        try:
            _store, project_id = self.authoring.session.required()
            if self.folder is None:
                raise AuthorMemoryDeltaError('기존 기억 폴더를 먼저 선택하세요.')
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            identity = (str(self.authoring.session.path), str(project_id))
            if hub is None or not hub.open_feature(
                    'author_context_composer_panel', project_identity=identity):
                raise AuthorMemoryDeltaError('기존 통합 집필 문맥 화면을 열지 못했습니다.')
            composer = getattr(self.authoring, 'author_context_composer_panel', None)
            if composer is None:
                raise AuthorMemoryDeltaError('통합 문맥 화면을 다시 열어 주세요.')
            composer.accept_existing_memory_folder(self.folder)
            self.status.setText('기억 기록 폴더를 통합 문맥에 선택했습니다. 집필 사용 동의는 별도입니다.')
        except (AuthorMemoryDeltaError, ValueError, OSError):
            self.status.setText('현재 작품·기억 기록을 다시 선택하세요. 원고/DB는 변경하지 않았습니다.')

    def refresh(self):
        self.invalidate_final_alignment()
        self._clear_approval()
        self.existing.clear()
        if self.folder is None:
            self.status.setText('기존 로컬 폴더를 직접 선택하세요.')
            return
        try:
            _store, pid = self.authoring.session.required()
            records = list_author_memory_deltas(self.folder, str(pid))
            for item in records:
                if not item.retracted:
                    self.existing.addItem(f'{item.source_episode}화 → {item.valid_from}~{item.valid_through}화 · '
                                          f'{item.category} · {item.subject}', item.delta_id)
            self.status.setText(f'현재 작가 기억 기록 중 활성 {self.existing.count()}건 · 읽기 전용 조회')
        except (AuthorMemoryDeltaError, ValueError, OSError):
            self.status.setText('기억 기록을 안전하게 읽을 수 없습니다. 원본은 수정하지 않았습니다.')

    def add(self):
        self.invalidate_final_alignment()
        agreed = self.save_agree.isChecked()
        self.save_agree.setChecked(False)
        self._clear_approval()
        try:
            if self.folder is None:
                raise AuthorMemoryDeltaError('기존 폴더 선택 필요')
            store, pid = self.authoring.session.required()
            add_author_memory_delta(store, str(pid), folder=self.folder,
                                    source_episode=self.source.value(),
                                    valid_from=self.start.value(), valid_through=self.end.value(),
                                    category=str(self.category.currentData()),
                                    subject=self.subject.text(), change=self.change.toPlainText(),
                                    explicit_author_save=agreed)
            self.refresh()
            self.status.setText('작가 승인에 따라 별도의 새 기억 사건 파일을 저장했습니다.')
        except (ValueError, OSError):
            self.status.setText('승인/근거/범위/중복을 확인하세요. 기존 파일은 변경하지 않았습니다.')

    def retract(self):
        self.invalidate_final_alignment()
        agreed = self.retract_agree.isChecked()
        self.retract_agree.setChecked(False)
        self._clear_approval()
        try:
            if self.folder is None or not self.existing.currentData():
                raise AuthorMemoryDeltaError('철회 기록 선택 필요')
            _store, pid = self.authoring.session.required()
            retract_author_memory_delta(self.folder, str(pid), str(self.existing.currentData()),
                                        explicit_author_retract=agreed)
            self.refresh()
            self.status.setText('별도 철회 사건을 추가했습니다. 기존 사실 기록은 삭제하지 않았습니다.')
        except (ValueError, OSError):
            self.status.setText('철회 기록과 직접 승인을 확인하세요. 기존 파일은 변경하지 않았습니다.')

    def _approve(self, checked):
        self.approved_fingerprint = None
        if not checked:
            return
        try:
            self.authoring.session.required()
            if self.folder is None:
                raise AuthorMemoryDeltaError('기억 폴더 선택 필요')
            self.approved_fingerprint = memory_delta_fingerprint(self.folder)
            self.status.setText('현재 기억 기록 파일의 SHA만 이번 문맥 1회 사용으로 승인했습니다. 모델 실행 별도 승인 필요.')
        except (ValueError, OSError):
            self._clear_approval()

    def consume_approved_memory(self) -> tuple[str, str] | None:
        """Use only at author-directed batch start, never at GUI initialization."""
        if not self.batch_consent.isChecked():
            return None
        path, stamp = self.folder, self.approved_fingerprint
        self._clear_approval()
        if path is None or not stamp or memory_delta_fingerprint(path) != stamp:
            raise AuthorMemoryDeltaError('기억 기록이 변경돼 동의를 다시 받아야 합니다.')
        return str(path), stamp

    def _clear_final_evidence(self, *_args):
        self._final_evidence = None
        if hasattr(self, 'final_evidence_text'):
            self.final_evidence_text.clear()

    def invalidate_final_alignment(self, *_args):
        self._clear_final_evidence()
        self._final_alignment = None
        self._final_identity = None
        if hasattr(self, 'final_table'):
            self.final_table.setRowCount(0)
            self.final_open.setEnabled(False)
            self.final_status.setText('작품·기억 원장·범위·저장 원고 변경 시 다시 조회하세요.')

    def preview_final_alignment(self):
        self.invalidate_final_alignment()
        try:
            session, identity = _current_author_state(self.authoring)
            if self.folder is None:
                raise AuthorMemoryFinalAlignmentError('기존 기억 폴더 선택 필요')
            snapshot = build_author_memory_final_alignment(
                session.store, identity[1], folder=self.folder,
                through_episode=self.final_scope.value())
        except (AuthorMemoryFinalAlignmentError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.final_status.setText('현재 작품·저장 원고·작가 기억 기록을 읽지 못했습니다.')
            return
        self._final_alignment = snapshot
        self._final_identity = identity
        self.final_table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            cells = (row.episode, row.final_characters, row.applicable_memories,
                     row.stale_sources, row.subject_found, row.change_found,
                     row.change_not_found, '예' if row.missing_final else '아니요')
            for column, value in enumerate(cells):
                self.final_table.setItem(index, column, QTableWidgetItem(str(value)))
        self.final_open.setEnabled(True)
        self.final_status.setText(
            f'{snapshot.through_episode}화 직접 대조: 저장 최종본 누락 '
            f'{snapshot.missing_final_chapters}화, 기억 근거 변경 '
            f'{snapshot.stale_source_chapters}화, 검토 후보 '
            f'{snapshot.candidate_chapters}화. 정확한 문자열 출현만 집계했으며 '
            '문학 품질·QC·출판 승인 판정이 아닙니다.')


    def preview_final_evidence(self):
        """작가가 직접 선택한 저장 회차의 최종본·기억 원문을 별도 클릭으로 표시."""
        self._clear_final_evidence()
        snapshot, identity = self._final_alignment, self._final_identity
        index = self.final_table.currentRow()
        if (snapshot is None or identity is None
                or not 0 <= index < len(snapshot.rows)):
            self.final_status.setText('먼저 기억·최종본을 전수 대조하고 회차를 선택하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity or self.final_scope.value() != snapshot.through_episode:
                raise AuthorMemoryFinalAlignmentError('작품 또는 조회 범위가 변경됐습니다.')
            if self.folder is None or str(self.folder.resolve()) != snapshot.folder:
                raise AuthorMemoryFinalAlignmentError('기억 기록 폴더가 변경됐습니다.')
            evidence = read_author_memory_episode_evidence(
                snapshot, session.store, identity[1],
                episode=snapshot.rows[index].episode)
            lines = [
                f'{evidence.episode}화 저장 최종본 · revision {evidence.revision}',
                '작가 직접 작성 기억 변화와 저장 원고의 정확한 문자열 일치 여부입니다.',
                '문학 품질·QC 합격·출판 승인 판정이 아닙니다.',
                f'적용 기억 {len(evidence.memories)}건',
            ]
            for number, memory in enumerate(evidence.memories, 1):
                lines.extend((
                    '',
                    f'[{number}] 유형: {memory.category} / 근거: {memory.source_episode}화',
                    f'근거 최종본 현재 일치: {"예" if memory.source_current else "아니요"}',
                    f'대상 문자열 출현: {"예" if memory.subject_present else "아니요"}',
                    f'변화 문자열 출현: {"예" if memory.change_present else "아니요"}',
                    f'작가 대상: {memory.subject}',
                    '작가 직접 작성 변화:',
                    memory.change,
                ))
            lines.extend(('', '=== 선택 회차 SQLite 저장 최종본 전체 ===', evidence.final_text))
            self._final_evidence = evidence
            self.final_evidence_text.setPlainText('\n'.join(lines))
            self.final_status.setText(
                f'{evidence.episode}화 원문과 적용 기억을 읽기 전용으로 표시했습니다. '
                '저장·모델 실행·QC·출판 승인은 수행하지 않았습니다.')
        except (AuthorMemoryFinalAlignmentError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.final_status.setText(
                '저장 최종본 또는 기억 원장이 변경됐습니다. 전수 대조부터 다시 실행하세요.')

    def open_final_alignment(self):
        snapshot, identity = self._final_alignment, self._final_identity
        row_index = self.final_table.currentRow()
        if (snapshot is None or identity is None
                or not 0 <= row_index < len(snapshot.rows)):
            self.final_status.setText('먼저 전수 대조하고 이동할 회차를 직접 선택하세요.')
            return
        row = snapshot.rows[row_index]
        self.invalidate_final_alignment()
        if row.revision is None:
            self.final_status.setText('저장되지 않은 회차는 자동 생성하지 않습니다.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity or self.final_scope.value() != snapshot.through_episode:
                raise AuthorMemoryFinalAlignmentError('작품 또는 조회 범위가 변경됐습니다.')
            if self.folder is None or str(self.folder.resolve()) != snapshot.folder:
                raise AuthorMemoryFinalAlignmentError('기억 폴더가 변경됐습니다.')
            require_current_author_memory_final_alignment(
                snapshot, session.store, identity[1])
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=row.episode)
            self.final_status.setText(decision.message)
        except (AuthorMemoryFinalAlignmentError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.final_status.setText('기억 기록·원고 변경으로 이전 인계를 무효화했습니다.')
