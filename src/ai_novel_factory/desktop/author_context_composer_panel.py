"""Windows/PySide6 local author context selection and episode preview.

All optional records require a separate explicit selection. Preview is not an
AI execution approval. The form never changes a manuscript or reference work.
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QLabel,
                               QPushButton, QSpinBox, QPlainTextEdit,
                               QFileDialog, QVBoxLayout)
from ..author_memory_delta import (AuthorMemoryDeltaError, list_author_memory_deltas,
                                   memory_delta_fingerprint)
from ..author_context_envelope import (AuthorContextSources, AuthorContextEnvelopeError,
                                       capture_author_context_sources,
                                       compose_author_context,
                                       require_unchanged_author_sources)


class AuthorContextComposerPanel(QGroupBox):
    _SOURCE_NAMES = (
        ('arc', '장편 아크'), ('scene', '회차별 장면 설계표'),
        ('fact', '과거 저장 원고 기반 작가 사실'), ('language', '고유명사·말투 규칙'),
        ('memory', '작가 직접 기록한 기억 변화'),
    )

    def __init__(self, authoring, parent=None):
        super().__init__('작가 장편 통합 문맥 / 로컬 미리보기', parent)
        self.authoring = authoring
        self.folders: dict[str, Path] = {}
        self._approved: AuthorContextSources | None = None
        root = QVBoxLayout(self)
        note = QLabel('작가 기록만 선택해 조합합니다. 미선택 기록을 AI가 추론해 채우지 않습니다. '
                      '문맥 미리보기는 AI 모델 실행/품질 QC/출판 승인과 별개입니다.')
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        root.addLayout(form)
        self.folder_labels: dict[str, QLabel] = {}
        for key, caption in self._SOURCE_NAMES:
            choose = QPushButton(caption + ' 기존 로컬 폴더 직접 선택')
            choose.clicked.connect(lambda _checked=False, k=key: self.choose_folder(k))
            self.folder_labels[key] = QLabel('미선택')
            form.addRow(choose, self.folder_labels[key])
        self.episode = QSpinBox(); self.episode.setRange(1, 1000)
        self.episode.setValue(1)
        form.addRow('집필 예정 회차', self.episode)
        self.scenes = QSpinBox(); self.scenes.setRange(1, 20)
        self.scenes.setValue(3)
        form.addRow('해당 회차 장면 수', self.scenes)
        self.preview_button = QPushButton('선택한 작가 기록을 통합해 미리보기')
        self.preview_button.clicked.connect(self.refresh)
        root.addWidget(self.preview_button)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(260)
        root.addWidget(self.preview)
        self.consent = QCheckBox('위 폴더들의 현재 지문을 이번 AI 배치 문맥에 1회 사용하는 데 별도 동의합니다')
        self.consent.setObjectName('authorContextComposerOneBatchOptIn')
        self.consent.toggled.connect(self._approval_changed)
        root.addWidget(self.consent)
        self.status = QLabel('모든 항목은 기존 SQLite/작가 JSON 읽기 전용입니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.episode.valueChanged.connect(self._reset_consent)
        self.scenes.valueChanged.connect(self._reset_consent)

    def _reset_consent(self, *_):
        self._approved = None
        self.consent.blockSignals(True)
        self.consent.setChecked(False)
        self.consent.blockSignals(False)
        self.preview.clear()

    def invalidate(self):
        self._reset_consent()
        self.folders.clear()
        for label in self.folder_labels.values():
            label.setText('미선택')
        self.status.setText('작품이 변경되어 이전 작가 기록/승인이 해제되었습니다.')

    def choose_folder(self, key: str):
        selected = QFileDialog.getExistingDirectory(self, '기존 작가 기록 폴더 직접 선택')
        if selected:
            self.folders[key] = Path(selected)
            self._reset_consent()
            self.folder_labels[key].setText('선택됨 · 로컬 원본 변경 없음')

    def accept_existing_memory_folder(self, folder: Path) -> None:
        """A direct click in the existing memory editor selects, never approves."""
        store, project_id = self.authoring.session.required()
        path = Path(folder)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise AuthorMemoryDeltaError('기존 로컬 기억 기록 폴더를 직접 선택하세요.')
        if not any(not row.retracted for row in
                   list_author_memory_deltas(path, str(project_id))):
            raise AuthorMemoryDeltaError('현재 작품에 활성 작가 기억 기록이 없습니다.')
        memory_delta_fingerprint(path)
        self.folders['memory'] = path
        self._reset_consent()
        self.folder_labels['memory'].setText('작가가 기존 기억 화면에서 직접 선택함')
        self.status.setText('기억 폴더만 선택했습니다. 미리보기와 AI 문맥 동의는 별도로 진행하세요.')

    def _capture(self) -> AuthorContextSources:
        store, project_id = self.authoring.session.required()
        return capture_author_context_sources(
            store, str(project_id), arc_folder=self.folders.get('arc'),
            scene_folder=self.folders.get('scene'), fact_folder=self.folders.get('fact'),
            language_folder=self.folders.get('language'),
            memory_folder=self.folders.get('memory'))

    def refresh(self):
        self._reset_consent()
        try:
            store, project_id = self.authoring.session.required()
            selection = self._capture()
            bundle = compose_author_context(store, str(project_id),
                                            episode=self.episode.value(),
                                            scene_count=self.scenes.value(),
                                            sources=selection)
            lines = [bundle.outline, '\n[장면별 별도 추가 계획 — 읽기 전용]']
            lines.extend(f'장면 {index}: {body}' for index, body
                         in enumerate(bundle.scenes, start=1) if body)
            self.preview.setPlainText('\n'.join(lines))
            self.status.setText('작가 통합 문맥 조회 완료 · 원고/DB 저장이나 모델 호출 없음.')
        except (AuthorContextEnvelopeError, ValueError, OSError):
            self.status.setText('선택한 작가 기록이 누락·충돌·변경됐거나 문맥 한도를 초과했습니다.')
        except Exception:
            self.status.setText('문맥 조회를 완료하지 못했습니다. 원고/DB 변경 없음.')

    def _approval_changed(self, checked: bool):
        self._approved = None
        if not checked:
            return
        try:
            store, project_id = self.authoring.session.required()
            selection = self._capture()
            compose_author_context(store, str(project_id),
                                   episode=self.episode.value(),
                                   scene_count=self.scenes.value(), sources=selection)
            self._approved = selection
            self.status.setText('이 선택의 현재 지문만 1회 승인했습니다. 모델 실행은 별도 승인해야 합니다.')
        except (ValueError, OSError):
            self.consent.blockSignals(True)
            self.consent.setChecked(False)
            self.consent.blockSignals(False)
            self.status.setText('현재 선택을 승인할 수 없습니다. 기록과 문맥을 다시 확인하세요.')

    def consume_batch_sources(self) -> AuthorContextSources | None:
        """Called by explicit batch-start handler only, never during GUI setup."""
        if not self.consent.isChecked():
            return None
        selected = self._approved
        self._reset_consent()
        if selected is None:
            raise AuthorContextEnvelopeError('작가 통합 문맥 사용 동의가 유효하지 않습니다.')
        store, project_id = self.authoring.session.required()
        require_unchanged_author_sources(store, str(project_id), selected)
        return selected
