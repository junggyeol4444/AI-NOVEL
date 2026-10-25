"""기존 Windows PySide6 작가 GUI의 SQLite 원본·새 복원 사본 읽기 전용 대조."""
from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_sqlite_copy_comparison import (
    AuthorCopyComparisonError, compare_author_sqlite_copy,
    require_current_author_copy_comparison,
)
from ai_novel_factory.author_sqlite_chapter_delta import (
    AuthorSqliteChapterDeltaError, build_author_sqlite_chapter_delta,
    read_author_sqlite_copy_chapter, read_author_sqlite_chapter_text_difference,
    require_current_author_sqlite_chapter_delta,
)
from .author_navigation_contract import select_saved_episode
from ai_novel_factory.project_local_handoff import (
    LocalHandoffError, NewCopyHandoff,
    require_idle_authoring, require_new_copy_handoff,
)


class AuthorSqliteCopyComparisonPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('기존 SQLite 원본 · 새 복원 사본 내용 직접 대조', parent)
        self.authoring = authoring
        self._copy = ''
        self._receipt = ''
        self._new_copy_handoff = None
        self._snapshot = None
        self._identity = None
        self._chapter_delta = None
        layout = QVBoxLayout(self)
        info = QLabel('기존 SQLite와 작가가 선택한 별도 복원 사본의 bible_ 테이블 실제 행을 '
                      '로컬에서 읽기 전용 대조합니다. 원고 본문은 표시하지 않습니다. '
                      '같은 내용이라도 실제 Windows 재열기 검증·품질 합격·출판 승인이 아닙니다.')
        info.setWordWrap(True)
        layout.addWidget(info)
        choose_copy = QPushButton('기존 새 복원 SQLite 사본 직접 선택')
        choose_copy.setObjectName('authorSqliteCopyChoose')
        choose_copy.clicked.connect(self.choose_copy)
        layout.addWidget(choose_copy)
        choose_receipt = QPushButton('해당 사본의 SHA 기록 JSON 직접 선택')
        choose_receipt.setObjectName('authorSqliteCopyReceipt')
        choose_receipt.clicked.connect(self.choose_receipt)
        layout.addWidget(choose_receipt)
        compare = QPushButton('원본·사본 저장 내용 읽기 전용 전수 대조 (첫 클릭)')
        compare.setObjectName('authorSqliteCopyCompare')
        compare.clicked.connect(self.compare)
        layout.addWidget(compare)
        self.handoff = QPushButton('확인한 사본을 기존 SQLite 재열기 화면에 선택만 전달 (두 번째 클릭)')
        self.handoff.setObjectName('authorSqliteCopyHandoff')
        self.handoff.setEnabled(False)
        self.handoff.clicked.connect(self.open_reopen_stage)
        layout.addWidget(self.handoff)
        row = QHBoxLayout()
        row.addWidget(QLabel('회차별 대조 마지막 회차'))
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('authorSqliteCopyChapterThrough')
        self.through.valueChanged.connect(self.invalidate_chapters)
        row.addWidget(self.through)
        self.chapter_compare = QPushButton('원본·사본 회차별 원고·장면·검수 실제 대조 (별도 클릭)')
        self.chapter_compare.setObjectName('authorSqliteCopyChapterCompare')
        self.chapter_compare.setEnabled(False)
        self.chapter_compare.clicked.connect(self.compare_chapters)
        row.addWidget(self.chapter_compare)
        layout.addLayout(row)
        self.chapter_table = QTableWidget(0, 9)
        self.chapter_table.setObjectName('authorSqliteCopyChapterTable')
        self.chapter_table.setHorizontalHeaderLabels((
            '회차', '원본 revision', '사본 revision', '플롯', '초고',
            '최종본', '요약', '장면', '검수 기록'))
        self.chapter_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.chapter_table)
        self.chapter_open = QPushButton('선택 회차의 기존 원본 편집기 열기 (별도 직접 클릭)')
        self.chapter_open.setObjectName('authorSqliteCopyChapterOpen')
        self.chapter_open.setEnabled(False)
        self.chapter_open.clicked.connect(self.open_source_chapter)
        layout.addWidget(self.chapter_open)
        self.copy_text_field = QComboBox()
        self.copy_text_field.setObjectName('authorSqliteCopyTextField')
        for label, key in (('플롯', 'plot'), ('초고', 'draft'),
                           ('최종본', 'final_text'), ('요약', 'summary')):
            self.copy_text_field.addItem(label, key)
        layout.addWidget(self.copy_text_field)
        self.copy_text_open = QPushButton('선택 회차의 사본 원문 읽기 전용 열람 (별도 직접 클릭)')
        self.copy_text_open.setObjectName('authorSqliteCopyChapterText')
        self.copy_text_open.setEnabled(False)
        self.copy_text_open.clicked.connect(self.open_copy_chapter_text)
        layout.addWidget(self.copy_text_open)
        self.copy_text_view = QPlainTextEdit()
        self.copy_text_view.setObjectName('authorSqliteCopyChapterTextView')
        self.copy_text_view.setReadOnly(True)
        self.copy_text_view.setPlaceholderText('작가가 사본 회차와 원문 종류를 직접 선택하면 이곳에만 표시합니다.')
        layout.addWidget(self.copy_text_view)
        self.original_text_view = QPlainTextEdit()
        self.original_text_view.setObjectName('authorSqliteOriginalChapterTextView')
        self.original_text_view.setReadOnly(True)
        self.original_text_view.setPlaceholderText(
            '원본·사본의 동일 저장 회차를 선택해 별도 대조하면 원본 전체 원문을 표시합니다.')
        layout.addWidget(self.original_text_view)
        self.text_difference = QPushButton(
            '선택 회차 원본·사본 원문 전체 대조 및 첫 차이 위치 (별도 클릭)')
        self.text_difference.setObjectName('authorSqliteTextDifference')
        self.text_difference.setEnabled(False)
        self.text_difference.clicked.connect(self.show_text_difference)
        layout.addWidget(self.text_difference)
        self.copy_text_field.currentIndexChanged.connect(self.clear_copy_text)
        self.chapter_table.itemSelectionChanged.connect(self.clear_copy_text)
        self.status = QLabel('현재 작품을 연 뒤 로컬 사본과 SHA 기록을 직접 선택하세요.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def clear_copy_text(self, *_args):
        self.copy_text_view.clear()
        self.original_text_view.clear()

    def invalidate_chapters(self, *_args):
        self._chapter_delta = None
        self.chapter_table.setRowCount(0)
        self.chapter_open.setEnabled(False)
        self.copy_text_open.setEnabled(False)
        self.text_difference.setEnabled(False)
        self.clear_copy_text()

    def invalidate(self, *_args):
        self.invalidate_chapters()
        self._snapshot = self._identity = None
        self.chapter_compare.setEnabled(False)
        self.handoff.setEnabled(False)
        self.status.setText('현재 원본·사본·기록을 다시 직접 조회하세요.')

    def choose_copy(self):
        path, _ = QFileDialog.getOpenFileName(self, '새 복원 사본 선택', '', 'SQLite (*.sqlite *.db)')
        if path:
            self._new_copy_handoff = None
            self._copy = path
            self.invalidate()

    def choose_receipt(self):
        path, _ = QFileDialog.getOpenFileName(self, '새 사본 SHA 기록 선택', '', 'JSON (*.json)')
        if path:
            self._new_copy_handoff = None
            self._receipt = path
            self.invalidate()

    def accept_new_copy_handoff(self, handoff: NewCopyHandoff) -> bool:
        """복원 화면이 생성한 사본/기록만 선택한다. DB 대조·열기는 실행 안 함."""
        try:
            if type(handoff) is not NewCopyHandoff:
                raise LocalHandoffError('기존 새 사본 인계 정보가 올바르지 않습니다.')
            session = self.authoring.session
            if (session.path is None or
                    str(session.project_id) != handoff.project_id):
                raise LocalHandoffError('작품 선택이 변경되었습니다.')
            require_idle_authoring(self.authoring, handoff.project_id)
            require_new_copy_handoff(handoff)
        except (LocalHandoffError, ValueError, OSError):
            self.status.setText('사본·원고·작품 정보가 달라 선택하지 않았습니다.')
            return False
        self.invalidate()
        self._new_copy_handoff = handoff
        self._copy = str(handoff.copy)
        self._receipt = str(handoff.receipt)
        self.status.setText(
            '생성한 새 사본·SHA 기록만 선택했습니다. '
            '내용 대조는 아래 첫 클릭 버튼에서 별도 실행하세요. '
            '원본/사본을 수정하지 않았습니다.')
        return True

    def compare(self):
        self.invalidate()
        try:
            session = self.authoring.session
            if session.path is None or session.project_id is None:
                raise AuthorCopyComparisonError('현재 작품을 먼저 열어 주세요.')
            project_id = str(session.project_id)
            require_idle_authoring(self.authoring, project_id)
            identity = (str(session.path), project_id)
            if self._new_copy_handoff is not None:
                require_new_copy_handoff(self._new_copy_handoff)
                if (self._new_copy_handoff.project_id != project_id
                        or str(self._new_copy_handoff.copy) != self._copy
                        or str(self._new_copy_handoff.receipt) != self._receipt):
                    raise LocalHandoffError('새 사본/기록 선택이 변경됐습니다.')
            snapshot = compare_author_sqlite_copy(
                session.path, self._copy, self._receipt, project_id)
        except (AuthorCopyComparisonError, LocalHandoffError, ValueError, OSError):
            self.status.setText('원본·사본·SHA 기록을 읽기 전용으로 대조하지 못했습니다.')
            return
        self._snapshot, self._identity = snapshot, identity
        self.handoff.setEnabled(True)
        self.chapter_compare.setEnabled(True)
        self.status.setText(
            f'원본 테이블 {snapshot.source_tables}개 · 사본 {snapshot.copy_tables}개 · '
            f'내용 동일 테이블 {snapshot.matched_tables}개 · 차이 후보 '
            f'{len(snapshot.differing_tables)}개 · 원본 저장 회차 {snapshot.source_episode_rows}개 · '
            f'사본 저장 회차 {snapshot.copy_episode_rows}개. '
            '원본과 사본의 생성 시점 차이는 정상일 수 있습니다. '
            '재열기·검수·출판은 별도 실행입니다.')

    def compare_chapters(self):
        """테이블 전체 대조 후 작가가 따로 누른 경우에만 1~N화 상세 비교."""
        self.invalidate_chapters()
        snapshot, identity = self._snapshot, self._identity
        if snapshot is None or identity is None:
            self.status.setText('먼저 원본·사본의 전체 저장 내용을 직접 대조하세요.')
            return
        try:
            session = self.authoring.session
            if (str(session.path), str(session.project_id)) != identity:
                raise AuthorSqliteChapterDeltaError('현재 작품이 변경됐습니다.')
            require_idle_authoring(self.authoring, identity[1])
            delta = build_author_sqlite_chapter_delta(
                snapshot, through_episode=self.through.value())
        except (AuthorSqliteChapterDeltaError, LocalHandoffError, ValueError, OSError):
            self.status.setText('원본·사본 회차별 원고·장면·검수 기록을 다시 직접 조회하세요.')
            return
        self._chapter_delta = delta
        self.chapter_table.setRowCount(len(delta.rows))
        for index, row in enumerate(delta.rows):
            values = (
                str(row.episode), str(row.source_revision or '없음'),
                str(row.copy_revision or '없음'),
                '다름' if row.plot_changed else '동일',
                '다름' if row.draft_changed else '동일',
                '다름' if row.final_changed else '동일',
                '다름' if row.summary_changed else '동일',
                '다름' if row.scene_changed else '동일',
                '다름' if row.check_changed else '동일',
            )
            for column, value in enumerate(values):
                self.chapter_table.setItem(index, column, QTableWidgetItem(value))
        self.chapter_open.setEnabled(bool(delta.rows))
        self.copy_text_open.setEnabled(any(row.copy_revision is not None for row in delta.rows))
        self.text_difference.setEnabled(any(
            row.source_revision is not None and row.copy_revision is not None
            for row in delta.rows))
        self.status.setText(
            f'{delta.through_episode}화 범위 · 원본에 없는 회차 {delta.missing_source}화 · '
            f'사본에 없는 회차 {delta.missing_copy}화 · 최종본 차이 {delta.changed_final}화 · '
            f'장면 차이 {delta.changed_scenes}화 · 검수 기록 차이 {delta.changed_checks}화. '
            '차이는 사본 생성 시점에 따른 것일 수 있습니다. 복원·검수·출판 승인 아님.')



    def show_text_difference(self):
        """작가가 고른 저장 원본/사본 전체 원문과 정확한 첫 차이만 로컬 표시."""
        self.clear_copy_text()
        delta, identity = self._chapter_delta, self._identity
        index = self.chapter_table.currentRow()
        if delta is None or identity is None or not 0 <= index < len(delta.rows):
            self.status.setText('회차별 대조를 조회하고 양쪽에 저장된 회차를 선택하세요.')
            return
        row = delta.rows[index]
        if row.source_revision is None or row.copy_revision is None:
            self.status.setText('원본과 사본에 모두 저장된 회차만 대조할 수 있습니다.')
            return
        field_name = self.copy_text_field.currentData()
        try:
            session = self.authoring.session
            if (str(session.path), str(session.project_id)) != identity:
                raise AuthorSqliteChapterDeltaError('현재 작품이 변경됐습니다.')
            require_idle_authoring(self.authoring, identity[1])
            evidence = read_author_sqlite_chapter_text_difference(
                delta, row.episode, field_name)
            if (self._chapter_delta is not delta or self._identity != identity
                    or self.chapter_table.currentRow() != index
                    or self.copy_text_field.currentData() != field_name):
                raise AuthorSqliteChapterDeltaError('작가의 선택이 변경됐습니다.')
            self.original_text_view.setPlainText(evidence.source_text)
            self.copy_text_view.setPlainText(evidence.copy_text)
            if (self.original_text_view.toPlainText() != evidence.source_text
                    or self.copy_text_view.toPlainText() != evidence.copy_text):
                raise AuthorSqliteChapterDeltaError('원문 표시 형식이 변경됐습니다.')
            if not evidence.identical:
                for editor, content, changed in (
                    (self.original_text_view, evidence.source_text,
                     evidence.source_changed_chars),
                    (self.copy_text_view, evidence.copy_text,
                     evidence.copy_changed_chars),
                ):
                    offset = evidence.common_prefix_chars
                    utf16_position = len(content[:offset].encode('utf-16-le')) // 2
                    cursor = editor.textCursor()
                    cursor.setPosition(utf16_position)
                    if changed:
                        length = len(content[offset:offset + min(changed, 1)]
                                     .encode('utf-16-le')) // 2
                        cursor.setPosition(utf16_position + length,
                                           QTextCursor.MoveMode.KeepAnchor)
                    editor.setTextCursor(cursor)
                    editor.ensureCursorVisible()
            self.status.setText(
                f'{row.episode}화 {self.copy_text_field.currentText()} · '
                f'원본 {len(evidence.source_text)}자/revision {evidence.source_revision} · '
                f'사본 {len(evidence.copy_text)}자/revision {evidence.copy_revision} · '
                + ('원문 완전 동일. ' if evidence.identical else
                   f'첫 차이 {evidence.common_prefix_chars + 1}번째 문자 · '
                   f'원본 차이 구간 {evidence.source_changed_chars}자 · '
                   f'사본 차이 구간 {evidence.copy_changed_chars}자 · '
                   f'공통 접미 {evidence.common_suffix_chars}자. ')
                + '읽기 전용 비교이며 사본 병합·원고 저장·검수·출판 승인 없음.')
        except (AuthorSqliteChapterDeltaError, LocalHandoffError,
                ValueError, OSError, LookupError):
            self.clear_copy_text()
            self.status.setText('원본·사본·회차·원문 또는 선택 상태가 변경됐습니다. 다시 대조하세요.')

    def open_copy_chapter_text(self):
        """원본·사본 대조를 다시 확인한 후 작가가 고른 사본 원문만 표시."""
        self.clear_copy_text()
        delta, identity = self._chapter_delta, self._identity
        index = self.chapter_table.currentRow()
        if delta is None or identity is None or not 0 <= index < len(delta.rows):
            self.status.setText('회차별 대조 후 사본에 저장된 회차를 직접 선택하세요.')
            return
        row = delta.rows[index]
        if row.copy_revision is None:
            self.status.setText('사본에 저장되지 않은 회차의 원문은 열 수 없습니다.')
            return
        try:
            session = self.authoring.session
            if (str(session.path), str(session.project_id)) != identity:
                raise AuthorSqliteChapterDeltaError('현재 작품이 변경됐습니다.')
            require_idle_authoring(self.authoring, identity[1])
            result = read_author_sqlite_copy_chapter(delta, row.episode)
            field = self.copy_text_field.currentData()
            if field not in ('plot', 'draft', 'final_text', 'summary'):
                raise AuthorSqliteChapterDeltaError('원문 종류를 다시 선택하세요.')
            content = getattr(result, field)
            self.copy_text_view.setPlainText(content)
            self.status.setText(
                f'{row.episode}화 사본 {self.copy_text_field.currentText()} '
                f'{len(content)}자 읽기 전용 표시. 원본 변경·사본 병합·검수·출판 승인 없음.')
        except (AuthorSqliteChapterDeltaError, LocalHandoffError,
                ValueError, OSError, LookupError):
            self.clear_copy_text()
            self.status.setText('현재 작품·사본·기록이 변경됐습니다. 다시 직접 대조하세요.')

    def open_source_chapter(self):
        """현재 원본 회차로만 이동한다. 사본 데이터 병합·저장·복원은 하지 않는다."""
        delta, identity = self._chapter_delta, self._identity
        index = self.chapter_table.currentRow()
        self.invalidate_chapters()
        if delta is None or identity is None or not 0 <= index < len(delta.rows):
            self.status.setText('대조한 원본 회차를 다시 직접 선택하세요.')
            return
        row = delta.rows[index]
        if row.source_revision is None:
            self.status.setText('원본에 저장되지 않은 회차는 기존 편집기로 이동할 수 없습니다.')
            return
        try:
            session = self.authoring.session
            if (str(session.path), str(session.project_id)) != identity:
                raise AuthorSqliteChapterDeltaError('작품이 변경됐습니다.')
            require_idle_authoring(self.authoring, identity[1])
            require_current_author_sqlite_chapter_delta(delta)
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=row.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
        except (AuthorSqliteChapterDeltaError, LocalHandoffError,
                ValueError, OSError, LookupError):
            self.status.setText('원본·사본 또는 회차가 변경됐습니다. 다시 직접 대조하세요.')
            return
        self.status.setText(
            f'{row.episode}화 기존 원본 편집기로 이동했습니다. '
            '사본 병합·원고 저장·검수·출판 승인은 수행하지 않았습니다.')

    def open_reopen_stage(self):
        snapshot, identity = self._snapshot, self._identity
        self.invalidate()  # 한 번 인계 후 이전 조회·승인 재사용 금지
        if snapshot is None or identity is None:
            return
        try:
            session = self.authoring.session
            if (str(session.path), str(session.project_id)) != identity:
                raise AuthorCopyComparisonError('현재 작품이 변경됐습니다.')
            require_idle_authoring(self.authoring, identity[1])
            require_current_author_copy_comparison(snapshot)
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature('sqlite_reopen_panel', project_identity=identity):
                raise AuthorCopyComparisonError('기존 재열기 화면을 열지 못했습니다.')
            panel = getattr(self.authoring, 'sqlite_reopen_panel', None)
            if panel is None or not panel.accept_author_copy_comparison(snapshot):
                raise AuthorCopyComparisonError('사본 선택 인계가 취소됐습니다.')
        except (AuthorCopyComparisonError, LocalHandoffError, ValueError, OSError):
            self.status.setText('현재 원고·SQLite·사본이 변경됐습니다. 다시 직접 조회하세요.')
            return
        self.status.setText('기존 SQLite 재열기에 사본 선택만 전달했습니다. 실제 열기는 별도 직접 클릭입니다.')
