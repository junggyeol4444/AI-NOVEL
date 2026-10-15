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
from .font_support import apply_korean_ui_font
from .project_studio import ProjectStudio
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
        self.korean_font_supported = apply_korean_ui_font()
        self.setWindowTitle('AI Novel Factory — 개발 중')
        self.resize(1420, 850)
        self.setMinimumSize(940, 600)
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName('sectionSidebar')
        self.sidebar.setFixedWidth(215)
        self.sidebar.addItems([s.label for s in SECTIONS])
        self.canon_panels = {}
        self.studio = None
        self.plot_editor = None
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
                self.novel_tabs = QTabWidget(page)
                self.novel_tabs.setObjectName('novelStudioTabs')
                self.studio = ProjectStudio(
                    self.authoring, self._go_to_key,
                    lambda: self.novel_tabs.setCurrentIndex(1), page)
                self.novel_tabs.addTab(self.studio, '작품 홈 · 집필실')
                self.novel_tabs.addTab(self.authoring, '기존 기능 · 상세 작업')
                layout.addWidget(self.novel_tabs)
                # The detailed existing tools remain available without replacing
                # user data or changing their Qt automation object names.
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
        # Windows UIAutomation SelectionItemPattern may change selection
        # without changing the QListWidget current row. Treat both native
        # accessibility selection and pointer/keyboard navigation as paths.
        self.sidebar.itemSelectionChanged.connect(self._change_page_from_selection)
        self.sidebar.setCurrentRow(0)
        self.api_check_button = QPushButton('고급: 연결 확인')
        self.api_check_button.setObjectName('checkLocalApiButton')
        self.api_check_button.setToolTip('버튼을 눌렀을 때만 로컬 API에 연결합니다.')
        self.api_check_button.clicked.connect(self._check_api)
        self.statusBar().addPermanentWidget(self.api_check_button)
        self.statusBar().showMessage('내 컴퓨터에 안전하게 보관 · AI 실행과 외부 게시에는 별도 승인이 필요합니다.')
        # No network request happens automatically. Publishing and AI remain disabled.

    def closeEvent(self, event) -> None:
        if self.studio is not None and not self.studio.confirm_discard():
            event.ignore()
            return
        authoring = getattr(self, 'authoring', None)
        if authoring is not None and authoring.auto_panel.is_running():
            authoring.auto_panel.request_stop()
            self.statusBar().showMessage('로컬 AI 집필 작업 중단 요청 중 · 프로세스 완료 후 종료해 주세요.')
            event.ignore()
            return
        publisher = getattr(self, 'additional_panels', {}).get('publication')
        if publisher is not None and getattr(publisher, 'wp_worker', None) is not None:
            if publisher.wp_worker.isRunning():
                self.statusBar().showMessage(
                    '외부 초안 전송 진행 중입니다. 결과를 확인한 후 종료해 주세요.')
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
            self.statusBar().showMessage(result.message + ' · AI는 개별 승인 필요 · 외부 전송은 별도 승인')
        except ConfigurationError:
            self.statusBar().showMessage('API 설정 오류 · AI는 개별 승인 필요 · 외부 전송은 별도 승인')

    def _current_project(self):
        authoring = getattr(self, 'authoring', None)
        if authoring is None:
            return None
        session = authoring.session
        return (session.path, session.project_id) if session.project_id else None

    def _change_page_from_selection(self) -> None:
        selected = self.sidebar.selectedItems()
        if not selected:
            return
        index = self.sidebar.row(selected[0])
        if index >= 0 and index != self.pages.currentIndex():
            self._change_page(index)

    def _go_to_key(self, key: str) -> None:
        for index, section in enumerate(SECTIONS):
            if section.key == key:
                self.sidebar.setCurrentRow(index)
                return

    def _change_page(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            if (self.pages.currentIndex() == 0 and index != 0 and
                    self.studio is not None and not self.studio.confirm_discard()):
                self.sidebar.blockSignals(True)
                self.sidebar.setCurrentRow(0)
                self.sidebar.blockSignals(False)
                return
            self.pages.setCurrentIndex(index)
            key = SECTIONS[index].key
            if key == 'novels' and self.studio is not None:
                self.studio.refresh()
            if key == 'episodes' and self.plot_editor is not None:
                current = self._current_project()
                if current is not None:
                    path, _pid = current
                    if getattr(self, '_plot_synced_path', None) != path:
                        self.plot_editor.open_database(str(path))
                        self._plot_synced_path = path
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
