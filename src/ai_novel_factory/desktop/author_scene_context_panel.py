"""Read-only local scene-plan preview; never calls a model or writes a DB."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QSpinBox, QLabel,
                                QPushButton, QFileDialog, QPlainTextEdit)
from ..author_scene_context import build_author_scene_context
from ..author_scene_plan import AuthorScenePlanError


class AuthorSceneContextPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 장면 설계표 · 회차별 읽기 전용 미리보기', parent)
        self.authoring = authoring
        self.folder = None
        root = QVBoxLayout(self)
        self.episode = QSpinBox(); self.episode.setRange(1, 1000)
        self.scenes = QSpinBox(); self.scenes.setRange(1, 20); self.scenes.setValue(3)
        root.addWidget(QLabel('회차')); root.addWidget(self.episode)
        root.addWidget(QLabel('해당 회차 장면 수')); root.addWidget(self.scenes)
        choose = QPushButton('기존 장면 계획 폴더 선택')
        choose.clicked.connect(self.choose_folder); root.addWidget(choose)
        self.context = QPlainTextEdit(); self.context.setReadOnly(True)
        self.context.setMaximumHeight(210); root.addWidget(self.context)
        preview = QPushButton('현재 회차 장면 설계표 읽기')
        preview.clicked.connect(self.refresh); root.addWidget(preview)
        self.status = QLabel('모델 호출·SQLite 쓰기·출판 없음')
        self.status.setWordWrap(True); root.addWidget(self.status)

    def invalidate(self):
        self.context.clear()
        self.status.setText('작품 변경: 이전 장면 계획 문맥을 초기화했습니다.')

    def choose_folder(self):
        value = QFileDialog.getExistingDirectory(self, '기존 로컬 장면 계획 폴더')
        if value:
            self.folder = Path(value)
            self.invalidate()

    def refresh(self):
        self.context.clear()
        try:
            store, pid = self.authoring.session.required()
            if self.folder is None:
                raise AuthorScenePlanError('장면 계획 폴더 선택 필요')
            state = build_author_scene_context(store, str(pid),
                episode=self.episode.value(), scenes_per_episode=self.scenes.value(),
                folder=self.folder)
            if state.missing:
                self.status.setText('이 회차의 작가 장면 계획이 없습니다.')
            elif state.stale:
                self.status.setText('작품 설정 변경: 계획을 다시 확인해야 합니다.')
            else:
                self.context.setPlainText(state.outline_context + '\n\n' +
                                          '\n\n'.join(state.scene_contexts))
                self.status.setText('작가 작성 문맥만 읽음. 실제 AI 집필·QC PASS는 NOT_RUN.')
        except (AuthorScenePlanError, OSError, ValueError):
            self.status.setText('장면 계획을 읽지 못했습니다. 선택 회차와 장면 수를 확인하세요.')
