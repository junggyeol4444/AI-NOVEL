"""Read-only preview of the author arc bound to a particular draft episode."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox,QVBoxLayout,QSpinBox,QLabel,
                                QPushButton,QFileDialog,QPlainTextEdit)
from ..author_arc_context import build_author_arc_context
from ..author_arc_ledger import AuthorArcError

class AuthorArcContextPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 아크 회차별 문맥 미리보기 (집필·저장 없음)',parent)
        self.authoring=authoring;self.folder=None
        root=QVBoxLayout(self)
        self.episode=QSpinBox();self.episode.setRange(1,1000)
        root.addWidget(self.episode)
        choose=QPushButton('기존 아크 계획 폴더 선택')
        choose.clicked.connect(self.choose);root.addWidget(choose)
        self.context=QPlainTextEdit();self.context.setReadOnly(True)
        self.context.setMaximumHeight(180);root.addWidget(self.context)
        preview=QPushButton('선택 회차의 작가 아크 문맥 읽기')
        preview.clicked.connect(self.refresh);root.addWidget(preview)
        self.status=QLabel('AI 모델 실행·원고 수정·출판 없음')
        self.status.setWordWrap(True);root.addWidget(self.status)

    def invalidate(self):
        self.context.clear();self.status.setText('작품 변경: 이전 문맥을 초기화했습니다.')

    def choose(self):
        path=QFileDialog.getExistingDirectory(self,'기존 로컬 아크 기록 폴더')
        if path:
            self.folder=Path(path);self.invalidate()

    def refresh(self):
        self.context.clear()
        try:
            db,pid=self.authoring.session.required()
            if self.folder is None:raise AuthorArcError('아크 폴더 선택 필요')
            result=build_author_arc_context(db,str(pid),next_episode=self.episode.value(),
                                            folder=self.folder)
            if result.stale_canon:
                self.status.setText('작품 설정 변경: 기존 작가 아크를 새로 검토해야 합니다.')
            elif result.scope_missing:
                self.status.setText('이 회차를 포함하는 작가 아크 계획이 없습니다.')
            else:
                self.context.setPlainText(result.context)
                self.status.setText('작가 입력 문맥만 조회했습니다. 실제 AI 집필·QC PASS는 NOT_RUN.')
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('현재 아크 계획을 읽을 수 없습니다.')
