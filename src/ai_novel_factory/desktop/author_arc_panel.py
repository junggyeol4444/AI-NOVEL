"""PySide6 desktop: author-only, append-only story-arc planning."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QSpinBox, QPushButton, QCheckBox, QFileDialog,
    QListWidget, QTableWidget, QTableWidgetItem)
from ..author_arc_ledger import (AuthorArcError, add_author_arc,
                                 read_author_arcs, withdraw_author_arc)
from ..author_arc_final_coverage import (
    AuthorArcFinalCoverageError, build_author_arc_final_coverage,
    require_current_author_arc_final_coverage,
    read_author_arc_episode_evidence,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode, _busy, _unsaved

class AuthorArcPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 장편 아크 계획 · 로컬 전용', parent)
        self.authoring = authoring
        self._folder = None
        self._bound = None
        self._coverage_snapshot = None
        self._coverage_identity = None
        form = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(form)
        self.folder_label = QLabel('로컬 계획 폴더 미선택')
        self.folder_label.setWordWrap(True)
        choose = QPushButton('기존 아크 기록 폴더 직접 선택')
        choose.clicked.connect(self.choose_folder)
        form.addRow(choose)
        form.addRow(self.folder_label)
        self.start = QSpinBox(); self.start.setRange(1, 1000)
        self.end = QSpinBox(); self.end.setRange(1, 1000); self.end.setValue(30)
        form.addRow('시작 회차', self.start); form.addRow('종료 회차', self.end)
        self.title_input = QLineEdit()
        form.addRow('아크 제목', self.title_input)
        self.fields = {}
        for key, label in [('objective','장편 목표'),('conflict','주요 갈등'),
                           ('foreshadow','복선 계획'),('resolution','해소 계획')]:
            edit=QPlainTextEdit();edit.setMaximumHeight(66)
            self.fields[key]=edit;form.addRow(label,edit)
        self.preview = QListWidget();self.preview.setMaximumHeight(130)
        root.addWidget(self.preview)
        self.coverage_through = QSpinBox()
        self.coverage_through.setRange(1, 1000)
        self.coverage_through.setValue(30)
        form.addRow('최종본 대조 종료 회차', self.coverage_through)
        self.coverage_episode = QSpinBox()
        self.coverage_episode.setRange(1, 1000)
        form.addRow('아크 안에서 직접 열 회차', self.coverage_episode)
        coverage_button = QPushButton('기존 아크·저장 최종본 복선·해소 범위 직접 대조')
        coverage_button.setObjectName('authorArcFinalCoveragePreview')
        coverage_button.clicked.connect(self.preview_saved_arc_coverage)
        root.addWidget(coverage_button)
        self.coverage_table = QTableWidget(0, 8)
        self.coverage_table.setObjectName('authorArcFinalCoverageTable')
        self.coverage_table.setHorizontalHeaderLabels((
            '작가 아크', '회차 범위', '저장 최종본', '누락 회차',
            '복선 문자열 회차', '해소 문자열 회차', '설정 변경', '순서 검토 후보'))
        self.coverage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.coverage_table.setMaximumHeight(230)
        root.addWidget(self.coverage_table)
        self.coverage_status = QLabel('NOT_RUN: 작가가 기존 아크 폴더를 선택한 뒤 직접 조회하세요.')
        self.coverage_status.setWordWrap(True)
        root.addWidget(self.coverage_status)
        self.coverage_open = QPushButton('선택 아크·직접 지정 회차를 기존 편집기로 열기 (별도 클릭)')
        self.coverage_open.setObjectName('authorArcFinalCoverageOpen')
        self.coverage_open.setEnabled(False)
        self.coverage_open.clicked.connect(self.open_saved_arc_coverage)
        root.addWidget(self.coverage_open)
        self.coverage_detail_button = QPushButton('선택 아크·회차의 저장 최종본 복선·해소 근거 읽기 (별도 클릭)')
        self.coverage_detail_button.setObjectName('authorArcEpisodeEvidenceOpen')
        self.coverage_detail_button.setEnabled(False)
        self.coverage_detail_button.clicked.connect(self.show_saved_arc_episode_evidence)
        root.addWidget(self.coverage_detail_button)
        self.coverage_detail_status = QLabel('선택 회차의 원문 근거는 별도 작가 클릭 후에만 표시합니다.')
        self.coverage_detail_status.setWordWrap(True)
        root.addWidget(self.coverage_detail_status)
        self.coverage_detail_text = QPlainTextEdit()
        self.coverage_detail_text.setObjectName('authorArcEpisodeEvidenceText')
        self.coverage_detail_text.setReadOnly(True)
        self.coverage_detail_text.setMaximumHeight(260)
        root.addWidget(self.coverage_detail_text)
        self.coverage_episode.valueChanged.connect(self.clear_coverage_detail)
        self.coverage_table.itemSelectionChanged.connect(self.clear_coverage_detail)
        self.coverage_through.valueChanged.connect(self.invalidate_coverage)
        self.save_consent = QCheckBox('위 내용을 이번 한 번 새 로컬 기록으로 저장하는 데 동의')
        self.withdraw_consent = QCheckBox('선택한 아크 기록을 이번 한 번 철회하는 데 동의')
        root.addWidget(self.save_consent);root.addWidget(self.withdraw_consent)
        self.batch_approval = QCheckBox('이번 AI 집필 한 번에만 현재 작가 아크 계획을 사용합니다')
        root.addWidget(self.batch_approval)
        self._batch_project = None
        self._batch_stamp = None
        self.batch_approval.toggled.connect(self._bind_batch)
        save = QPushButton('새 아크 기록 저장');save.clicked.connect(self.save_arc)
        remove = QPushButton('선택한 아크 철회');remove.clicked.connect(self.withdraw_arc)
        refresh=QPushButton('현재 아크 목록 읽기');refresh.clicked.connect(self.refresh)
        root.addWidget(save);root.addWidget(remove);root.addWidget(refresh)
        self.status=QLabel('저장·철회는 작가가 직접 누른 때에만 별도 JSON으로 기록합니다.')
        self.status.setWordWrap(True);root.addWidget(self.status)
        for obj in (self.start,self.end):obj.valueChanged.connect(self._revoke_save)
        self.title_input.textChanged.connect(self._revoke_save)
        for obj in self.fields.values():obj.textChanged.connect(self._revoke_save)

    def _revoke_save(self, *args):
        self.save_consent.setChecked(False)

    def invalidate(self):
        self.invalidate_coverage()
        self.save_consent.setChecked(False);self.withdraw_consent.setChecked(False)
        self.batch_approval.setChecked(False)
        self.preview.clear();self._bound=None
        self.status.setText('작품이 변경되어 아크 승인과 목록을 초기화했습니다.')

    def _project(self):
        session=self.authoring.session
        db,pid=session.required()
        current=(str(session.path),str(pid))
        return db,str(pid),current

    def _bind_batch(self, enabled):
        self._batch_project = None
        self._batch_stamp = None
        if enabled:
            try:
                _, pid, bound = self._project()
                if self._folder is None:
                    raise AuthorArcError('기록 폴더 선택 필요')
                from ..author_arc_ledger import arc_ledger_fingerprint
                self._batch_project = bound
                self._batch_stamp = arc_ledger_fingerprint(self._folder)
            except (AuthorArcError, ValueError, OSError):
                self.batch_approval.setChecked(False)
                self.status.setText('작품·로컬 아크 기록 폴더를 먼저 확인하세요.')

    def consume_batch_folder(self) -> str | None:
        if not self.batch_approval.isChecked():
            return None
        try:
            _, _, bound = self._project()
            from ..author_arc_ledger import arc_ledger_fingerprint
            if (self._folder is None or self._batch_project != bound
                    or self._batch_stamp != arc_ledger_fingerprint(self._folder)):
                raise AuthorArcError('아크 기록이 변경되었습니다.')
            return str(self._folder)
        finally:
            self.batch_approval.setChecked(False)

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'작가 아크 JSON 기록용 기존 로컬 폴더')
        if path:
            self._folder=Path(path)
            self.folder_label.setText('기존 로컬 폴더 선택됨 (원고 SQLite와 별도)')
            self.invalidate()

    def refresh(self):
        self.invalidate_coverage()
        self.preview.clear();self.withdraw_consent.setChecked(False)
        try:
            _,pid,bound=self._project()
            if self._folder is None:raise AuthorArcError('폴더를 먼저 선택하세요.')
            arcs=read_author_arcs(self._folder,pid)
            for arc in arcs:
                status='철회' if arc.withdrawn else '작가 기록'
                self.preview.addItem(f'{arc.start}~{arc.end}화 · {arc.title} · {status}')
                self.preview.item(self.preview.count()-1).setData(256,arc.arc_id)
            self._bound=bound
            self.status.setText(f'작가 아크 기록 {len(arcs)}개 조회. 현재 품질 PASS·출판 승인 없음.')
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('현재 작품의 아크 기록을 읽을 수 없습니다.')

    def save_arc(self):
        approved=self.save_consent.isChecked();self.save_consent.setChecked(False)
        try:
            db,pid,_=self._project()
            if self._folder is None:raise AuthorArcError('기존 계획 폴더 선택 필요')
            add_author_arc(db,pid,folder=self._folder,start=self.start.value(),
                end=self.end.value(),title=self.title_input.text(),
                objective=self.fields['objective'].toPlainText(),
                conflict=self.fields['conflict'].toPlainText(),
                foreshadow=self.fields['foreshadow'].toPlainText(),
                resolution=self.fields['resolution'].toPlainText(),
                explicit_author_save=approved)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('아크를 저장하지 않았습니다. 회차 범위·승인·입력값을 확인하세요.')

    def withdraw_arc(self):
        approved=self.withdraw_consent.isChecked();self.withdraw_consent.setChecked(False)
        try:
            _,pid,bound=self._project()
            current=self.preview.currentItem()
            if not approved or current is None or self._bound!=bound:
                raise AuthorArcError('기록과 철회 승인을 다시 선택하세요.')
            withdraw_author_arc(self._folder,pid,current.data(256),explicit_author_withdraw=True)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('아크 철회를 실행하지 않았습니다. 다시 확인하세요.')

    def clear_coverage_detail(self, *_args):
        self.coverage_detail_text.clear()
        self.coverage_detail_status.setText('회차·아크를 선택하고 별도 클릭으로 현재 저장 원문을 조회하세요.')

    def invalidate_coverage(self, *_args):
        self.clear_coverage_detail()
        self.coverage_detail_button.setEnabled(False)
        self._coverage_snapshot = None
        self._coverage_identity = None
        self.coverage_table.setRowCount(0)
        self.coverage_open.setEnabled(False)
        self.coverage_status.setText('아크·작품·원고·범위 변경 시 직접 다시 조회하세요.')

    def preview_saved_arc_coverage(self):
        self.invalidate_coverage()
        try:
            session, identity = _current_author_state(self.authoring)
            if self._folder is None:
                raise AuthorArcFinalCoverageError('기존 아크 폴더를 직접 선택하세요.')
            snapshot = build_author_arc_final_coverage(
                session.store, identity[1], folder=self._folder,
                through_episode=self.coverage_through.value())
        except (AuthorArcFinalCoverageError, BatchScopeBridgeError,
                AuthorArcError, ValueError, OSError, LookupError):
            self.coverage_status.setText('기존 아크·저장 최종본을 읽지 못했습니다. 자동 승인 없음.')
            return
        self._coverage_snapshot, self._coverage_identity = snapshot, identity
        self.coverage_table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            values = (row.title, f'{row.start}~{row.end}화',
                      str(row.stored_final), str(row.missing_final),
                      str(row.foreshadow_hits), str(row.resolution_hits),
                      '재확인' if row.canon_changed else '변경 없음',
                      '검토 후보' if row.order_candidate else '확정 아님')
            for col, value in enumerate(values):
                self.coverage_table.setItem(index, col, QTableWidgetItem(value))
        self.coverage_open.setEnabled(bool(snapshot.rows))
        self.coverage_detail_button.setEnabled(bool(snapshot.rows))
        self.coverage_status.setText(
            f'기존 아크 {len(snapshot.rows)}개 대조 / '
            f'작가 검토 후보 {snapshot.review_candidate_count}개. '
            '복선·해소 문장과 최종본의 정확한 문자열 비교이며 '
            '실제 서사 해소·품질 합격·출판 승인 판정이 아닙니다.')

    def open_saved_arc_coverage(self):
        snapshot, identity = self._coverage_snapshot, self._coverage_identity
        index = self.coverage_table.currentRow()
        number = self.coverage_episode.value()
        self._coverage_snapshot = None
        self._coverage_identity = None
        self.coverage_open.setEnabled(False)
        if (snapshot is None or identity is None
                or not 0 <= index < len(snapshot.rows)
                or self._folder is None
                or str(self._folder.resolve()) != snapshot.folder
                or self.coverage_through.value() != snapshot.through_episode):
            self.coverage_status.setText('조회한 아크를 다시 직접 선택하세요.')
            return
        arc = snapshot.rows[index]
        if not arc.start <= number <= min(arc.end, snapshot.through_episode):
            self.coverage_status.setText('선택한 아크 안의 저장 회차를 직접 지정하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise AuthorArcFinalCoverageError('작품이 변경됐습니다.')
            require_current_author_arc_final_coverage(
                snapshot, session.store, identity[1])
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=number)
            self.coverage_status.setText(decision.message)
        except (AuthorArcFinalCoverageError, BatchScopeBridgeError,
                AuthorArcError, ValueError, OSError, LookupError):
            self.coverage_status.setText('아크·원고가 변경됐거나 저장 회차를 열 수 없습니다.')


    def show_saved_arc_episode_evidence(self):
        """두 번째 작가 클릭: 현재 원고·아크를 재확인한 뒤 읽기 전용 표시."""
        self.clear_coverage_detail()
        snapshot, identity = self._coverage_snapshot, self._coverage_identity
        index = self.coverage_table.currentRow()
        number = self.coverage_episode.value()
        if (snapshot is None or identity is None
                or not 0 <= index < len(snapshot.rows)
                or self._folder is None
                or str(self._folder.resolve()) != snapshot.folder
                or self.coverage_through.value() != snapshot.through_episode):
            self.coverage_detail_status.setText('아크·조회 범위를 다시 직접 선택하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity or _busy(self.authoring) or _unsaved(self.authoring):
                raise AuthorArcFinalCoverageError('작품·미저장 원고·집필 상태가 변경됐습니다.')
            detail = read_author_arc_episode_evidence(
                snapshot, session.store, identity[1],
                arc_id=snapshot.rows[index].arc_id, episode=number)
            if (_busy(self.authoring) or _unsaved(self.authoring)
                    or _current_author_state(self.authoring)[1] != identity
                    or self.coverage_table.currentRow() != index
                    or self.coverage_episode.value() != number):
                raise AuthorArcFinalCoverageError('선택이나 집필 상태가 변경됐습니다.')
            self.coverage_detail_text.setPlainText(detail.final_text)
            self.coverage_detail_status.setText(
                f'{detail.episode}화 저장 최종본 전체 원문 · revision {detail.revision} · '
                f'복선 표현 {detail.foreshadow_count}회 (앞 {len(detail.foreshadow_offsets)}개 '
                f'문자 위치: {detail.foreshadow_offsets}) · '
                f'해소 표현 {detail.resolution_count}회 (앞 {len(detail.resolution_offsets)}개 '
                f'문자 위치: {detail.resolution_offsets}). '
                '문자열 발견은 서사 완성·QC 합격·출판 승인이 아닙니다.')
        except (AuthorArcFinalCoverageError, BatchScopeBridgeError,
                AuthorArcError, ValueError, OSError, LookupError):
            self.clear_coverage_detail()
            self.coverage_detail_status.setText(
                '아크·저장 원고·작품 또는 미저장/집필 상태가 변경됐습니다. 다시 조회하세요.')
