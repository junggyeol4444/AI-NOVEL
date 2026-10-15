"""Validation branch: project-scoped GUI editors for existing canon stores.

Each action uses the same SQLite file and project_id as the authoring screen.
Nothing is silently generated, published, deleted, or sent to a service.
"""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QComboBox, QSpinBox, QPushButton, QMessageBox,
)

from ai_novel_factory.database.novel_bible import NovelBibleStore
from ai_novel_factory.database.characters import CharacterStore
from ai_novel_factory.database.world_canon import WorldCanonStore
from ai_novel_factory.database.event_timeline import EventTimelineStore
from ai_novel_factory.database.relationships import RelationshipStore
from ai_novel_factory.database.foreshadow import ForeshadowStore

STORES = {
    'bible': NovelBibleStore,
    'characters': CharacterStore,
    'world': WorldCanonStore,
    'timeline': EventTimelineStore,
    'relationships': RelationshipStore,
    'foreshadowing': ForeshadowStore,
}
LABELS = {
    'bible': 'Novel Bible 설정',
    'characters': '등장인물과 비밀',
    'world': '세계관과 조직·지역·능력·아이템',
    'timeline': '사건 시간선',
    'relationships': '인물 관계의 회차별 변화',
    'foreshadowing': '복선과 회수 이력',
}

