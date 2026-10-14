"""Stage 11: reference-novel chooser UI; no content reads or uploads."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QVBoxLayout, QWidget,
)

from .reference_selection import REFERENCE_FILE_FILTER, ReferenceFileSelection


class ReferencePickerWidget(QWidget):
    """In-memory file chooser; selections are not imported or persisted."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selection = ReferenceFileSelection()
        layout = QVBoxLayout(self)

        notice = QLabel(
            "TXT · Markdown · EPUB · DOCX · PDF 파일을 선택할 수 있습니다. "
            "선택만 하며 원문을 읽거나 서버에 전송하지 않습니다."
        )
        notice.setWordWrap(True)
        notice.setObjectName("referencePrivacyNotice")
        layout.addWidget(notice)

        actions = QHBoxLayout()
        self.choose_button = QPushButton("참고소설 파일 선택…")
        self.choose_button.setObjectName("chooseReferenceFilesButton")
        self.choose_button.clicked.connect(self.choose_files)
        self.clear_button = QPushButton("선택 목록 비우기")
        self.clear_button.setObjectName("clearReferenceFilesButton")
        self.clear_button.clicked.connect(self.clear_files)
        actions.addWidget(self.choose_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.file_list = QListWidget()
        self.file_list.setObjectName("selectedReferenceFiles")
        self.file_list.setAccessibleName("선택한 참고소설 파일 이름 목록")
        layout.addWidget(self.file_list)

        self.selection_status = QLabel()
        self.selection_status.setObjectName("referenceSelectionStatus")
        layout.addWidget(self.selection_status)
        self._refresh()

    def choose_files(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "참고소설 파일 선택",
            "",
            REFERENCE_FILE_FILTER,
        )
        # Canceling the dialog must not clear an earlier selection.
        if paths:
            self.selection.add_paths(paths)
            self._refresh()

    def clear_files(self) -> None:
        self.selection.clear()
        self._refresh()

    def _refresh(self) -> None:
        self.file_list.clear()
        self.file_list.addItems(self.selection.display_names)
        count = len(self.selection.selected_paths)
        self.selection_status.setText(
            f"{count}개 파일 선택됨 · 아직 가져오기/분석/저장하지 않음"
        )
        self.clear_button.setEnabled(count > 0)
