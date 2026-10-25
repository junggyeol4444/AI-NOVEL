"""Windows/PySide6 local author context selection and episode preview.

All optional records require a separate explicit selection. Preview is not an
AI execution approval. The form never changes a manuscript or reference work.
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QLabel,
                               QPushButton, QSpinBox, QPlainTextEdit,
                               QFileDialog, QVBoxLayout)
from ..author_continuity_context_handoff import (
    ContinuityContextLease, ContinuityContextHandoffError,
    require_current_continuity_context,
)
from ..author_scene_plan import (
    AuthorScenePlanError, read_author_scene_plans, scene_plan_fingerprint,
)
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
        self._handoff_lease: ContinuityContextLease | None = None
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
        self.episode.valueChanged.connect(self._episode_changed)
        self.scenes.valueChanged.connect(self._episode_changed)

    def _episode_changed(self, *_):
        self._handoff_lease = None
        self._reset_consent()

    def _reset_consent(self, *_):
        self._approved = None
        self.consent.blockSignals(True)
        self.consent.setChecked(False)
        self.consent.blockSignals(False)
        self.preview.clear()

    def invalidate(self):
        self._handoff_lease = None
        self._reset_consent()
        self.folders.clear()
        for label in self.folder_labels.values():
            label.setText('미선택')
        self.status.setText('작품이 변경되어 이전 작가 기록/승인이 해제되었습니다.')

    def choose_folder(self, key: str):
        selected = QFileDialog.getExistingDirectory(self, '기존 작가 기록 폴더 직접 선택')
        if selected:
            self._handoff_lease = None
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

    def accept_existing_scene_folder(
        self, folder: Path, episode: int, scene_count: int, identity: tuple,
    ) -> None:
        """작가가 별도 클릭으로 선택한 기존 저장 장면 기록만 문맥 폴더에 연결."""
        session = self.authoring.session
        store, project_id = session.required()
        current = (str(session.path), str(project_id))
        if (type(identity) is not tuple or identity != current
                or type(episode) is not int or not 1 <= episode <= 1000
                or type(scene_count) is not int or not 1 <= scene_count <= 20):
            raise AuthorScenePlanError('작품 또는 장면 범위가 변경됐습니다.')
        path = Path(folder)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise AuthorScenePlanError('작가가 직접 선택한 로컬 기록 폴더가 필요합니다.')
        plans = tuple(
            plan for plan in read_author_scene_plans(path, str(project_id))
            if plan.episode == episode and not plan.revoked)
        if len(plans) != 1 or len(plans[0].beats) != scene_count:
            raise AuthorScenePlanError(
                '현재 회차의 활성 저장 장면 계획이 하나이고 장면 수가 일치해야 합니다.')
        scene_plan_fingerprint(path)
        self._handoff_lease = None
        self._reset_consent()
        self.episode.setValue(episode)
        self.scenes.setValue(scene_count)
        self.folders['scene'] = path
        self.folder_labels['scene'].setText(
            '기존 저장 장면 계획에서 직접 선택됨 · 현재 지문 재확인 필요')
        self.status.setText(
            f'{episode}화의 기존 저장 장면 {scene_count}개 폴더만 선택했습니다. '
            '작가 통합 문맥 미리보기와 배치 1회 사용 동의는 별도 클릭해야 합니다. '
            'AI 실행·원고 저장·출판은 하지 않았습니다.')

    def _capture(self) -> AuthorContextSources:
        store, project_id = self.authoring.session.required()
        lease = self._handoff_lease
        if lease is not None:
            if self.episode.value() != lease.episode or self.scenes.value() != lease.scene_count:
                raise ContinuityContextHandoffError('문맥 인계 회차·장면 수가 변경됐습니다.')
            require_current_continuity_context(lease, store, str(project_id))
        return capture_author_context_sources(
            store, str(project_id), arc_folder=self.folders.get('arc'),
            scene_folder=self.folders.get('scene'), fact_folder=self.folders.get('fact'),
            language_folder=self.folders.get('language'),
            memory_folder=self.folders.get('memory'))

    def accept_existing_continuity_sources(self, lease: ContinuityContextLease) -> None:
        """기존 연속성 화면의 두 번째 클릭에서만 5종 폴더를 선택한다."""
        store, project_id = self.authoring.session.required()
        require_current_continuity_context(lease, store, str(project_id))
        self._handoff_lease = None
        self._reset_consent()
        self.episode.setValue(lease.episode)
        self.scenes.setValue(lease.scene_count)
        names = ('arc', 'scene', 'fact', 'language', 'memory')
        self.folders = dict(zip(names, (Path(p) for p in lease.coverage.folders)))
        for key in names:
            self.folder_labels[key].setText('작가가 연속성 화면에서 직접 선택함 · 재확인 필요')
        self._handoff_lease = lease
        self.status.setText(
            '5종 기록 폴더와 회차만 인계했습니다. 문맥 미리보기와 '
            'AI 배치 문맥 1회 사용 동의는 별도 직접 클릭하세요.')

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
