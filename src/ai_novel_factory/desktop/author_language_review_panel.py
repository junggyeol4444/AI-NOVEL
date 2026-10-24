"""Offline, read-only author-language context and candidate-spelling review UI."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QFormLayout, QLabel, QSpinBox, QComboBox,
    QPushButton, QFileDialog, QPlainTextEdit, QTableWidget, QTableWidgetItem,
)
from ..author_language_context import (build_author_language_context,
                                       review_discouraged_spelling)
from ..author_language_ledger import AuthorLanguageError
from ..author_language_scope_audit import (
    build_author_language_scope_audit, require_current_author_language_scope_audit,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode


class AuthorLanguageReviewPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 언어 규칙 · 회차별 표기 검토 후보 (읽기 전용)', parent)
        self.authoring = authoring
        self.folder: Path | None = None
        self._scope = None
        self._scope_identity = None
        root = QVBoxLayout(self)
        note = QLabel('검토 후보는 단순 표기 출현이며 오류 확정·문학 품질 PASS가 아닙니다. 원고 자동 변경 없음.')
        note.setWordWrap(True); root.addWidget(note)
        form = QFormLayout(); root.addLayout(form)
        self.episode = QSpinBox(); self.episode.setRange(1, 1000)
        form.addRow('검토할 저장 회차', self.episode)
        self.source = QComboBox(); self.source.addItem('저장 최종 원고', 'final_text')
        self.source.addItem('저장 초고', 'draft')
        form.addRow('원고 종류', self.source)
        choose = QPushButton('기존 로컬 작가 언어 규칙 폴더 선택')
        choose.clicked.connect(self.choose_folder); root.addWidget(choose)
        read = QPushButton('회차별 권장 표기·비권장 표현 후보 조회')
        read.clicked.connect(self.refresh); root.addWidget(read)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(285); root.addWidget(self.preview)
        self.status = QLabel('원고·모델·참고작에 쓰거나 외부 전송하지 않습니다.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.episode.valueChanged.connect(self._clear)
        self.source.currentIndexChanged.connect(self._clear)

        # 기존 작가 언어 규칙/SQLite 저장 최종본의 1~1000화 범위 조회.
        # 별도 버튼을 눌러야만 원본 편집기로 이동하며 저장·QC·출판은 하지 않는다.
        scope_form = QFormLayout()
        self.scope_through = QSpinBox()
        self.scope_through.setObjectName('authorLanguageScopeThrough')
        self.scope_through.setRange(1, 1000)
        self.scope_through.setValue(30)
        scope_form.addRow('저장 최종본 언어 규칙 전수 조회 마지막 회차', self.scope_through)
        root.addLayout(scope_form)
        scope_button = QPushButton('작가 규칙·저장 최종본 1~선택 회차 전수 조회 (첫 클릭)')
        scope_button.setObjectName('authorLanguageScopePreview')
        scope_button.clicked.connect(self.refresh_scope)
        root.addWidget(scope_button)
        self.scope_table = QTableWidget(0, 7)
        self.scope_table.setObjectName('authorLanguageScopeTable')
        self.scope_table.setHorizontalHeaderLabels((
            '회차', '공백 제외 글자', '적용 규칙', '과거 설정 규칙',
            '비권장 출현', '권장 출현', '조회 상태'))
        self.scope_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.scope_table.setMaximumHeight(260)
        self.scope_table.currentCellChanged.connect(self.show_scope_details)
        root.addWidget(self.scope_table)
        self.scope_details = QPlainTextEdit()
        self.scope_details.setReadOnly(True)
        self.scope_details.setMaximumHeight(120)
        root.addWidget(self.scope_details)
        self.scope_open = QPushButton('선택 저장 회차를 기존 원본 편집기로 열기 (별도 두 번째 클릭)')
        self.scope_open.setObjectName('authorLanguageScopeOpenExisting')
        self.scope_open.setEnabled(False)
        self.scope_open.clicked.connect(self.open_scope_episode)
        root.addWidget(self.scope_open)
        self.scope_status = QLabel('기존 언어 규칙 폴더 선택 후 작가가 직접 조회하세요. 자동 합격 없음.')
        self.scope_status.setWordWrap(True)
        root.addWidget(self.scope_status)
        self.scope_through.valueChanged.connect(self._clear_scope)

    def _clear_scope(self, *_):
        self._scope = self._scope_identity = None
        self.scope_table.setRowCount(0)
        self.scope_details.clear()
        self.scope_open.setEnabled(False)
        self.scope_status.setText('작품·원고·규칙·조회 범위를 다시 직접 확인하세요.')

    def _clear(self, *_):
        self.preview.clear()
        self.status.setText('선택이 변경됐습니다. 직접 다시 조회하세요.')
        self._clear_scope()

    def invalidate(self):
        self._clear()
        self.folder = None
        self.status.setText('작품이 변경됐습니다. 로컬 규칙 폴더를 다시 선택하세요.')

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, '기존 로컬 언어 규칙 폴더')
        if chosen:
            self.folder = Path(chosen)
            self._clear()

    def refresh(self):
        self.preview.clear()
        try:
            if self.folder is None:
                raise AuthorLanguageError('로컬 언어 규칙 폴더 선택 필요')
            store, project_id = self.authoring.session.required()
            number = self.episode.value()
            state = build_author_language_context(store, str(project_id),
                episode=number, folder=self.folder)
            if not state.configured:
                self.status.setText('이 회차의 활성 작가 언어 규칙이 없습니다. 자동 통과가 아닙니다.')
                return
            if state.stale:
                self.status.setText('작품 설정이 달라졌습니다. 언어 규칙을 수동으로 다시 확인하세요.')
                return
            episode = store.get_episode(str(project_id), number)
            manuscript = getattr(episode, str(self.source.currentData()))
            hints = review_discouraged_spelling(manuscript, state)
            lines = [f'{number}화 · 현재 작가 직접 기록 규칙 {len(state.applicable)}개',
                     '==== 작성 참고 문맥 (QC/출판 승인 아님) ====',
                     state.prompt_text,
                     '==== 현재 저장 원고의 비권장 표기 단순 검색 결과 (작가 검토 후보) ====']
            if hints:
                for hint in hints:
                    lines.append(f'- {hint.subject} / {hint.unexpected_form}: {hint.count}회 · 첫 위치 {hint.first_offset + 1}')
            else:
                lines.append('해당 규칙의 비권장 표기 출현이 발견되지 않았음. 품질 검증 PASS 아님.')
            self.preview.setPlainText('\n'.join(lines))
            self.status.setText('로컬 원고 읽기만 수행. 자동 교정·원고 저장·QC 승인 없음.')
        except (AuthorLanguageError, OSError, ValueError):
            self.status.setText('규칙 또는 회차 원고 조회를 완료하지 못했습니다.')
        except Exception:
            self.status.setText('로컬 회차 데이터를 읽을 수 없습니다. 원고는 변경하지 않았습니다.')

    def refresh_scope(self):
        self._clear_scope()
        try:
            if self.folder is None:
                raise AuthorLanguageError('기존 작가 언어 규칙 폴더를 직접 선택하세요.')
            session, identity = _current_author_state(self.authoring)
            audit = build_author_language_scope_audit(
                session.store, identity[1], folder=self.folder,
                through_episode=self.scope_through.value())
            self._scope, self._scope_identity = audit, identity
            self.scope_table.setRowCount(len(audit.chapters))
            for index, chapter in enumerate(audit.chapters):
                values = (chapter.episode, chapter.final_characters,
                          chapter.active_rules, chapter.stale_rules,
                          chapter.avoided_occurrences, chapter.preferred_occurrences,
                          chapter.status)
                for col, value in enumerate(values):
                    self.scope_table.setItem(index, col, QTableWidgetItem(str(value)))
            self.scope_open.setEnabled(True)
            self.scope_status.setText(
                f'1~{audit.through_episode}화 저장 최종본 조회: 누락 {audit.missing_final}화, '
                f'과거 설정 규칙 포함 {audit.stale_rule_chapters}화, '
                f'비권장 표기 후보 {audit.chapters_with_candidates}화 '
                f'총 {audit.total_candidate_occurrences}회. '
                '모든 회차 원문을 조회했으나 문학 품질·QC·출판 합격은 아닙니다.')
        except (AuthorLanguageError, BatchScopeBridgeError, OSError, ValueError, LookupError):
            self._clear_scope()
            self.scope_status.setText('작가 규칙 또는 저장 최종본 전수 조회를 완료하지 못했습니다.')

    def show_scope_details(self, row, _column, *_):
        audit = self._scope
        if audit is None or not 0 <= row < len(audit.chapters):
            self.scope_details.clear()
            return
        chapter = audit.chapters[row]
        lines = [f'{chapter.episode}화 · {chapter.status}',
                 f'비권장 표기 후보 {chapter.avoided_forms}종 / {chapter.avoided_occurrences}회',
                 '표시된 후보는 원고 오류 확정이 아닙니다.']
        for finding in chapter.findings_preview:
            lines.append(f'{finding.subject} / {finding.avoided_form}: {finding.occurrences}회')
        if chapter.avoided_forms > len(chapter.findings_preview):
            lines.append('나머지 후보는 표에 개수만 집계됨. 자동 교정 없음.')
        self.scope_details.setPlainText('\n'.join(lines))

    def open_scope_episode(self):
        audit, identity = self._scope, self._scope_identity
        row = self.scope_table.currentRow()
        if audit is None or identity is None or not 0 <= row < len(audit.chapters):
            self.scope_status.setText('먼저 전수 조회하고 저장 회차를 직접 선택하세요.')
            return
        chapter = audit.chapters[row]
        if chapter.revision is None:
            self.scope_status.setText('저장되지 않은 회차는 원본 편집기로 이동하지 않습니다.')
            return
        try:
            session, current_identity = _current_author_state(self.authoring)
            if identity != current_identity or self.folder is None:
                raise AuthorLanguageError('작품 또는 언어 규칙 폴더가 변경됐습니다.')
            require_current_author_language_scope_audit(
                audit, session.store, identity[1], folder=self.folder)
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=chapter.episode)
            if not decision.allowed:
                self.scope_status.setText(decision.message)
                return
            self.scope_status.setText(
                f'{chapter.episode}화 기존 편집기로 이동했습니다. '
                '원고 수정·QC·참고작 검사·출판은 별도 작가 작업입니다.')
        except (AuthorLanguageError, BatchScopeBridgeError, ValueError, OSError, LookupError):
            self._clear_scope()
            self.scope_status.setText('원고·작가 규칙이 변경되어 이전 인계를 무효화했습니다.')