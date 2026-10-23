"""Lazy local Windows authoring workspace for the pre-existing features.

Does not import optional tools, read manuscripts, create databases, run AI,
record approval, publish, or create files before a direct author action.
"""
from __future__ import annotations
from importlib import import_module
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QLabel, QPushButton, QStackedWidget, QWidget,
)
from ai_novel_factory.feature_workspace_registry import FEATURE_ENTRIES, get_feature_entry
from .author_navigation_contract import prefill_existing_feature


class FeatureWorkspaceHub(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('7. 통합 로컬 집필 작업 공간 (사용자 직접 실행)', parent)
        self.authoring = authoring
        self._opened = {}
        self._mounted = set()
        self._active_attribute = ''
        self._project_signature = self._signature()
        root = QVBoxLayout(self)
        note = QLabel('기존 기능을 필요할 때만 엽니다. 모델 실행, 검수 완료, 출판 승인은 자동으로 수행하지 않습니다.')
        note.setWordWrap(True)
        root.addWidget(note)
        actions = QHBoxLayout()
        self.finder = QLineEdit()
        self.finder.setPlaceholderText('기능 검색: 참고작, 인물, EPUB, 검수, SQLite …')
        self.finder.setObjectName('authoringFeatureSearch')
        self.selector = QComboBox()
        self.selector.setObjectName('authoringFeatureSelector')
        self.open_button = QPushButton('선택한 기능 열기')
        self.open_button.setObjectName('authoringFeatureOpen')
        self.refresh_button = QPushButton('현재 기능 새로고침')
        self.refresh_button.setObjectName('authoringFeatureRefresh')
        actions.addWidget(self.finder)
        actions.addWidget(self.selector)
        actions.addWidget(self.open_button)
        actions.addWidget(self.refresh_button)
        root.addLayout(actions)
        self.status = QLabel('작품을 열고 원하는 기능을 직접 선택하세요.')
        self.status.setWordWrap(True)
        self.status.setObjectName('authoringFeatureStatus')
        root.addWidget(self.status)
        self.pages = QStackedWidget()
        self.pages.setObjectName('authoringFeaturePages')
        self.placeholder = QLabel('선택한 기능을 열면 이 영역에 표시됩니다.')
        self.placeholder.setWordWrap(True)
        self.pages.addWidget(self.placeholder)
        root.addWidget(self.pages)
        self._fill_entries('')
        self.finder.textChanged.connect(self._fill_entries)
        self.open_button.clicked.connect(self.open_selected)
        self.refresh_button.clicked.connect(self.refresh_visible)
        # Current executable/arguments are independent of project identity.
        for key in ('executable', 'arguments'):
            field = self.authoring.fields.get(key)
            if field is not None:
                field.textChanged.connect(self._revoke_model_lease)

    def _signature(self):
        session = getattr(self.authoring, 'session', None)
        return (str(getattr(session, 'path', None)),
                str(getattr(session, 'project_id', None)))

    def _fill_entries(self, keyword: str):
        selected = self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        key = keyword.strip().casefold()
        for entry in FEATURE_ENTRIES:
            label = entry.group + ' / ' + entry.caption
            if not key or key in label.casefold():
                self.selector.addItem(label, entry.instance_attribute)
        index = self.selector.findData(selected)
        if index >= 0:
            self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        self.open_button.setEnabled(self.selector.count() > 0)

    def _revoke_model_lease(self, _text):
        obj = self._opened.get('local_model_integrity_panel')
        if obj is not None and hasattr(obj, 'invalidate'):
            obj.invalidate()

    def invalidate_all(self):
        """Clear opt-in and stale previews when DB/project changes.

        Never close a running model worker or rewrite any user data.
        """
        new_sig = self._signature()
        if new_sig == self._project_signature:
            # DB path changes can happen before open_project updates session.
            # The calling workflow still treats this as a revocation.
            pass
        self._project_signature = new_sig
        for obj in list(self._opened.values()):
            if hasattr(obj, 'invalidate'):
                try:
                    obj.invalidate()
                except (ValueError, OSError):
                    self.status.setText('일부 도구의 이전 선택을 초기화하지 못했습니다. 다시 확인하세요.')
                except Exception:
                    self.status.setText('도구 상태를 새 작품에 맞춰 다시 선택하세요.')
        self._active_attribute = ''
        self.pages.setCurrentWidget(self.placeholder)
        self.status.setText('작품/경로가 변경됐습니다. 실행·검수·출판은 다시 직접 승인해야 합니다.')

    def open_selected(self):
        attr = self.selector.currentData()
        if not attr:
            self.status.setText('선택한 기능이 없습니다.')
            return
        if getattr(self.authoring.session, 'store', None) is None:
            self.status.setText('먼저 기존 작품을 열거나 새 작품을 생성하세요.')
            return
        self._open(attr)

    def open_feature(self, attr, *, episode_number=None, project_identity=None):
        """작가가 직접 선택한 현재 작품의 허용 화면만 연다. 실행하지 않는다."""
        current = self._signature()
        if project_identity is not None and tuple(project_identity) != current:
            self.status.setText('작품이 변경됐습니다. 작업 목록을 다시 조회하세요.')
            return False
        if current != self._project_signature:
            # 이전 작품에서 연 패널의 선택/승인 지문을 새 작품에 재사용 금지.
            self.invalidate_all()
        if getattr(self.authoring.session, 'store', None) is None:
            self.status.setText('먼저 기존 작품을 열어 주세요.')
            return False
        try:
            get_feature_entry(attr)
        except KeyError:
            self.status.setText('등록되지 않은 기능은 열 수 없습니다.')
            return False
        if not self._open(attr):
            return False
        if episode_number is not None:
            widget = self._opened.get(attr)
            if widget is not None and prefill_existing_feature(widget, attr, episode_number):
                self.status.setText(
                    f'{episode_number}화 범위를 입력했습니다. 조회·검수·승인은 직접 실행하세요.')
        return True

    def _open(self, attr):
        entry = get_feature_entry(attr)
        self._project_signature = self._signature()
        obj = self._opened.get(attr)
        if obj is None:
            # Some 31–47 integration patches already attach a widget to the
            # original form. Reuse it and never instantiate a duplicate.
            obj = getattr(self.authoring, attr, None)
            if obj is None:
                try:
                    module = import_module('ai_novel_factory.desktop.' + entry.module)
                    widget_class = getattr(module, entry.class_name)
                    obj = widget_class(self.authoring, self.authoring)
                except (ImportError, AttributeError, ValueError, OSError):
                    self.status.setText('선택한 기능의 코드가 아직 기존 main에 설치되지 않았습니다.')
                    return False
                except Exception:
                    self.status.setText('선택한 기능을 열지 못했습니다. 원고는 변경되지 않았습니다.')
                    return False
                setattr(self.authoring, attr, obj)
                self.pages.addWidget(obj)
                self._mounted.add(attr)
            self._opened[attr] = obj
        self._active_attribute = attr
        if attr in self._mounted:
            self.pages.setCurrentWidget(obj)
            self.status.setText(entry.caption + ': 기능을 열었습니다. 실행·저장 버튼은 별도로 누르세요.')
        else:
            # Existing GUI already owns the widget. Never reparent it.
            obj.setFocus()
            self.status.setText(entry.caption + ': 기존 화면에 이미 열려 있습니다. 아래 해당 패널에서 직접 사용하세요.')
        self.refresh_visible()
        return True

    def refresh_visible(self):
        obj = self._opened.get(self._active_attribute)
        if obj is None:
            return
        action = getattr(obj, 'refresh', None)
        if callable(action):
            try:
                action()
            except (ValueError, OSError):
                self.status.setText('기능 상태 갱신에 실패했습니다. 프로젝트 선택을 확인하세요.')
            except Exception:
                self.status.setText('선택한 기능을 직접 다시 열어 확인하세요.')
