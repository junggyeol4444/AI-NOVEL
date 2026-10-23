"""Read-only GUI for author-context coverage across 30/100/250 episodes."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QLabel,
                               QPushButton, QPlainTextEdit, QSpinBox, QVBoxLayout)
from ..author_context_scope import plan_author_context_scope
from ..author_context_envelope import (AuthorContextEnvelopeError,
                                       capture_author_context_sources)


class AuthorContextScopePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 작가 통합 문맥 준비 범위 (읽기 전용)', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        info = QLabel('30/100/250화 작가 문맥 준비만 조회합니다. 실제 AI 집필, 품질 검사, '
                      '출판 승인으로 계산하지 않습니다.')
        info.setWordWrap(True)
        root.addWidget(info)
        form = QFormLayout(); root.addLayout(form)
        self.range = QComboBox()
        for count in (30, 100, 250):
            self.range.addItem(f'{count}화', count)
        form.addRow('계획 조회 범위', self.range)
        self.scenes = QSpinBox(); self.scenes.setRange(1, 20); self.scenes.setValue(3)
        form.addRow('회차당 장면 수', self.scenes)
        self.button = QPushButton('현재 선택된 작가 기록으로 준비 범위 조회')
        self.button.clicked.connect(self.refresh)
        root.addWidget(self.button)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        self.output.setMaximumHeight(290); root.addWidget(self.output)
        self.status = QLabel('통합 문맥 화면에서 로컬 폴더를 먼저 직접 지정하세요.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.range.currentIndexChanged.connect(self.invalidate)
        self.scenes.valueChanged.connect(self.invalidate)

    def invalidate(self, *_):
        self.output.clear()
        self.status.setText('선택 또는 작품이 변경됐습니다. 직접 다시 조회하세요.')

    def refresh(self):
        self.output.clear()
        try:
            composer = getattr(self.authoring, 'author_context_composer_panel', None)
            if composer is None:
                raise AuthorContextEnvelopeError('통합 문맥 폴더 선택 필요')
            store, project_id = self.authoring.session.required()
            selection = capture_author_context_sources(
                store, str(project_id), arc_folder=composer.folders.get('arc'),
                scene_folder=composer.folders.get('scene'),
                fact_folder=composer.folders.get('fact'),
                language_folder=composer.folders.get('language'),
                memory_folder=composer.folders.get('memory'))
            plan = plan_author_context_scope(store, str(project_id),
                                             through_episode=int(self.range.currentData()),
                                             scenes_per_episode=self.scenes.value(),
                                             sources=selection)
            lines = [f'{plan.total}화 범위: 기존 저장 {plan.existing}, 문맥 준비 {plan.ready}, '
                     f'추가 작가 확인 필요 {plan.blocked}',
                     '준비=문맥 조합 가능, 실제 AI 집필/품질 QC/출판 합격 아님.']
            for episode in plan.episodes:
                if episode.status != 'CONTEXT_READY':
                    lines.append(f'{episode.episode}화: {episode.status} / {episode.note}')
            self.output.setPlainText('\n'.join(lines[:270]))
            self.status.setText('기존 SQLite/작가 기록을 읽기만 했습니다. 실행·저장·출판 없음.')
        except (AuthorContextEnvelopeError, ValueError, OSError):
            self.status.setText('작가 기록 또는 선택 범위가 유효하지 않아 조회를 보류했습니다.')
        except Exception:
            self.status.setText('준비 범위를 조회하지 못했습니다. 로컬 원본은 변경하지 않았습니다.')
