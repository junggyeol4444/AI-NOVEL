"""Windows PySide6 manual evidence file selector and structured finding view."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFileDialog, QCheckBox,
)
from ai_novel_factory.reader_simulation import (
    ReaderSimulationError, annotate_saved_reader_scenes, simulate_reader_profiles,
)
from ai_novel_factory.reader_simulation_records import ReaderSimulationStore
from .author_navigation_contract import _busy, _unsaved
from ai_novel_factory.evidence_review_workflow import (
    plan_evidence_review, review_saved_evidence, write_empty_evidence_manifest,
    EvidenceReviewWorkflowError,
)


class EvidenceReviewPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('회차 원고 근거 · 인물 지식·복선·시간선·세계관', parent)
        self.authoring = authoring
        self._expected = None
        self._bound = None
        root = QVBoxLayout(self)
        notice = QLabel('작가가 직접 표시한 근거만 확인합니다. 표시하지 않은 문장과 문학 품질은 '
                        '검증되지 않으며, 자동 합격·출판 승인은 없습니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.source = QComboBox()
        self.source.addItem('저장된 최종본', 'final')
        self.source.addItem('저장된 초고', 'draft')
        self.source.setObjectName('evidenceReviewSource')
        root.addWidget(self.source)
        self.manifest = QLineEdit()
        self.manifest.setReadOnly(True)
        self.manifest.setObjectName('evidenceManifestFile')
        row = QHBoxLayout()
        row.addWidget(self.manifest)
        choose = QPushButton('작가 근거 JSON 선택')
        choose.setObjectName('evidenceChooseManifest')
        choose.clicked.connect(self.choose_manifest)
        row.addWidget(choose)
        root.addLayout(row)
        template = QPushButton('빈 근거 JSON 템플릿 새 파일 저장 (기존 파일 보존)')
        template.setObjectName('evidenceCreateTemplate')
        template.clicked.connect(self.create_template)
        root.addWidget(template)
        self.inspect = QPushButton('현재 원고 근거 확인 (명시적 실행)')
        self.inspect.setObjectName('evidenceInspectSaved')
        self.inspect.clicked.connect(self.inspect_evidence)
        root.addWidget(self.inspect)
        self.status = QLabel('원고·근거 미선택: NOT_EXAMINED')
        self.status.setObjectName('evidenceReviewStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.source.currentIndexChanged.connect(self.invalidate)

        # Stage 79 — only manually annotated observations, not simulated people.
        self._reader_snapshot = None
        self._reader_scenes = ()
        self._reader_marks = {}
        self._reader_draft = ''
        self._reader_report = None
        self._reader_annotations = ()
        reader_notice = QLabel(
            '독자 관점 관찰: 작가가 각 장면 6개 속성을 직접 표시합니다. '
            '예/아니요는 작가 관찰치이며 실제 독자 반응·문학 품질·출판 승인 아님.')
        reader_notice.setWordWrap(True)
        root.addWidget(reader_notice)
        self.reader_load = QPushButton('현재 저장 초고·장면 읽기 전용으로 불러오기')
        self.reader_load.setObjectName('readerProxyLoadSavedScenes')
        self.reader_load.clicked.connect(self._reader_load)
        root.addWidget(self.reader_load)
        self.reader_scene = QComboBox()
        self.reader_scene.setObjectName('readerProxySelectedScene')
        root.addWidget(self.reader_scene)
        self.reader_controls = {}
        metrics = (
            ('goal_visible', '장면 목표 명확성'),
            ('tension_present', '갈등·긴장 표시'),
            ('development', '사건 진행'),
            ('character_choice', '인물 선택'),
            ('consequence', '행동의 결과'),
            ('closing_hook', '마지막 궁금증'),
        )
        for name, label in metrics:
            entry = QComboBox()
            entry.setObjectName('readerProxy_' + name)
            entry.addItem(label + ': 미확인', None)
            entry.addItem(label + ': 예', True)
            entry.addItem(label + ': 아니요', False)
            self.reader_controls[name] = entry
            root.addWidget(entry)
        self.reader_scene.currentIndexChanged.connect(self._reader_show_marks)
        self.reader_apply = QPushButton('선택 장면의 관찰표시만 반영 (SQLite 저장 없음)')
        self.reader_apply.setObjectName('readerProxyApplySceneMarks')
        self.reader_apply.clicked.connect(self._reader_apply_marks)
        root.addWidget(self.reader_apply)
        self.reader_preview = QPushButton('모든 저장 장면의 작가 관찰지표 계산 (승인 아님)')
        self.reader_preview.setObjectName('readerProxyPreview')
        self.reader_preview.clicked.connect(self._reader_preview)
        root.addWidget(self.reader_preview)
        self.reader_path = QLineEdit()
        self.reader_path.setObjectName('readerProxyNewFilePath')
        self.reader_path.setReadOnly(True)
        root.addWidget(self.reader_path)
        reader_choose = QPushButton('관찰 결과를 저장할 새 로컬 SQLite 파일 직접 선택')
        reader_choose.setObjectName('readerProxyChooseNewFile')
        reader_choose.clicked.connect(self._reader_choose_file)
        root.addWidget(reader_choose)
        self.reader_consent = QCheckBox(
            '이번 계산된 작가 관찰지표만 새 별도 SQLite 파일에 저장하는 1회를 승인')
        self.reader_consent.setObjectName('readerProxyExplicitConsent')
        root.addWidget(self.reader_consent)
        self.reader_save = QPushButton('작가 독자 관찰지표 수동 저장 (기존 파일 덮어쓰기 금지)')
        self.reader_save.setObjectName('readerProxyRecord')
        self.reader_save.clicked.connect(self._reader_save)
        root.addWidget(self.reader_save)
        self.reader_status = QLabel('장면 관찰 미실행 · NOT_RUN')
        self.reader_status.setObjectName('readerProxyStatus')
        self.reader_status.setWordWrap(True)
        root.addWidget(self.reader_status)
        for control in self.reader_controls.values():
            control.currentIndexChanged.connect(
                lambda _index: self.reader_consent.setChecked(False))
        self.source.currentIndexChanged.connect(self._reader_reset)

    def invalidate(self, *_args):
        self._expected = None
        self._bound = None
        self.status.setText('현재 원고·근거를 다시 선택해야 합니다. NOT_EXAMINED')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None or not session.episode_number:
            raise EvidenceReviewWorkflowError('먼저 로컬 작품과 회차를 선택하세요.')
        return session, session.project_id, session.episode_number

    def choose_manifest(self):
        filename, _ = QFileDialog.getOpenFileName(self, '기존 로컬 근거 JSON', '', 'JSON (*.json)')
        if filename:
            self.manifest.setText(filename)
            self.invalidate()

    def create_template(self):
        filename, _ = QFileDialog.getSaveFileName(self, '새 근거 JSON 템플릿', '', 'JSON (*.json)')
        if not filename:
            return
        try:
            session, project, episode = self._current()
            write_empty_evidence_manifest(
                session.store, project, episode, source=self.source.currentData(),
                destination=filename)
        except (ValueError, OSError):
            self.status.setText('근거 템플릿 저장 실패. 기존 파일은 덮어쓰지 않습니다.')
            return
        self.manifest.setText(filename)
        self.invalidate()
        self.status.setText('빈 근거 템플릿 생성. 작가가 근거 위치를 입력해야 합니다. 자동 합격 아님.')

    def inspect_evidence(self):
        self.invalidate()
        try:
            session, project, episode = self._current()
            source = self.source.currentData()
            plan = plan_evidence_review(session.store, project, episode, source=source)
            result = review_saved_evidence(
                session.store, session.path, project, episode, source=source,
                manifest_path=self.manifest.text(), expected=plan)
        except (ValueError, OSError):
            self.status.setText('근거 확인 불가 또는 변경 감지. 검사 합격으로 기록하지 않았습니다.')
            return
        self._expected = plan
        self._bound = (project, episode, source)
        labels = {'continuity': '설정', 'character_knowledge': '인물 지식',
                  'foreshadowing': '복선', 'timeline': '시간선'}
        lines = []
        for item in result.sections:
            lines.append(f'{labels.get(item.category, item.category)}: '
                         f'표시 {item.examined}건 / 발견 {item.findings}건 / {item.status}')
        self.status.setText('\n'.join(lines) + '\n표시한 범위만 확인됨 · '
                            '원고 전체 검사/출판 승인 아님 · 사람 검수 필수')


    def _reader_reset(self, *_args):
        self._reader_snapshot = None
        self._reader_scenes = ()
        self._reader_marks = {}
        self._reader_draft = ''
        self._reader_report = None
        self._reader_annotations = ()
        self.reader_scene.clear()
        self.reader_consent.setChecked(False)
        self.reader_status.setText('작품·원고·장면 변경 시 관찰을 다시 시작하세요. NOT_RUN')

    def _reader_fresh(self):
        session, project, episode = self._current()
        if (_busy(self.authoring) or _unsaved(self.authoring)
                or session.path is None or self._reader_snapshot is None):
            raise ReaderSimulationError('집필 실행 중이거나 미저장 원고가 있습니다.')
        current = session.store.get_episode(project, episode)
        rows = tuple(sorted(
            session.store.list_scenes(project, episode), key=lambda row: row.position))
        identity = (str(session.path), str(project), episode)
        digest = sha256(current.draft.encode('utf-8')).hexdigest()
        scene_digest = tuple(
            (item.position, sha256(item.text.encode('utf-8')).hexdigest())
            for item in rows)
        if ((identity, current.revision, digest, scene_digest)
                != self._reader_snapshot):
            raise ReaderSimulationError('원고·장면·작품 또는 revision이 변경됐습니다.')
        if current.draft != self._reader_draft or tuple(
                item.text for item in rows) != self._reader_scenes:
            raise ReaderSimulationError('저장 장면이 수정됐습니다.')
        return session, project, episode

    def _reader_load(self):
        self._reader_reset()
        try:
            session, project, episode = self._current()
            if _busy(self.authoring) or _unsaved(self.authoring) or session.path is None:
                raise ReaderSimulationError('미저장 원고 또는 모델/배치 실행이 있습니다.')
            saved = session.store.get_episode(project, episode)
            rows = tuple(sorted(session.store.list_scenes(project, episode),
                                key=lambda row: row.position))
            if (not saved.draft.strip() or not 1 <= len(rows) <= 100
                    or tuple(row.position for row in rows) != tuple(
                        range(1, len(rows) + 1))):
                raise ReaderSimulationError('저장 초고·연속된 장면 자료가 필요합니다.')
            contents = tuple(row.text for row in rows)
            if saved.draft != '\n\n'.join(contents):
                raise ReaderSimulationError(
                    '저장 초고와 장면 원문이 다릅니다. 임의로 병합하지 않습니다.')
            self._reader_draft = saved.draft
            self._reader_scenes = contents
            self._reader_snapshot = (
                (str(session.path), str(project), episode),
                saved.revision, sha256(saved.draft.encode('utf-8')).hexdigest(),
                tuple((row.position, sha256(row.text.encode('utf-8')).hexdigest())
                      for row in rows))
            self._reader_marks = {index: {
                key: None for key in self.reader_controls}
                for index in range(1, len(contents) + 1)}
            for index in range(1, len(contents) + 1):
                self.reader_scene.addItem(f'{index}장면 · 저장 원문', index)
            self._reader_show_marks()
            self.reader_status.setText(
                f'{episode}화 저장 초고의 {len(contents)}개 장면을 불러왔습니다. '
                '장면마다 작가 관찰 항목을 직접 표시하세요. 품질 판정 아님.')
        except (ReaderSimulationError, ValueError, OSError):
            self._reader_reset()
            self.reader_status.setText(
                '저장 초고·장면이 없거나 상태가 변경됐습니다. 원고 변경 없이 중단.')

    def _reader_show_marks(self, *_args):
        number = self.reader_scene.currentData()
        values = self._reader_marks.get(number, {})
        for key, control in self.reader_controls.items():
            wanted = values.get(key)
            control.blockSignals(True)
            control.setCurrentIndex(0 if wanted is None else 1 if wanted else 2)
            control.blockSignals(False)

    def _reader_apply_marks(self):
        number = self.reader_scene.currentData()
        try:
            self._reader_fresh()
            if type(number) is not int or number not in self._reader_marks:
                raise ReaderSimulationError('현재 저장 장면을 선택하세요.')
            self._reader_marks[number] = {
                key: control.currentData()
                for key, control in self.reader_controls.items()}
        except (ReaderSimulationError, ValueError, OSError):
            self._reader_reset()
            self.reader_status.setText('이전 관찰의 원고·장면 지문이 변경됐습니다. 다시 불러오세요.')
            return
        self._reader_report = None
        self._reader_annotations = ()
        self.reader_consent.setChecked(False)
        self.reader_status.setText(
            f'{number}장면의 작가 관찰표시를 이번 화면에서만 보관했습니다. '
            '다른 장면도 표시한 후 전체 관찰지표를 계산하세요.')

    def _reader_inputs(self):
        session, project, episode = self._reader_fresh()
        number = self.reader_scene.currentData()
        if number in self._reader_marks:
            selected = self._reader_marks[number]
            if any(control.currentData() is not selected[key]
                   for key, control in self.reader_controls.items()):
                raise ReaderSimulationError(
                    '현재 장면의 변경 사항을 먼저 명시적으로 반영하세요.')
        marks = tuple(self._reader_marks[index]
                      for index in range(1, len(self._reader_scenes) + 1))
        annotations = annotate_saved_reader_scenes(
            self._reader_draft, self._reader_scenes, marks)
        report = simulate_reader_profiles(
            project, episode, self._reader_draft, scenes=annotations)
        return session, report, annotations

    def _reader_preview(self):
        try:
            _, report, annotations = self._reader_inputs()
        except (ReaderSimulationError, ValueError, OSError):
            self._reader_reset()
            self.reader_status.setText(
                '저장 원고·장면·미반영 관찰이 변경돼 전체 계산을 취소했습니다.')
            return
        self._reader_report = report
        self._reader_annotations = annotations
        self.reader_consent.setChecked(False)
        summaries = ', '.join(
            f'{metric.dimension}: '
            + (str(metric.score) if metric.score is not None else '미확인')
            for metric in report.metrics)
        self.reader_status.setText(
            '작가 수동 관찰지표 (실제 독자 평가 아님): ' + summaries +
            f' · 누락 관찰 {len(report.unexamined)}영역. '
            '문학적 품질·QC PASS·출판 승인 아님.')

    def _reader_choose_file(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, '작가 관찰지표 새 SQLite 파일', '', 'SQLite (*.sqlite)')
        if not filename:
            return
        target = Path(filename)
        if (not target.is_absolute() or target.is_symlink()
                or target.exists() or not target.parent.is_dir()):
            self.reader_status.setText('기존 파일을 덮어쓸 수 없습니다. 새 파일명을 고르세요.')
            return
        self.reader_path.setText(str(target))
        self.reader_consent.setChecked(False)

    def _reader_save(self):
        approval = self.reader_consent.isChecked()
        self.reader_consent.setChecked(False)
        if not approval or self._reader_report is None:
            self.reader_status.setText('현재 계산 결과와 별도 1회 저장 승인이 필요합니다.')
            return
        target = Path(self.reader_path.text())
        try:
            if (not target.is_absolute() or target.is_symlink()
                    or target.exists() or not target.parent.is_dir()):
                raise ReaderSimulationError('기존 파일 덮어쓰기 금지')
            _, report, annotations = self._reader_inputs()
            if (report != self._reader_report or
                    annotations != self._reader_annotations):
                raise ReaderSimulationError('관찰 표시 또는 원고가 변경됐습니다.')
            with ReaderSimulationStore(target) as records:
                records.record(report, draft=self._reader_draft, scenes=annotations)
        except (ReaderSimulationError, ValueError, OSError):
            self._reader_report = None
            self.reader_status.setText(
                '선택 원고·관찰값이 변경됐거나 별도 기록 실패. 기존 파일 변경 없음.')
            return
        self._reader_report = None
        self.reader_status.setText(
            '별도 로컬 SQLite 새 파일에 관찰지표만 저장했습니다. '
            '원문 미저장·품질 합격 아님·출판 승인 아님.')
