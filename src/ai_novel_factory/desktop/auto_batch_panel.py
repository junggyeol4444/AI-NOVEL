"""UI for an explicitly approved real-model batch drafting run.

Runs on a worker thread, one saved episode at a time; cancellation is cooperative
at model call boundaries. This is NOT a full quality-approved/publication engine.
"""
from __future__ import annotations

from pathlib import Path
import shlex
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout,
)
from ai_novel_factory.auto_novel_run import run_auto_novel
from ai_novel_factory.local_models import LocalExecutableProvider


class AutoBatchWorker(QThread):
    progress_changed = Signal(int, str)
    finished_report = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, project_id, provider, target, chars,
                 scenes, parent=None):
        super().__init__(parent)
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.provider = provider
        self.target = target
        self.chars = chars
        self.scenes = scenes
        self.stop_requested = Event()

    def run(self):
        try:
            result = run_auto_novel(
                self.database_path, self.project_id, self.provider,
                through_episode=self.target, target_chars=self.chars,
                scenes_per_episode=self.scenes,
                progress=lambda n, step: self.progress_changed.emit(n, step),
                should_stop=self.stop_requested.is_set)
            self.finished_report.emit(result)
        except (ValueError, OSError) as exc:
            self.failed.emit(str(exc)[:160])
        except BaseException as exc:
            self.failed.emit('자동 집필이 중단되었습니다. 분류: ' + type(exc).__name__)


class AutoBatchPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('6. 여러 회차 로컬 AI 집필 (검토 전 초고)', parent)
        self.authoring = authoring
        self.worker = None
        root = QVBoxLayout(self)
        notice = QLabel(
            '작품의 장르·소재·분위기·목표 회차를 먼저 저장하세요. '
            '실제 로컬 실행형 AI로 회차 플롯과 장면 초고를 생성합니다. '
            '기존 회차는 덮어쓰지 않습니다. '
            '검사 근거가 불충분한 초고는 수동 검수 대기이며 확정·게시되지 않습니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        form = QFormLayout()
        root.addLayout(form)
        self.through = QSpinBox()
        self.through.setObjectName('autoBatchThroughEpisode')
        self.through.setRange(1, 1000)
        self.through.setValue(2)
        form.addRow('생성할 마지막 회차', self.through)
        self.target_chars = QSpinBox()
        self.target_chars.setObjectName('autoBatchTargetChars')
        self.target_chars.setRange(50, 50000)
        self.target_chars.setValue(5000)
        form.addRow('회차별 목표 글자 수', self.target_chars)
        self.scenes = QSpinBox()
        self.scenes.setObjectName('autoBatchScenes')
        self.scenes.setRange(1, 20)
        self.scenes.setValue(3)
        form.addRow('회차별 장면 수', self.scenes)
        self.consent = QCheckBox(
            '이번 실행에서만 지정한 로컬 모델로 순차 집필하는 것을 승인합니다')
        self.consent.setObjectName('autoBatchExplicitApproval')
        root.addWidget(self.consent)
        self.start_button = QPushButton('로컬 AI 여러 회차 집필 시작')
        self.start_button.setObjectName('autoBatchStart')
        self.stop_button = QPushButton('현재 장면 완료 후 중단')
        self.stop_button.setObjectName('autoBatchStop')
        self.stop_button.setEnabled(False)
        root.addWidget(self.start_button)
        root.addWidget(self.stop_button)
        self.status = QLabel('대기: 모델 실행 파일/인수를 위에서 지정하세요.')
        self.status.setWordWrap(True)
        self.status.setObjectName('autoBatchStatus')
        root.addWidget(self.status)
        self.start_button.clicked.connect(self.start_batch)
        self.stop_button.clicked.connect(self.request_stop)

    def refresh_defaults(self):
        if self.is_running():
            return
        for key, spin in (('target_episodes', self.through),
                          ('characters_per_episode', self.target_chars)):
            value = self.authoring._text(key).strip()
            if value.isdecimal() and spin.minimum() <= int(value) <= spin.maximum():
                spin.setValue(int(value))

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def request_stop(self):
        if self.is_running():
            self.worker.stop_requested.set()
            self.status.setText('중단 요청: 실행 중인 로컬 모델 호출이 완료되면 중단합니다.')

    def start_batch(self):
        if self.is_running():
            return
        session = self.authoring.session
        if session.project_id is None or session.path is None:
            self.status.setText('작품 메뉴에서 먼저 작품을 생성하거나 열어 주세요.')
            return
        if not self.consent.isChecked():
            self.status.setText('실제 로컬 AI 연속 실행에 대한 이번 회차 승인이 필요합니다.')
            return
        self.consent.setChecked(False)
        try:
            executable = self.authoring._text('executable').strip()
            arguments = tuple(shlex.split(self.authoring._text('arguments')))
            provider = LocalExecutableProvider(
                executable, arguments=arguments,
                timeout_seconds=(
                    1500 if (Path(executable).name.casefold() == 'anf_local_model.exe'
                             and arguments[:1] == ('--gguf',))
                    else 450 if arguments[:1] == ('--gguf',) else 120),
                explicitly_allowed=True)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc)[:160])
            return
        self.worker = AutoBatchWorker(
            str(session.path), str(session.project_id), provider,
            self.through.value(), self.target_chars.value(), self.scenes.value(),
            self)
        self.worker.progress_changed.connect(
            lambda num, stage: self.status.setText(f'{num}화: {stage}'))
        self.worker.finished_report.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._cleanup)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText('로컬 모델 연속 집필 시작. 저장된 회차는 건너뜁니다.')
        self.worker.start()

    def _finished(self, result):
        self.status.setText(
            f'작업 완료: 새 회차 {len(result.created_episodes)}개, '
            f'이미 존재하는 회차 {len(result.skipped_existing)}개, '
            f'로컬 AI 실행 {result.local_model_invocations}회. '
            f'검수 필수 {len(result.review_required_episodes)}개. '
            + ('중단 요청 반영됨.' if result.stopped else '비공개 초고만 저장됨.'))
        # Keep existing form edits untouched, but show the newly generated
        # saved episodes in the selector immediately. Preserve selection.
        session = self.authoring.session
        if (session.store is not None and session.project_id is not None
                and self.worker is not None
                and str(session.path) == str(self.worker.database_path)
                and str(session.project_id) == self.worker.project_id):
            selector = self.authoring.episodes
            selected = selector.currentData()
            selector.blockSignals(True)
            try:
                selector.clear()
                for episode in session.store.list_episodes(session.project_id):
                    selector.addItem(str(episode.episode) + '화', episode.episode)
                index = selector.findData(selected)
                selector.setCurrentIndex(index if index >= 0 else -1)
            finally:
                selector.blockSignals(False)

    def _failed(self, message):
        self.status.setText('집필 실패/보류: ' + message)

    def _cleanup(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
