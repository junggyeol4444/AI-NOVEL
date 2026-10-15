"""User-first local novel home, creation flow and manuscript workspace.

The classic authoring form remains accessible for features not yet integrated.
All project and manuscript writes are explicit. No remote calls at startup.
"""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
from uuid import uuid4

from PySide6.QtCore import Qt, QSettings, QStandardPaths
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QFormLayout, QSpinBox, QStackedWidget,
    QListWidget, QFileDialog, QMessageBox, QSplitter, QDialog, QDialogButtonBox,
    QFrame, QScrollArea,
)

from ai_novel_factory.manuscript_versions import ManuscriptVersionStore
from ai_novel_factory.desktop.draft_backup import write_draft_copy, DraftBackupError


class ProjectStudio(QWidget):
    """Shared project session, visible reader/writer workflow, no mock actions."""

    def __init__(self, workflow, navigate, show_advanced, parent=None):
        super().__init__(parent)
        self.workflow = workflow
        self.navigate = navigate
        self.show_advanced = show_advanced
        self._loaded_episode = None
        self._loaded_revision = None
        self._shown_text = ''
        self._episode_char_target = None
        self._context_manual = False
        self._focus_mode = False
        self._recent_settings = QSettings('AI Novel Factory', 'ProjectStudio')
        self.setObjectName('projectStudio')
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(15)
        self.heading = QLabel('나만의 이야기를 시작하세요')
        self.heading.setObjectName('studioHeading')
        self.heading.setStyleSheet('font-size: 25px; font-weight: 700;')
        root.addWidget(self.heading)
        self.summary = QLabel('작품을 선택하거나 새로 만드세요. 저장은 내 컴퓨터에서만 이루어집니다.')
        self.summary.setObjectName('studioSummary')
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        bar = QHBoxLayout()
        for title, action, name in (
            ('작품 홈', lambda: self._show(0), 'studioHomeButton'),
            ('새 작품 만들기', lambda: self._show(1), 'studioNewButton'),
            ('원고 집필실', lambda: self._show(2), 'studioWritingButton'),
            ('세부 작업 도구', self._advanced, 'studioAdvancedButton'),
        ):
            button = QPushButton(title)
            button.setObjectName(name)
            button.clicked.connect(action)
            bar.addWidget(button)
        bar.addStretch(1)
        root.addLayout(bar)

        self.pages = QStackedWidget()
        self.pages.setObjectName('studioPages')
        root.addWidget(self.pages, 1)
        self._build_home()
        self._build_create()
        self._build_writer()
        self.refresh()

    def _build_home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel('작품 현황')
        label.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(label)
        self.progress = QLabel('열려 있는 작품이 없습니다.')
        self.progress.setObjectName('studioProgress')
        self.progress.setWordWrap(True)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        for caption, fn in (
            ('새 작품 만들기', lambda: self._show(1)),
            ('기존 작품 파일 열기', self._open_file),
            ('선택 작품 집필하기', lambda: self._show(2)),
        ):
            btn = QPushButton(caption)
            btn.clicked.connect(fn)
            actions.addWidget(btn)
        layout.addLayout(actions)
        layout.addWidget(QLabel('최근 열어 본 작품 — 선택 후 열기'))
        self.recents = QListWidget()
        self.recents.setObjectName('studioRecentProjects')
        layout.addWidget(self.recents, 1)
        reopen = QPushButton('선택한 작품 열기')
        reopen.setObjectName('studioOpenRecentButton')
        reopen.clicked.connect(self._open_recent)
        self.recents.itemDoubleClicked.connect(lambda _item: self._open_recent())
        layout.addWidget(reopen)
        self.pages.addWidget(page)

    def _build_create(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel('1 · 작품의 핵심만 입력하세요')
        heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            '내 컴퓨터의 전용 작품 폴더에 새 파일을 만듭니다. 기존 DB나 설정을 덮어쓰지 않습니다.'))
        form = QFormLayout()
        self.new_title = QLineEdit()
        self.new_title.setObjectName('studioNewTitle')
        self.new_title.setPlaceholderText('작품 제목')
        self.new_author = QLineEdit()
        self.new_author.setObjectName('studioNewAuthor')
        self.new_author.setPlaceholderText('필명 (선택)')
        self.new_genre = QLineEdit()
        self.new_genre.setObjectName('studioNewGenre')
        self.new_subject = QPlainTextEdit()
        self.new_subject.setMaximumHeight(88)
        self.new_subject.setPlaceholderText('이야기의 소재, 주인공과 목표')
        self.new_premise = QPlainTextEdit()
        self.new_premise.setMaximumHeight(100)
        self.new_premise.setPlaceholderText('절대 바뀌면 안 되는 세계관/인물 규칙')
        self.new_mood = QLineEdit()
        self.new_target = QSpinBox()
        self.new_target.setRange(1, 1000)
        self.new_target.setValue(250)
        self.new_characters = QSpinBox()
        self.new_characters.setRange(1, 500000)
        self.new_characters.setValue(5000)
        for text, field in (
            ('작품 제목 *', self.new_title), ('작가/필명 (선택)', self.new_author),
            ('장르', self.new_genre), ('소재와 주인공', self.new_subject),
            ('최상위 작품 설정 *', self.new_premise), ('분위기', self.new_mood),
            ('목표 회차', self.new_target), ('회차당 목표 글자 수', self.new_characters),
        ):
            field.setAccessibleName(text)
            form.addRow(text, field)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        save = QPushButton('로컬 작품 생성')
        save.setObjectName('studioCreateProjectButton')
        save.clicked.connect(self._create_project)
        references = QPushButton('참고소설 등록·분석 도구 열기')
        references.setObjectName('studioReferencesButton')
        references.clicked.connect(lambda: self.navigate('references'))
        buttons.addWidget(save)
        buttons.addWidget(references)
        layout.addLayout(buttons)
        self.create_status = QLabel('참고소설 분석과 전체 자동 기획은 아직 완성되지 않았습니다.')
        self.create_status.setWordWrap(True)
        layout.addWidget(self.create_status)
        # Long new-novel setup must stay operable on 820x560 and smaller
        # Windows display scaling; the creation action cannot be clipped.
        self.create_scroll = QScrollArea(self)
        self.create_scroll.setObjectName('studioCreateScroll')
        self.create_scroll.setWidgetResizable(True)
        self.create_scroll.setWidget(page)
        self.pages.addWidget(self.create_scroll)

    def _build_writer(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.editor_heading = QLabel('집필실 · 작품과 회차를 선택하세요')
        self.editor_heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        heading_line = QHBoxLayout()
        heading_line.addWidget(self.editor_heading, 1)
        self.focus_toggle = QPushButton('집중 집필 모드')
        self.focus_toggle.setObjectName('studioFocusModeButton')
        self.focus_toggle.setAccessibleName('집중 집필 모드 켜기·끄기')
        self.focus_toggle.setCheckable(True)
        self.focus_toggle.clicked.connect(self._toggle_focus_mode)
        heading_line.addWidget(self.focus_toggle)
        self.context_toggle = QPushButton('설정·검수 펼치기')
        self.context_toggle.setObjectName('studioContextToggle')
        self.context_toggle.setAccessibleName('설정·검수 패널 토글')
        self.context_toggle.setCheckable(True)
        self.context_toggle.clicked.connect(self._user_toggle_context)
        heading_line.addWidget(self.context_toggle)
        layout.addLayout(heading_line)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName('studioWriterSplitter')
        # Episode list is directly backed by the selected project's SQLite.
        episodes_side = QWidget()
        self.episodes_side = episodes_side
        episodes_side.setMinimumWidth(115)
        episodes_side.setMaximumWidth(180)
        episodes_layout = QVBoxLayout(episodes_side)
        episodes_layout.addWidget(QLabel('회차'))
        self.episode_search = QLineEdit()
        self.episode_search.setObjectName('studioEpisodeSearch')
        self.episode_search.setAccessibleName('회차 검색')
        self.episode_search.setPlaceholderText('번호·상태 검색')
        episodes_layout.addWidget(self.episode_search)
        self.episode_list = QListWidget()
        self.episode_list.setObjectName('studioEpisodeList')
        self.episode_list.currentRowChanged.connect(self._select_episode)
        episodes_layout.addWidget(self.episode_list)
        self.episode_search.textChanged.connect(self._filter_episodes)
        self.episode_matches = QLabel('회차를 선택하세요.')
        self.episode_matches.setObjectName('studioEpisodeMatches')
        self.episode_matches.setWordWrap(True)
        episodes_layout.addWidget(self.episode_matches)
        movement = QHBoxLayout()
        previous_episode = QPushButton('이전')
        previous_episode.setObjectName('studioPreviousEpisode')
        previous_episode.setAccessibleName('이전 회차')
        previous_episode.clicked.connect(lambda: self._jump_episode(-1))
        next_episode = QPushButton('다음')
        next_episode.setObjectName('studioNextEpisode')
        next_episode.setAccessibleName('다음 회차')
        next_episode.clicked.connect(lambda: self._jump_episode(1))
        movement.addWidget(previous_episode)
        movement.addWidget(next_episode)
        episodes_layout.addLayout(movement)
        self.first_episode = QPushButton('첫 회차 바로 시작')
        self.first_episode.setObjectName('studioFirstEpisodeButton')
        self.first_episode.setAccessibleName('첫 회차 바로 시작')
        self.first_episode.clicked.connect(self._start_first_episode)
        episodes_layout.addWidget(self.first_episode)
        add = QPushButton('새 회차 기획')
        add.setObjectName('studioAddEpisode')
        add.clicked.connect(self._create_episode)
        episodes_layout.addWidget(add)
        splitter.addWidget(episodes_side)

        manuscript_side = QWidget()
        manuscript_side.setMinimumWidth(235)
        center = QVBoxLayout(manuscript_side)
        self.editor_status = QLabel('저장된 초고만 보여줍니다. 자동 품질 검사는 통과로 표시하지 않습니다.')
        self.editor_status.setWordWrap(True)
        center.addWidget(self.editor_status)
        self.manuscript_stats = QLabel('원고 0글자 · 저장 여부 확인')
        self.manuscript_stats.setObjectName('studioManuscriptStats')
        self.manuscript_stats.setAccessibleName('원고 글자 수와 저장 상태')
        center.addWidget(self.manuscript_stats)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName('studioManuscriptEditor')
        self.editor.setAccessibleName('회차 원고 편집기')
        self.editor.setPlaceholderText('새 회차를 선택하고 이곳에 원고를 입력하거나 기존 초고를 수정하세요.')
        self.editor.setMinimumHeight(330)
        self.editor.textChanged.connect(self._mark_dirty)
        self.save_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self.editor)
        self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_shortcut.activated.connect(self._save_manuscript)
        center.addWidget(self.editor, 1)

        # A writer can search lengthy chapters without switching away from
        # their draft. Replace modifies only the live editor; SQLite writes
        # remain exclusively behind the explicit Save Manuscript button.
        find_row = QGridLayout()
        self.manuscript_find = QLineEdit()
        self.manuscript_find.setObjectName('studioFindManuscript')
        self.manuscript_find.setAccessibleName('원고 본문 찾기')
        self.manuscript_find.setPlaceholderText('본문에서 찾기')
        self.manuscript_find.returnPressed.connect(self._find_next)
        find_row.addWidget(self.manuscript_find, 0, 0)
        find_next = QPushButton('다음 찾기')
        find_next.setObjectName('studioFindNext')
        find_next.clicked.connect(self._find_next)
        find_row.addWidget(find_next, 0, 1)
        self.manuscript_replace = QLineEdit()
        self.manuscript_replace.setObjectName('studioReplaceManuscript')
        self.manuscript_replace.setAccessibleName('원고 바꿀 글')
        self.manuscript_replace.setPlaceholderText('바꿀 글')
        find_row.addWidget(self.manuscript_replace, 1, 0)
        replace_one = QPushButton('선택 항목 바꾸기')
        replace_one.setObjectName('studioReplaceOne')
        replace_one.clicked.connect(self._replace_one)
        find_row.addWidget(replace_one, 1, 1)
        find_row.setColumnStretch(0, 3)
        find_row.setColumnStretch(1, 1)
        center.addLayout(find_row)
        self.find_feedback = QLabel('')
        self.find_feedback.setObjectName('studioFindFeedback')
        self.find_feedback.setWordWrap(True)
        center.addWidget(self.find_feedback)
        actions = QHBoxLayout()
        save = QPushButton('원고 버전 저장')
        save.setObjectName('studioSaveManuscript')
        save.setAccessibleName('원고 버전 저장')
        save.clicked.connect(self._save_manuscript)
        tools = QPushButton('로컬 AI 생성·최종본 검수')
        tools.setObjectName('studioAuthoringTools')
        tools.clicked.connect(self._advanced)
        actions.addWidget(save)
        actions.addWidget(tools)
        center.addLayout(actions)
        backup = QPushButton('현재 원고를 TXT로 별도 보관')
        backup.setObjectName('studioBackupCurrentDraft')
        backup.setAccessibleName('편집 중인 현재 원고를 TXT로 별도 보관')
        backup.clicked.connect(self._backup_current_draft)
        center.addWidget(backup)
        history_button = QPushButton('이전 원고·버전 이력')
        history_button.setObjectName('studioVersionHistoryButton')
        history_button.setAccessibleName('이전 원고·버전 이력')
        history_button.clicked.connect(self._open_version_history)
        center.addWidget(history_button)
        splitter.addWidget(manuscript_side)

        context_side = QWidget()
        context_side.setMinimumWidth(175)
        context_side.setMaximumWidth(310)
        self.context_side = context_side
        context = QVBoxLayout(context_side)
        context.addWidget(QLabel('작품 설정 · 현재 회차'))
        self.canon = QPlainTextEdit()
        self.canon.setObjectName('studioContextPreview')
        self.canon.setReadOnly(True)
        context.addWidget(self.canon, 1)
        self.quality = QLabel('검수 상태: NOT_RUN')
        self.quality.setWordWrap(True)
        context.addWidget(self.quality)
        for label, key in (('설정·인물 관리', 'bible'), ('회차·장면 플롯', 'episodes'),
                           ('검수/유사성 확인', 'similarity'),
                           ('검토된 원고 내보내기', 'publication')):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, target=key: self.navigate(target))
            context.addWidget(btn)
        splitter.addWidget(context_side)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([160, 780, 250])
        layout.addWidget(splitter, 1)
        self.pages.addWidget(page)

    def _toggle_focus_mode(self, enabled: bool) -> None:
        # Local-only UI preference; no QSettings changes, no manuscript
        # transfer, and no session/SQLite writes. Keep a visible exit button.
        self._focus_mode = enabled
        self.episodes_side.setVisible(not enabled)
        self.context_toggle.setEnabled(not enabled)
        if enabled:
            self.context_side.setVisible(False)
        else:
            self.context_side.setVisible(self.context_toggle.isChecked())
        self.focus_toggle.setText('집중 모드 종료' if enabled else '집중 집필 모드')
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _apply_context_visible(self, visible: bool) -> None:
        self.context_side.setVisible(visible)
        self.context_toggle.blockSignals(True)
        self.context_toggle.setChecked(visible)
        self.context_toggle.blockSignals(False)
        self.context_toggle.setText(
            '설정·검수 접기' if visible else '설정·검수 펼치기')

    def _user_toggle_context(self, visible: bool) -> None:
        self._context_manual = True
        self._apply_context_visible(visible)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Respect an explicit user toggle, but give smaller screens a
        # manuscript-first layout without permanently hiding canon access.
        if (hasattr(self, 'context_side') and not self._context_manual
                and not self._focus_mode):
            self._apply_context_visible(event.size().width() >= 900)

    def _show(self, index):
        if index == 2 and not self.workflow.session.project_id:
            index = 1  # No novel yet: show the creation wizard instead of an inert editor.
        if index != 2 and not self.confirm_discard():
            return
        self.pages.setCurrentIndex(index)
        self.refresh()

    def _advanced(self):
        self.show_advanced()  # MainWindow intercepts the tab change if the draft is unsaved.

    def confirm_discard(self, *, apply=True):
        # Unsaved text still matters when the user temporarily leaves the
        # writing page. Never interpret hiding the editor as saving it.
        if self.editor.toPlainText() == self._shown_text:
            return True
        decision = QMessageBox.question(
            self, '저장하지 않은 원고', '편집 중인 원고가 있습니다. 저장하지 않고 이동하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if decision != QMessageBox.StandardButton.Yes:
            return False
        # A positive discard must really discard the draft; otherwise the
        # stale modified text can survive another project/tab change.
        if apply:
            self.editor.setPlainText(self._shown_text)
        return True

    def _find_next(self) -> None:
        needle = self.manuscript_find.text()
        if not needle:
            self.find_feedback.setText('찾을 글을 먼저 입력하세요.')
            return
        if self.editor.find(needle):
            self.find_feedback.setText('본문에서 일치하는 부분을 선택했습니다.')
            return
        # Wrap once, but never alter the manuscript when there is no match.
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
        if self.editor.find(needle):
            self.find_feedback.setText('본문 처음부터 다시 찾았습니다.')
        else:
            self.find_feedback.setText('일치하는 글이 없습니다.')

    def _replace_one(self) -> None:
        needle = self.manuscript_find.text()
        cursor = self.editor.textCursor()
        if not self.editor.isEnabled() or not needle:
            self.find_feedback.setText('편집할 회차와 찾을 글을 선택하세요.')
            return
        if cursor.selectedText() != needle:
            self.find_feedback.setText('먼저 다음 찾기로 바꿀 위치를 선택하세요.')
            return
        # Replace exactly one selected occurrence. No automatic mass replace
        # and no SQLite write: Undo and explicit versioned Save remain possible.
        cursor.insertText(self.manuscript_replace.text())
        self.find_feedback.setText('선택한 1곳만 바꿨습니다. 저장하려면 원고 버전 저장을 누르세요.')

    def _update_manuscript_stats(self):
        text = self.editor.toPlainText()
        count = sum(not letter.isspace() for letter in text)
        words = len(text.split())
        target = self._episode_char_target
        progress = (f' · 목표 {target:,}글자 대비 {count * 100 // target}%'
                    if isinstance(target, int) and target > 0 else '')
        dirty = ' · 미저장' if text != self._shown_text else ' · 저장본과 일치'
        self.manuscript_stats.setText(
            f'공백 제외 {count:,}글자 · {words:,}어절' + progress + dirty)

    def _mark_dirty(self):
        self._update_manuscript_stats()
        if self.pages.currentIndex() == 2:
            self.editor_status.setText(
                '수정 사항이 저장되지 않았습니다. 이동 전 원고 버전을 저장하세요.'
                if self.editor.toPlainText() != self._shown_text else '저장된 원고')

    def _remember(self, filename):
        raw = self._recent_settings.value('recent_paths', [])
        previous = [raw] if isinstance(raw, str) else list(raw or [])
        paths = [str(filename)] + [v for v in previous if v != str(filename)]
        self._recent_settings.setValue('recent_paths', paths[:10])
        session = self.workflow.session
        if session.store and session.project_id:
            digest = sha256(str(filename).encode('utf-8')).hexdigest()
            self._recent_settings.setValue('recent_title_' + digest,
                                            session.store.get_project(session.project_id).title)

    def _recent_paths(self):
        raw = self._recent_settings.value('recent_paths', [])
        values = [raw] if isinstance(raw, str) else list(raw or [])
        for text in values[:10]:
            if not isinstance(text, str):
                continue
            path = Path(text)
            if path.is_absolute() and path.suffix.lower() in ('.db', '.sqlite'):
                if path.is_file() and not path.is_symlink():
                    yield path

    def _open_recent(self):
        item = self.recents.currentItem()
        if item is None:
            self._show_error('열 작품을 먼저 선택하세요.')
            return
        self._open_path(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '기존 작품 열기', '', '로컬 작품 (*.db *.sqlite)')
        if path:
            self._open_path(Path(path))

    def _open_path(self, path):
        if not self.confirm_discard(apply=False):
            return
        previous_db = self.workflow._text('db')
        try:
            self.workflow._set('db', str(path))
            self.workflow._open()
            self.workflow._sync()
            self._remember(path)
            self._loaded_episode = None
            self.refresh()
            self.pages.setCurrentIndex(0)
        except (OSError, ValueError) as exc:
            # A failed import/open must not leave the advanced form pointing
            # at a different DB from the manuscript still open in session.
            # Keep live unsaved text; never call refresh() on a failed open.
            active = self.workflow.session.path
            self.workflow._set('db', str(active) if active is not None else previous_db)
            if isinstance(exc, OSError):
                self._show_error('로컬 파일을 열거나 저장하지 못했습니다.')
            else:
                self._show_error(str(exc))

    def _create_project(self):
        if not self.confirm_discard(apply=False):
            return
        title = self.new_title.text().strip()
        if not title:
            self.create_status.setText('작품 제목을 입력하세요.')
            return
        if not self.new_premise.toPlainText().strip():
            self.create_status.setText('최상위 작품 설정을 입력하세요.')
            self.new_premise.setFocus()
            return
        try:
            location = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation)
            if not location:
                raise ValueError('로컬 작품 저장 폴더를 찾지 못했습니다.')
            base = Path(location) / 'novels'
            if base.is_symlink():
                raise ValueError('작품 저장 폴더가 안전하지 않습니다.')
            base.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = base / ('novel_' + uuid4().hex + '.sqlite')
            rules = {
                'genre': self.new_genre.text().strip(),
                'subject': self.new_subject.toPlainText().strip(),
                'target_episodes': str(self.new_target.value()),
                'characters_per_episode': str(self.new_characters.value()),
                'mood': self.new_mood.text().strip(),
            }
            self.workflow.session.create_project(
                str(path), title, self.new_author.text().strip(),
                self.new_premise.toPlainText(), extra_rules=rules)
            for key, value in (
                ('db', str(path)), ('title', title),
                ('author', self.new_author.text().strip()),
                ('premise', self.new_premise.toPlainText()),
                ('genre', rules['genre']), ('subject', rules['subject']),
                ('target_episodes', rules['target_episodes']),
                ('characters_per_episode', rules['characters_per_episode']),
                ('mood', rules['mood']),
            ):
                self.workflow._set(key, value)
            self.workflow._sync()
            self._remember(path)
            self._loaded_episode = None
            self.create_status.setText('로컬 작품을 생성했습니다. 다음은 회차와 장면을 기획하세요.')
            self.pages.setCurrentIndex(2)
            self.refresh()
        except OSError:
            self.create_status.setText('로컬 작품 폴더에 저장하지 못했습니다.')
        except ValueError as exc:
            self.create_status.setText(str(exc)[:200])

    def _start_first_episode(self):
        # One deliberate click makes a blank first chapter: no model execution,
        # no publishing, and never overwrites an existing chapter.
        session = self.workflow.session
        if not session.project_id or not self.confirm_discard(apply=False):
            if not session.project_id:
                self._show_error('작품을 먼저 열어 주세요.')
            return
        try:
            if session.store.list_episodes(session.project_id):
                self._show_error('이미 회차가 있습니다. 목록에서 회차를 선택하세요.')
                return
            session.create_episode(1, '')
            self.workflow._sync()
            self._loaded_episode = None
            self.refresh()
            self.pages.setCurrentIndex(2)
            self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        except OSError:
            self._show_error('로컬 회차를 저장하지 못했습니다.')
        except ValueError as exc:
            self._show_error(str(exc))

    def _create_episode(self):
        session = self.workflow.session
        if not session.project_id:
            self._show_error('작품을 먼저 열어 주세요.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('새 회차 기획')
        layout = QVBoxLayout(dialog)
        number = QSpinBox()
        number.setRange(1, 1000000)
        existing = session.store.list_episodes(session.project_id)
        number.setValue(max((ep.episode for ep in existing), default=0) + 1)
        plot = QPlainTextEdit()
        plot.setPlaceholderText('이번 화의 목표, 사건, 감정 변화, 장면 요약')
        layout.addWidget(QLabel('회차 번호'))
        layout.addWidget(number)
        layout.addWidget(QLabel('회차 플롯'))
        layout.addWidget(plot)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        # Cancelled dialogs cannot discard draft changes or prompt to do so.
        # Even an accepted request keeps the editor intact if DB creation fails.
        if not self.confirm_discard(apply=False):
            return
        try:
            session.create_episode(number.value(), plot.toPlainText())
            self.workflow._sync()
            self._loaded_episode = None
            self.refresh()
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))

    def _filter_episodes(self, query: str) -> None:
        # Search UI labels only; never inspect the writer's unpublished draft.
        needle = query.strip().casefold()
        visible = 0
        for i in range(self.episode_list.count()):
            item = self.episode_list.item(i)
            shown = needle in item.text().casefold()
            item.setHidden(not shown)
            visible += int(shown)
        total = self.episode_list.count()
        self.episode_matches.setText(
            f'검색된 회차 {visible} / 전체 {total}' if needle
            else f'전체 {total}회차')

    def _jump_episode(self, direction: int) -> None:
        if direction not in (-1, 1):
            return
        indices = [i for i in range(self.episode_list.count())
                   if not self.episode_list.item(i).isHidden()]
        if not indices:
            return
        current = next((
            i for i in range(self.episode_list.count())
            if self.episode_list.item(i).data(Qt.ItemDataRole.UserRole)
               == self.workflow.session.episode_number), -1)
        if current not in indices:
            target = indices[0] if direction > 0 else indices[-1]
        else:
            position = indices.index(current) + direction
            if not 0 <= position < len(indices):
                return
            target = indices[position]
        # Filtering can leave QListWidget's currentRow at a hidden or stale
        # selection. Use the persisted session episode, and explicitly invoke
        # the existing confirmation + refresh path even if Qt suppressed a
        # currentRowChanged signal for the target index.
        self._select_episode(target)

    def _select_episode(self, row):
        if row < 0:
            return
        number = self.episode_list.item(row).data(Qt.ItemDataRole.UserRole)
        session = self.workflow.session
        if not session.project_id or number == self._loaded_episode:
            return
        if not self.confirm_discard(apply=False):
            self.episode_list.blockSignals(True)
            for i in range(self.episode_list.count()):
                if self.episode_list.item(i).data(Qt.ItemDataRole.UserRole) == self._loaded_episode:
                    self.episode_list.setCurrentRow(i)
                    break
            self.episode_list.blockSignals(False)
            return
        try:
            session.select_episode(number)
            self.workflow._sync()
            self._loaded_episode = None
            self.refresh()
        except (OSError, ValueError) as exc:
            # A failed chapter load must not strand selection on a different
            # chapter while the editor still shows the prior manuscript.
            self.episode_list.blockSignals(True)
            for i in range(self.episode_list.count()):
                if (self.episode_list.item(i).data(Qt.ItemDataRole.UserRole)
                        == session.episode_number):
                    self.episode_list.setCurrentRow(i)
                    break
            self.episode_list.blockSignals(False)
            self._show_error(str(exc))

    def _open_version_history(self):
        session = self.workflow.session
        if not session.project_id or session.episode_number is None:
            self._show_error('먼저 원고 회차를 선택하세요.')
            return
        try:
            with ManuscriptVersionStore(session.path) as store:
                entries = store.list_versions(session.project_id, session.episode_number)
        except (ValueError, OSError):
            self._show_error('원고 버전 이력을 읽을 수 없습니다.')
            return
        if not entries:
            self.editor_status.setText('아직 저장한 원고 버전이 없습니다.')
            return
        from PySide6.QtWidgets import QListWidgetItem
        dialog = QDialog(self)
        dialog.setObjectName('studioVersionHistoryDialog')
        dialog.setWindowTitle(f'{session.episode_number}화 · 로컬 원고 버전')
        dialog.resize(690, 510)
        box = QVBoxLayout(dialog)
        note = QLabel('과거 원고는 읽기 전용입니다. 복원은 원본 이력을 지우지 않고 새 수정본으로 저장합니다.')
        note.setWordWrap(True)
        box.addWidget(note)
        versions_list = QListWidget(dialog)
        versions_list.setObjectName('studioVersionHistoryEntries')
        for item in entries:
            row = QListWidgetItem(f'{item.ordinal}번째 · {item.kind} · {item.created_at[:16]}')
            row.setData(Qt.ItemDataRole.UserRole, item.version_id)
            versions_list.addItem(row)
        box.addWidget(versions_list, 1)
        preview = QPlainTextEdit(dialog)
        preview.setObjectName('studioVersionHistoryPreview')
        preview.setReadOnly(True)
        preview.setPlaceholderText('확인할 이전 원고를 선택하세요.')
        box.addWidget(preview, 2)

        def selected(row):
            preview.setPlainText(entries[row].draft or entries[row].final_text
                                 if 0 <= row < len(entries) else '')

        versions_list.currentRowChanged.connect(selected)
        actions = QHBoxLayout()
        restore = QPushButton('선택 버전을 새 수정본으로 복원')
        restore.setObjectName('studioRestoreVersionButton')
        def restore_selected():
            row = versions_list.currentRow()
            if 0 <= row < len(entries) and self._restore_version(entries[row].version_id):
                dialog.accept()
        restore.clicked.connect(restore_selected)
        actions.addWidget(restore)
        close = QPushButton('닫기')
        close.clicked.connect(dialog.reject)
        actions.addWidget(close)
        box.addLayout(actions)
        versions_list.setCurrentRow(len(entries) - 1)
        dialog.exec()

    def _restore_version(self, version_id: str) -> bool:
        # This user-visible helper is intentionally never called without a
        # positive confirmation. A previous FINAL is restored as a draft,
        # never as automatically reviewed/publishable material.
        session = self.workflow.session
        if not session.project_id or session.episode_number is None:
            self._show_error('복원할 회차를 선택하세요.')
            return False
        # Do NOT discard the live editor before an atomic DB restore succeeds.
        # Even a confirmed restore may fail (another window writes meanwhile).
        unsaved = self.editor.toPlainText() != self._shown_text
        try:
            with ManuscriptVersionStore(session.path) as store:
                ep = store.get_episode(session.project_id, session.episode_number)
                if (self._loaded_episode != ep.episode or
                        self._loaded_revision != ep.revision):
                    self._show_error('다른 작업에서 회차가 변경되었습니다. 기존 편집 내용을 복사한 후 다시 열어 주세요.')
                    return False
                past = store.get_version(session.project_id, ep.episode, version_id)
                if (past.draft or past.final_text) == ep.draft and not ep.final_text:
                    self.editor_status.setText('현재 초고와 동일한 내용입니다. 복원이 필요하지 않습니다.')
                    return False
                answer = QMessageBox.question(
                    self, '과거 원고 복원 확인',
                    f'{ep.episode}화의 {past.ordinal}번째 버전을 새 수정본으로 저장합니다. '
                    '현행 최종본 승인 상태가 있다면 해제됩니다. 원본 버전 이력은 보존합니다. '
                    + ('복원에 성공하면 현재 저장하지 않은 편집 내용은 사라집니다. '
                       if unsaved else '')
                    + '계속하시겠습니까?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return False
                store.restore_as_revision(
                    session.project_id, ep.episode, version_id,
                    expected_revision=ep.revision, note='사용자 승인 이전 버전 복원')
            session.pending_draft = None
            self.workflow._sync()
            self._loaded_episode = None
            self.refresh()
            self.editor_status.setText('이전 원고를 새 초고 버전으로 복원했습니다. 검수는 별도입니다.')
            return True
        except (ValueError, OSError):
            self._show_error('복원할 수 없습니다. 원고 버전 또는 동시 수정 상태를 확인하세요.')
            return False

    def _backup_current_draft(self) -> None:
        # This manual safety copy is available even when another program
        # changed the SQLite revision. Copy exactly what the user can see.
        prose = self.editor.toPlainText()
        if not prose.strip():
            self._show_error('별도로 보관할 원고가 없습니다.')
            return
        number = self.workflow.session.episode_number or '임시'
        filename, _ = QFileDialog.getSaveFileName(
            self, '현재 원고 별도 보관 (덮어쓰기 금지)',
            f'원고_{number}화_임시보관.txt', '텍스트 파일 (*.txt)')
        if not filename:
            return
        try:
            write_draft_copy(filename, prose)
        except (DraftBackupError, OSError):
            self._show_error('원고 보관에 실패했습니다. 기존 파일은 변경하지 않습니다.')
            return
        # Not a manuscript version, not a database write or publishing.
        self.editor_status.setText(
            '현재 보이는 원고를 TXT 파일에 별도 보관했습니다. SQLite 버전 저장은 별도입니다.')
        self._update_manuscript_stats()

    def _save_manuscript(self):
        session = self.workflow.session
        if not session.project_id or session.episode_number is None:
            self._show_error('원고를 저장할 회차를 선택하세요.')
            return
        text = self.editor.toPlainText()
        if not text.strip():
            self._show_error('빈 원고는 저장하지 않습니다.')
            return
        try:
            ep = session.episode()
            # Optimistic concurrency must compare the revision loaded into
            # the editor, not merely obtain a fresh revision at save time.
            if self._loaded_episode != ep.episode or self._loaded_revision != ep.revision:
                self._show_error('이 회차가 다른 작업에서 수정됐습니다. 변경 내용을 복사하여 보관하고 회차를 다시 열어 주세요.')
                return
            if text == ep.draft:
                self.editor_status.setText('원고가 이미 저장되어 있습니다.')
                self._shown_text = text
                return
            if ep.final_text and QMessageBox.warning(
                self, '최종본 보호', '기존 최종 원고는 버전 이력에 보존되지만, '
                '새 초고를 저장하면 현재 최종본 승인 상태가 해제됩니다. 계속할까요?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            with ManuscriptVersionStore(session.path) as versions:
                history = versions.list_versions(session.project_id, ep.episode)
                if not history and (ep.draft or ep.final_text):
                    versions.capture_current(
                        session.project_id, ep.episode, expected_revision=ep.revision,
                        note='GUI 편집 전 기존 원고 보존')
                versions.save_version(
                    session.project_id, ep.episode, text, kind='REVISION',
                    expected_revision=ep.revision, note='사용자 집필실 수동 저장')
            session.pending_draft = None
            self._shown_text = text
            self.workflow._sync()
            self.refresh()
            self.editor_status.setText('로컬 SQLite에 새 원고 버전을 저장했습니다. 자동 검수는 별도입니다.')
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))

    def refresh(self):
        session = self.workflow.session
        self.recents.clear()
        for path in self._recent_paths():
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            digest = sha256(str(path).encode('utf-8')).hexdigest()
            label = self._recent_settings.value('recent_title_' + digest, path.stem)
            item.setText(label if isinstance(label, str) and label.strip() else path.stem)
            self.recents.addItem(item)
        if not session.project_id:
            self.heading.setText('나만의 이야기를 시작하세요')
            self.summary.setText('새 작품을 만들거나 기존 SQLite 작품을 열어 주세요.')
            self.progress.setText('선택한 작품이 없습니다.')
            self.editor_heading.setText('집필실 · 먼저 작품을 선택하세요')
            self.episode_list.clear()
            self._filter_episodes(self.episode_search.text())
            self.canon.setPlainText('')
            self.quality.setText('검수 상태: NOT_RUN')
            self.editor.setEnabled(False)
            self.first_episode.setEnabled(False)
            self.editor.setPlainText('')
            self._shown_text = ''
            self._loaded_episode = None
            self._loaded_revision = None
            self._episode_char_target = None
            self._update_manuscript_stats()
            return
        db, pid = session.required()
        title = db.get_project(pid).title
        episodes = db.list_episodes(pid)
        completed = sum(bool(ep.final_text.strip()) for ep in episodes)
        # Older locally created projects have no target_episodes rule.
        # Display missing optional metadata instead of breaking project open.
        saved_rules = {rule.key: rule.value for rule in db.list_rules(pid)}
        char_target = saved_rules.get('characters_per_episode', '')
        self._episode_char_target = (
            int(char_target) if str(char_target).isdecimal()
            and 1 <= int(char_target) <= 500000 else None)
        target = saved_rules.get('target_episodes') or '?'
        self.heading.setText(title)
        self.summary.setText('현재 선택한 작품 · 내 컴퓨터에만 저장됩니다.')
        self.progress.setText(
            f'기획된 회차 {len(episodes)} / 목표 {target} · 사용자 검수 최종본 {completed}회')
        self.editor_heading.setText(f'{title} · 원고 집필실')
        self.episode_list.blockSignals(True)
        self.episode_list.clear()
        selected_row = -1
        for i, ep in enumerate(episodes):
            from PySide6.QtWidgets import QListWidgetItem
            name = f'{ep.episode}화   ' + (
                '최종본' if ep.final_text else '초고 있음' if ep.draft else '기획 중')
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, ep.episode)
            self.episode_list.addItem(item)
            if ep.episode == session.episode_number:
                selected_row = i
        self.episode_list.setCurrentRow(selected_row)
        self.episode_list.blockSignals(False)
        self._filter_episodes(self.episode_search.text())
        self.editor.setEnabled(selected_row >= 0)
        self.first_episode.setEnabled(len(episodes) == 0)
        if selected_row < 0:
            self._loaded_episode = None
            self._loaded_revision = None
            self._shown_text = ''
            self.editor.setPlainText('')
            self.canon.setPlainText(saved_rules.get('premise', ''))
            self.quality.setText('검수 상태: NOT_RUN')
            return
        ep = session.episode()
        if self._loaded_episode != ep.episode or self.editor.toPlainText() == self._shown_text:
            self._shown_text = session.pending_draft if session.pending_draft is not None else ep.draft
            self._loaded_revision = ep.revision
            self.editor.setPlainText(self._shown_text)
        self._loaded_episode = ep.episode
        bible = saved_rules.get('premise', '')
        self.canon.setPlainText('작품 설정\n' + bible + '\n\n회차 플롯\n' + ep.plot)
        records = db.list_checks(pid, ep.episode)
        current = [c for c in records if c.content_revision == ep.revision]
        statuses = {c.category: c.outcome for c in current}
        needed = ('continuity', 'logic', 'character_knowledge', 'timeline',
                  'foreshadowing', 'reference_similarity', 'reader_simulation')
        output = [f'{key}: {statuses.get(key, "NOT_RUN")}' for key in needed]
        self.quality.setText('검수 (현재 원고 버전)\n' + '\n'.join(output))
        if self.editor.toPlainText() == self._shown_text:
            self.editor_status.setText('저장된 초고 / 사용자 직접 검수 필요')
        self._update_manuscript_stats()

    def _show_error(self, message):
        # Never show user file paths that OSError may include in the message.
        safe = '로컬 파일 접근 중 오류가 발생했습니다.' if not isinstance(message, str) else message[:200]
        self.editor_status.setText(safe)
        QMessageBox.warning(self, '작업을 완료하지 못했습니다', safe)
