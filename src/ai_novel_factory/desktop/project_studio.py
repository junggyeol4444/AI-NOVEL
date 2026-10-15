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
    QFrame,
)

from ai_novel_factory.manuscript_versions import ManuscriptVersionStore


class ProjectStudio(QWidget):
    """Shared project session, visible reader/writer workflow, no mock actions."""

    def __init__(self, workflow, navigate, show_advanced, parent=None):
        super().__init__(parent)
        self.workflow = workflow
        self.navigate = navigate
        self.show_advanced = show_advanced
        self._loaded_episode = None
        self._shown_text = ''
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
            ('작품 제목 *', self.new_title), ('작가/필명', self.new_author),
            ('장르', self.new_genre), ('소재와 주인공', self.new_subject),
            ('최상위 작품 설정', self.new_premise), ('분위기', self.new_mood),
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
        layout.addStretch(1)
        self.pages.addWidget(page)

    def _build_writer(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.editor_heading = QLabel('집필실 · 작품과 회차를 선택하세요')
        self.editor_heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(self.editor_heading)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName('studioWriterSplitter')
        # Episode list is directly backed by the selected project's SQLite.
        episodes_side = QWidget()
        episodes_layout = QVBoxLayout(episodes_side)
        episodes_layout.addWidget(QLabel('회차'))
        self.episode_list = QListWidget()
        self.episode_list.setObjectName('studioEpisodeList')
        self.episode_list.currentRowChanged.connect(self._select_episode)
        episodes_layout.addWidget(self.episode_list)
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
        center = QVBoxLayout(manuscript_side)
        self.editor_status = QLabel('저장된 초고만 보여줍니다. 자동 품질 검사는 통과로 표시하지 않습니다.')
        self.editor_status.setWordWrap(True)
        center.addWidget(self.editor_status)
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
        splitter.addWidget(manuscript_side)

        context_side = QWidget()
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
        splitter.setSizes([175, 710, 280])
        layout.addWidget(splitter, 1)
        self.pages.addWidget(page)

    def _show(self, index):
        if index != 2 and not self.confirm_discard():
            return
        self.pages.setCurrentIndex(index)
        self.refresh()

    def _advanced(self):
        self.show_advanced()  # MainWindow intercepts the tab change if the draft is unsaved.

    def confirm_discard(self):
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
        self.editor.setPlainText(self._shown_text)
        return True

    def _mark_dirty(self):
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
        if not self.confirm_discard():
            return
        try:
            self.workflow._set('db', str(path))
            self.workflow._open()
            self.workflow._sync()
            self._remember(path)
            self._loaded_episode = None
            self.refresh()
            self.pages.setCurrentIndex(0)
        except OSError:
            self._show_error('로컬 파일을 열거나 저장하지 못했습니다.')
        except ValueError as exc:
            self._show_error(str(exc))

    def _create_project(self):
        if not self.confirm_discard():
            return
        title = self.new_title.text().strip()
        if not title:
            self.create_status.setText('작품 제목을 입력하세요.')
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
        if not session.project_id or not self.confirm_discard():
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
        if not session.project_id or not self.confirm_discard():
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
        try:
            session.create_episode(number.value(), plot.toPlainText())
            self.workflow._sync()
            self._loaded_episode = None
            self.refresh()
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))

    def _select_episode(self, row):
        if row < 0:
            return
        number = self.episode_list.item(row).data(Qt.ItemDataRole.UserRole)
        session = self.workflow.session
        if not session.project_id or number == self._loaded_episode:
            return
        if not self.confirm_discard():
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
            self._show_error(str(exc))

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
            self.canon.setPlainText('')
            self.quality.setText('검수 상태: NOT_RUN')
            self.editor.setEnabled(False)
            self.first_episode.setEnabled(False)
            self.editor.setPlainText('')
            self._shown_text = ''
            self._loaded_episode = None
            return
        db, pid = session.required()
        title = db.get_project(pid).title
        episodes = db.list_episodes(pid)
        completed = sum(bool(ep.final_text.strip()) for ep in episodes)
        target = db.get_rule(pid, 'target_episodes').value or '?'
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
        self.editor.setEnabled(selected_row >= 0)
        self.first_episode.setEnabled(len(episodes) == 0)
        if selected_row < 0:
            self._loaded_episode = None
            self._shown_text = ''
            self.editor.setPlainText('')
            self.canon.setPlainText(db.get_rule(pid, 'premise').value)
            self.quality.setText('검수 상태: NOT_RUN')
            return
        ep = session.episode()
        if self._loaded_episode != ep.episode or self.editor.toPlainText() == self._shown_text:
            self._shown_text = session.pending_draft if session.pending_draft is not None else ep.draft
            self.editor.setPlainText(self._shown_text)
        self._loaded_episode = ep.episode
        bible = db.get_rule(pid, 'premise').value
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

    def _show_error(self, message):
        # Never show user file paths that OSError may include in the message.
        safe = '로컬 파일 접근 중 오류가 발생했습니다.' if not isinstance(message, str) else message[:200]
        self.editor_status.setText(safe)
        QMessageBox.warning(self, '작업을 완료하지 못했습니다', safe)