class CanonWorkspace(QWidget):
    """Explicit CRUD over original validated stores; selected records use revisions."""

    def __init__(self, section: str, context, parent=None):
        super().__init__(parent)
        if section not in STORES:
            raise ValueError('unsupported canon workspace')
        self.section, self.context = section, context
        self.records = ()
        self._loading = False
        self.fields = {}
        root = QVBoxLayout(self)
        root.addWidget(QLabel(LABELS[section]))
        self.status = QLabel('작품 메뉴에서 먼저 기존 작품을 열거나 새 작품을 생성하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        form = QFormLayout()
        root.addLayout(form)
        self.selection = QComboBox()
        self.selection.setObjectName('canonRecord_' + section)
        if section != 'relationships':
            form.addRow('저장된 항목', self.selection)
        else:
            self.selection.hide()

        def line(key, label):
            field = QLineEdit()
            field.setObjectName('canon_' + section + '_' + key)
            self.fields[key] = field
            form.addRow(label, field)
        def longtext(key, label):
            field = QPlainTextEdit()
            field.setMaximumHeight(72)
            field.setObjectName('canon_' + section + '_' + key)
            self.fields[key] = field
            form.addRow(label, field)
        def combo(key, label, choices):
            field = QComboBox()
            field.setObjectName('canon_' + section + '_' + key)
            for name, value in choices:
                field.addItem(name, value)
            self.fields[key] = field
            form.addRow(label, field)

        if section == 'bible':
            line('key', '설정 키 (예: genre, tone, premise)')
            longtext('value', '설정 내용')
        elif section == 'characters':
            line('name', '인물 이름')
            longtext('personality', '성격')
            line('goal', '목표')
            line('speech_style', '말투')
            longtext('secret', '비밀 (로컬 DB에 저장)')
        elif section == 'world':
            combo('category', '분류', [(v, v) for v in
                  ('worldview', 'organization', 'region', 'ability', 'item')])
            line('name', '명칭')
            longtext('description', '설명')
        elif section == 'timeline':
            line('title', '사건')
            line('when', '발생일 (YYYY-MM-DD, 선택)')
        elif section == 'relationships':
            combo('first', '첫 번째 인물', [])
            combo('second', '두 번째 인물', [])
            self.episode = QSpinBox()
            self.episode.setRange(1, 1000000)
            form.addRow('회차', self.episode)
            line('relationship', '관계 상태')
            longtext('notes', '변화 기록')
        elif section == 'foreshadowing':
            line('title', '복선 제목 (새 복선 생성 시)')
            self.episode = QSpinBox()
            self.episode.setRange(1, 1000000)
            form.addRow('회차', self.episode)
            combo('action', '기존 복선의 후속 사건',
                  [(v, v) for v in ('REVISIT', 'RESOLVE', 'ABANDON')])
            longtext('note', '기록')
        self.reset_button = QPushButton('새 항목 입력')
        self.reset_button.setObjectName('canonNew_' + section)
        self.save_button = QPushButton('직접 저장')
        self.save_button.setObjectName('canonSave_' + section)
        root.addWidget(self.reset_button)
        root.addWidget(self.save_button)
        root.addStretch(1)
        self.reset_button.clicked.connect(self._reset)
        self.save_button.clicked.connect(self._save)
        self.selection.currentIndexChanged.connect(self._load_selected)

    def _value(self, key):
        f = self.fields[key]
        if isinstance(f, QPlainTextEdit):
            return f.toPlainText()
        if isinstance(f, QComboBox):
            return f.currentData()
        return f.text()

    def _fill(self, key, value):
        f = self.fields[key]
        if isinstance(f, QPlainTextEdit):
            f.setPlainText(str(value or ''))
        elif isinstance(f, QComboBox):
            index = f.findData(value)
            f.setCurrentIndex(index if index >= 0 else 0)
        else:
            f.setText(str(value or ''))

    def _context(self):
        current = self.context()
        if not current or not current[0] or not current[1]:
            raise ValueError('작품 메뉴에서 먼저 작품을 선택하세요.')
        return current

    def _reset(self):
        self.selection.setCurrentIndex(0)
        for key, field in self.fields.items():
            if isinstance(field, QComboBox):
                if key not in ('first', 'second'):
                    field.setCurrentIndex(0)
            else:
                self._fill(key, '')
        self.status.setText('새 항목 입력 준비. 저장을 누르면 현재 작품에만 반영됩니다.')

    def _load_selected(self, _index=None):
        if self._loading or self.section == 'relationships':
            return
        row = self.selection.currentData()
        if row is None:
            return
        if self.section == 'bible':
            self._fill('key', row.key)
            self._fill('value', row.value)
        elif self.section == 'characters':
            for key in ('name', 'personality', 'goal', 'speech_style', 'secret'):
                self._fill(key, getattr(row, key))
        elif self.section == 'world':
            for key in ('category', 'name', 'description'):
                self._fill(key, getattr(row, key))
        elif self.section == 'timeline':
            if row.anchor_event_id is not None:
                self.status.setText('상대시간 기록은 이 단순 편집 화면에서 변경할 수 없습니다.')
            else:
                self._fill('title', row.title)
                self._fill('when', row.when or '')
        elif self.section == 'foreshadowing':
            self._fill('title', row.title)

    def refresh(self, selected_id=None):
        try:
            path, pid = self._context()
            with STORES[self.section](path) as db:
                db.get_project(pid)
                if self.section == 'bible':
                    records = db.list_rules(pid)
                    label = lambda x: x.key
                    ident = lambda x: x.key
                elif self.section == 'characters':
                    records = db.list_characters(pid)
                    label = lambda x: x.name
                    ident = lambda x: x.character_id
                elif self.section == 'world':
                    records = db.list_entries(pid)
                    label = lambda x: x.category + ': ' + x.name
                    ident = lambda x: x.entry_id
                elif self.section == 'timeline':
                    records = db.list_events(pid)
                    label = lambda x: x.title
                    ident = lambda x: x.event_id
                elif self.section == 'foreshadowing':
                    records = db.list_threads(pid)
                    label = lambda x: x.title
                    ident = lambda x: x.thread_id
                else:
                    records = db.list_characters(pid)
                    first, second = self.fields['first'], self.fields['second']
                    prev1, prev2 = first.currentData(), second.currentData()
                    first.clear()
                    second.clear()
                    for char in records:
                        first.addItem(char.name, char.character_id)
                        second.addItem(char.name, char.character_id)
                    for field, value in ((first, prev1), (second, prev2)):
                        i = field.findData(value)
                        if i >= 0:
                            field.setCurrentIndex(i)
                    self.status.setText('선택한 두 인물의 관계 이력을 현재 회차에 저장합니다.')
                    return
            previous = selected_id if selected_id is not None else (
                self.selection.currentData().key if self.section == 'bible'
                and self.selection.currentData() is not None else None)
            if previous is None and self.selection.currentData() is not None:
                current = self.selection.currentData()
                previous = getattr(current, 'character_id', None) or getattr(
                    current, 'entry_id', None) or getattr(current, 'event_id', None) or getattr(
                    current, 'thread_id', None)
            self._loading = True
            self.selection.clear()
            self.selection.addItem('새 항목', None)
            for record in records:
                self.selection.addItem(label(record), record)
            for i in range(1, self.selection.count()):
                if ident(self.selection.itemData(i)) == previous:
                    self.selection.setCurrentIndex(i)
                    break
            self._loading = False
            if self.selection.currentData() is not None:
                self._load_selected()
            self.status.setText(f'현재 작품: 저장된 항목 {len(records)}개')
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc)[:160])

    def _save(self):
        try:
            path, pid = self._context()
            row = self.selection.currentData()
            selected = None
            with STORES[self.section](path) as db:
                if self.section == 'bible':
                    key, value = self._value('key'), self._value('value')
                    current = next((x for x in db.list_rules(pid) if x.key == key), None)
                    saved = db.save_rule(pid, key, value, expected_revision=(
                        current.revision if current is not None else None))
                    selected = saved.key
                elif self.section == 'characters':
                    kwargs = {x: self._value(x) for x in
                              ('name', 'personality', 'goal', 'speech_style', 'secret')}
                    saved = (db.update_character(pid, row.character_id,
                             expected_revision=row.revision, **kwargs)
                             if row is not None else db.create_character(pid, **kwargs))
                    selected = saved.character_id
                elif self.section == 'world':
                    kwargs = {x: self._value(x) for x in ('category', 'name', 'description')}
                    saved = (db.update_entry(pid, row.entry_id, expected_revision=row.revision,
                                             **kwargs) if row is not None
                             else db.create_entry(pid, **kwargs))
                    selected = saved.entry_id
                elif self.section == 'timeline':
                    if row is not None and row.anchor_event_id:
                        raise ValueError('상대시간 사건은 이 화면에서 수정할 수 없습니다.')
                    kwargs = {'title': self._value('title'),
                              'when': self._value('when').strip() or None}
                    saved = (db.update_event(pid, row.event_id, expected_revision=row.revision,
                                             **kwargs) if row is not None
                             else db.create_event(pid, **kwargs))
                    selected = saved.event_id
                elif self.section == 'relationships':
                    first, second = self._value('first'), self._value('second')
                    if not first or not second or first == second:
                        raise ValueError('서로 다른 두 인물을 선택하세요.')
                    episode = self.episode.value()
                    history = db.history(pid, first, second)
                    current = next((x for x in history if x.episode == episode), None)
                    db.save_relation(pid, first, second, episode,
                                     relationship=self._value('relationship'),
                                     notes=self._value('notes'),
                                     expected_revision=(current.revision if current else None))
                else:
                    if row is None:
                        saved = db.create_thread(pid, title=self._value('title'),
                                                 episode=self.episode.value(),
                                                 note=self._value('note'))
                        selected = saved.thread_id
                    else:
                        db.add_event(pid, row.thread_id, episode=self.episode.value(),
                                     action=self._value('action'), note=self._value('note'),
                                     expected_revision=row.revision)
                        selected = row.thread_id
            self.refresh(selected)
            self.status.setText('현재 작품의 로컬 SQLite에 저장했습니다.')
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc)[:160])
