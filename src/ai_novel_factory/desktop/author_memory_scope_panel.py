"""Read-only 30/100/250 chapter author memory scope in native PySide6."""
from __future__ import annotations
from PySide6.QtWidgets import (QComboBox, QGroupBox, QLabel, QPushButton,
                               QPlainTextEdit, QVBoxLayout)
from ..author_memory_delta import AuthorMemoryDeltaError
from ..author_memory_context import plan_author_memory_scope


class AuthorMemoryScopePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 작가 기억 변화 근거 현황 (읽기 전용)', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        self.scope = QComboBox()
        for count in (30, 100, 250, 1000):
            self.scope.addItem(f'{count}화', count)
        root.addWidget(self.scope)
        self.check = QPushButton('저장된 회차와 기억 변화 근거 현황 직접 조회')
        self.check.clicked.connect(self.refresh)
        root.addWidget(self.check)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        self.output.setMaximumHeight(340)
        root.addWidget(self.output)
        self.status = QLabel('출판/품질 합격 판정 없음 · 원고/SQLite 읽기 전용')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.scope.currentIndexChanged.connect(self.invalidate)

    def invalidate(self, *_):
        self.output.clear()
        self.status.setText('선택/작품이 변경되어 다시 직접 조회해야 합니다.')

    def refresh(self):
        self.output.clear()
        try:
            author = getattr(self.authoring, 'author_memory_panel', None)
            if author is None or author.folder is None:
                raise AuthorMemoryDeltaError('기억 기록 폴더를 먼저 선택해야 합니다.')
            store, pid = self.authoring.session.required()
            rows = plan_author_memory_scope(store, str(pid), folder=author.folder,
                                            through_episode=int(self.scope.currentData()))
            status = {name: sum(item.status == name for item in rows)
                      for name in ('EXISTING', 'MEMORY_READY', 'MEMORY_STALE',
                                   'AUTHOR_MEMORY_MISSING')}
            lines = [f'{len(rows)}화 중 기존 저장 {status["EXISTING"]}, '
                     f'기억 준비 {status["MEMORY_READY"]}, '
                     f'근거 변경 {status["MEMORY_STALE"]}, '
                     f'작가 기록 없음 {status["AUTHOR_MEMORY_MISSING"]}',
                     'MEMORY_READY는 작가 기록 확인 상태이지 집필·QC·출판 PASS가 아닙니다.']
            lines.extend(f'{v.episode}화: {v.status} / 관련 {v.item_count}건'
                         for v in rows if v.status != 'EXISTING')
            self.output.setPlainText('\n'.join(lines))
            self.status.setText('현재 SQLite/작가 기억 기록을 읽었습니다. 저장/모델 실행 없음.')
        except (ValueError, OSError):
            self.status.setText('선택한 기존 작품 또는 기억 파일을 다시 확인하세요. 원본 변경 없음.')
        except Exception:
            self.status.setText('기억 근거 현황을 조회할 수 없습니다. 원본 변경 없음.')
