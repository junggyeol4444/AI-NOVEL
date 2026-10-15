"""Stage 8: basic PySide6 shell, without external side effects.

PySide6 is an optional dependency; import this module only when launching UI.
"""
from __future__ import annotations
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow,
    QPushButton, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)
from .navigation import SECTIONS
from .api_client import check_local_health
from .reference_picker import ReferencePickerWidget
from .reference_profile_browser import ReferenceProfileBrowser
from .plot_editor import PlotEditorWidget
from .authoring_workflow import AuthoringWorkflowWidget
from .canon_workspace import CanonWorkspace, STORES
from .additional_workspaces import PatternWorkspace, SimilarityWorkspace, PublicationWorkspace
from .task_monitor_widget import TaskMonitorWidget
from .operations_monitor_widget import OperationsMonitorWidget
from ai_novel_factory.settings import load_settings, ConfigurationError

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('AI Novel Factory — 개발 중')
        self.resize(1120, 720)
        self.setMinimumSize(760, 500)
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName('sectionSidebar')
        self.sidebar.setFixedWidth(215)
        self.sidebar.addItems([s.label for s in SECTIONS])
        self.canon_panels = {}
        self.additional_panels = {}
        self.pages = QStackedWidget()
        self.pages.setObjectName('sectionPages')
        for section in SECTIONS:
            page = QWidget()
            layout = QVBoxLayout(page)
            title = QLabel(section.label)
            title.setObjectName(f'title_{section.key}')
            title.setStyleSheet('font-size: 24px; font-weight: bold; margin-bottom: 12px;')
            description = QLabel(section.description)
            description.setWordWrap(True)
            pending = QLabel('해당 기능은 후속 개발 단계에서 연결됩니다.')
            pending.setObjectName(f'pending_{section.key}')
            pending.setStyleSheet('color: #666;')
            layout.addWidget(title)
            layout.addWidget(description)
            if section.key == 'novels':
                self.authoring = AuthoringWorkflowWidget(page)
                layout.addWidget(self.authoring)
            elif section.key in STORES:
                panel = CanonWorkspace(section.key, self._current_project, page)
                self.canon_panels[section.key] = panel
                layout.addWidget(panel)
            elif section.key == 'references':
                # Stage 11: selection only, no file content access or import.
                self.reference_picker = ReferencePickerWidget(page)
                layout.addWidget(self.reference_picker)
                self.reference_profile_browser = ReferenceProfileBrowser(self.reference_picker.selection, page)
                layout.addWidget(self.reference_profile_browser)
            elif section.key == 'episodes':
                self.plot_editor = PlotEditorWidget()
                plot_scroll = QScrollArea(page)
                plot_scroll.setObjectName('plotEditorScrollArea')
                plot_scroll.setWidgetResizable(True)
                plot_scroll.setWidget(self.plot_editor)
                tabs = QTabWidget(page)
                tabs.setObjectName('episodeWorkTabs')
                tabs.addTab(plot_scroll, '회차·장면 플롯')
                self.task_monitor = TaskMonitorWidget(page)
                tabs.addTab(self.task_monitor, '집필 작업 진행률')
                self.operations_monitor = OperationsMonitorWidget(page)
                tabs.addTab(self.operations_monitor, '작업 로그·비용·오류')
                layout.addWidget(tabs)
            elif section.key in ('patterns', 'similarity', 'publication'):
                cls = {'patterns': PatternWorkspace, 'similarity': SimilarityWorkspace,
                       'publication': PublicationWorkspace}[section.key]
                panel = (cls(page) if section.key == 'patterns' else
                         cls(lambda: self.authoring.session, page))
                self.additional_panels[section.key] = panel
                layout.addWidget(panel)
            else:
                layout.addWidget(pending)
                layout.addStretch(1)
            self.pages.addWidget(page)
        outer.addWidget(self.sidebar)
        outer.addWidget(self.pages, stretch=1)
        self.sidebar.currentRowChanged.connect(self._change_page)
        self.sidebar.setCurrentRow(0)
        self.api_check_button = QPushButton('로컬 API 연결 확인')
        self.api_check_button.setObjectName('checkLocalApiButton')
        self.api_check_button.setToolTip('버튼을 눌렀을 때만 로컬 API에 연결합니다.')
        self.api_check_button.clicked.connect(self._check_api)
        self.statusBar().addPermanentWidget(self.api_check_button)
        self.statusBar().showMessage('로컬 UI 준비됨 · API 미연결 · AI/출판 비활성')
        # No network request happens automatically. Publishing and AI remain disabled.

    def closeEvent(self, event) -> None:
        authoring = getattr(self, 'authoring', None)
        if authoring is not None and authoring.auto_panel.is_running():
            authoring.auto_panel.request_stop()
            self.statusBar().showMessage('로컬 AI 집필 작업 중단 요청 중 · 프로세스 완료 후 종료해 주세요.')
            event.ignore()
            return
        editor = getattr(self, 'plot_editor', None)
        if editor is not None:
            if not editor._warn_unsaved():
                event.ignore()
                return
            editor.session.close()
        authoring = getattr(self, 'authoring', None)
        if authoring is not None:
            authoring.session.close()
        event.accept()

    def _check_api(self) -> None:
        try:
            result = check_local_health(load_settings())
            self.statusBar().showMessage(result.message + ' · AI/출판 비활성')
        except ConfigurationError:
            self.statusBar().showMessage('API 설정 오류 · AI/출판 비활성')

    def _current_project(self):
        authoring = getattr(self, 'authoring', None)
        if authoring is None:
            return None
        session = authoring.session
        return (session.path, session.project_id) if session.project_id else None

    def _change_page(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)
            key = SECTIONS[index].key
            if key in self.canon_panels:
                self.canon_panels[key].refresh()
            elif key in self.additional_panels:
                self.additional_panels[key].refresh()

def run() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if owns_app:
        return app.exec()
    return 0
