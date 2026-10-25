"""PySide6 desktop: author-only, append-only story-arc planning."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QSpinBox, QPushButton, QCheckBox, QFileDialog,
    QListWidget, QTableWidget, QTableWidgetItem)
from ..author_arc_ledger import (AuthorArcError, add_author_arc,
                                 read_author_arcs, withdraw_author_arc)
from ..author_ai_planning import (
    AuthorAiPlanningError, require_current_author_ai_planning_source,
)
from ..author_full_plan_preview import (
    AuthorFullPlanError, build_author_full_plan,
    require_current_author_full_plan, author_full_plan_scenes,
)
from ..project_local_handoff import require_idle_authoring, LocalHandoffError
from ..author_arc_final_coverage import (
    AuthorArcFinalCoverageError, build_author_arc_final_coverage,
    require_current_author_arc_final_coverage,
    read_author_arc_episode_evidence,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode, _busy, _unsaved

class AuthorArcPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 장편 아크 계획 · 로컬 전용', parent)
        self.authoring = authoring
        self._folder = None
        self._bound = None
        self._coverage_snapshot = None
        self._coverage_identity = None
        self._full_plan = None
        self._full_plan_identity = None
        form = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(form)
        plan_group = QGroupBox('저장 작품 설정 기반 장편 1~1000화 기획 뼈대 · 읽기 전용')
        plan_root = QVBoxLayout(plan_group)
        plan_form = QFormLayout()
        self.full_through = QSpinBox()
        self.full_through.setRange(1, 1000)
        self.full_through.setValue(30)
        self.full_through.setObjectName('authorFullPlanThrough')
        self.full_arc_count = QSpinBox()
        self.full_arc_count.setRange(0, 1000)
        self.full_arc_count.setSpecialValueText('자동 (30화당 약 1개)')
        self.full_arc_count.setObjectName('authorFullPlanArcCount')
        self.full_scene_count = QSpinBox()
        self.full_scene_count.setRange(1, 20)
        self.full_scene_count.setValue(3)
        plan_form.addRow('기획 조회 회차', self.full_through)
        plan_form.addRow('전체 아크 수', self.full_arc_count)
        plan_form.addRow('회차당 장면 빈 칸', self.full_scene_count)
        plan_root.addLayout(plan_form)
        full_preview_button = QPushButton('현재 저장 설정으로 전체 아크·회차 기획 빈 칸 조회')
        full_preview_button.setObjectName('authorFullPlanPreview')
        full_preview_button.clicked.connect(self.preview_full_plan)
        plan_root.addWidget(full_preview_button)
        self.full_arc_table = QTableWidget(0, 3)
        self.full_arc_table.setObjectName('authorFullPlanArcTable')
        self.full_arc_table.setHorizontalHeaderLabels(('아크', '회차 범위', '이 범위에 포함된 회차'))
        self.full_arc_table.setMaximumHeight(180)
        self.full_arc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        plan_root.addWidget(self.full_arc_table)
        self.full_episode = QSpinBox()
        self.full_episode.setRange(1, 1000)
        plan_form.addRow('기획 빈 칸을 볼 회차', self.full_episode)
        self.full_scene_preview = QPlainTextEdit()
        self.full_scene_preview.setReadOnly(True)
        self.full_scene_preview.setMaximumHeight(135)
        self.full_scene_preview.setObjectName('authorFullPlanScenePreview')
        plan_root.addWidget(self.full_scene_preview)
        self.full_plan_status = QLabel(
            '현재 저장된 작품의 장르·소재·목표 회차·분위기를 사용합니다. '
            'AI 줄거리 생성/참고작 전수/원고 저장/검수 합격 아님.')
        self.full_plan_status.setWordWrap(True)
        plan_root.addWidget(self.full_plan_status)
        fill_arc = QPushButton('선택 아크를 아래 수동 편집 입력칸에 가져오기 (저장 안 함)')
        fill_arc.setObjectName('authorFullPlanFillArc')
        fill_arc.clicked.connect(self.prefill_full_plan_arc)
        plan_root.addWidget(fill_arc)
        handoff_scene = QPushButton('현재 회차 계획을 기존 장면 설계표로 넘기기 (자동 저장 없음)')
        handoff_scene.setObjectName('authorFullPlanToSceneEditor')
        handoff_scene.clicked.connect(self.handoff_full_plan_scene)
        plan_root.addWidget(handoff_scene)
        root.addWidget(plan_group)
        for spin in (self.full_through, self.full_arc_count, self.full_scene_count):
            spin.valueChanged.connect(self.invalidate_full_plan)
        self.full_episode.valueChanged.connect(self.show_full_plan_episode)
        self.full_arc_table.itemSelectionChanged.connect(self.show_full_plan_episode)
        self.folder_label = QLabel('로컬 계획 폴더 미선택')
        self.folder_label.setWordWrap(True)
        choose = QPushButton('기존 아크 기록 폴더 직접 선택')
        choose.clicked.connect(self.choose_folder)
        form.addRow(choose)
        form.addRow(self.folder_label)
        self.start = QSpinBox(); self.start.setRange(1, 1000)
        self.end = QSpinBox(); self.end.setRange(1, 1000); self.end.setValue(30)
        form.addRow('시작 회차', self.start); form.addRow('종료 회차', self.end)
        self.title_input = QLineEdit()
        form.addRow('아크 제목', self.title_input)
        self.fields = {}
        for key, label in [('objective','장편 목표'),('conflict','주요 갈등'),
                           ('foreshadow','복선 계획'),('resolution','해소 계획')]:
            edit=QPlainTextEdit();edit.setMaximumHeight(66)
            self.fields[key]=edit;form.addRow(label,edit)
        self.preview = QListWidget();self.preview.setMaximumHeight(130)
        root.addWidget(self.preview)
        self.coverage_through = QSpinBox()
        self.coverage_through.setRange(1, 1000)
        self.coverage_through.setValue(30)
        form.addRow('최종본 대조 종료 회차', self.coverage_through)
        self.coverage_episode = QSpinBox()
        self.coverage_episode.setRange(1, 1000)
        form.addRow('아크 안에서 직접 열 회차', self.coverage_episode)
        coverage_button = QPushButton('기존 아크·저장 최종본 복선·해소 범위 직접 대조')
        coverage_button.setObjectName('authorArcFinalCoveragePreview')
        coverage_button.clicked.connect(self.preview_saved_arc_coverage)
        root.addWidget(coverage_button)
        self.coverage_table = QTableWidget(0, 8)
        self.coverage_table.setObjectName('authorArcFinalCoverageTable')
        self.coverage_table.setHorizontalHeaderLabels((
            '작가 아크', '회차 범위', '저장 최종본', '누락 회차',
            '복선 문자열 회차', '해소 문자열 회차', '설정 변경', '순서 검토 후보'))
        self.coverage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.coverage_table.setMaximumHeight(230)
        root.addWidget(self.coverage_table)
        self.coverage_status = QLabel('NOT_RUN: 작가가 기존 아크 폴더를 선택한 뒤 직접 조회하세요.')
        self.coverage_status.setWordWrap(True)
        root.addWidget(self.coverage_status)
        self.coverage_open = QPushButton('선택 아크·직접 지정 회차를 기존 편집기로 열기 (별도 클릭)')
        self.coverage_open.setObjectName('authorArcFinalCoverageOpen')
        self.coverage_open.setEnabled(False)
        self.coverage_open.clicked.connect(self.open_saved_arc_coverage)
        root.addWidget(self.coverage_open)
        self.coverage_detail_button = QPushButton('선택 아크·회차의 저장 최종본 복선·해소 근거 읽기 (별도 클릭)')
        self.coverage_detail_button.setObjectName('authorArcEpisodeEvidenceOpen')
        self.coverage_detail_button.setEnabled(False)
        self.coverage_detail_button.clicked.connect(self.show_saved_arc_episode_evidence)
        root.addWidget(self.coverage_detail_button)
        self.coverage_detail_status = QLabel('선택 회차의 원문 근거는 별도 작가 클릭 후에만 표시합니다.')
        self.coverage_detail_status.setWordWrap(True)
        root.addWidget(self.coverage_detail_status)
        self.coverage_detail_text = QPlainTextEdit()
        self.coverage_detail_text.setObjectName('authorArcEpisodeEvidenceText')
        self.coverage_detail_text.setReadOnly(True)
        self.coverage_detail_text.setMaximumHeight(260)
        root.addWidget(self.coverage_detail_text)
        self.coverage_episode.valueChanged.connect(self.clear_coverage_detail)
        self.coverage_table.itemSelectionChanged.connect(self.clear_coverage_detail)
        self.coverage_through.valueChanged.connect(self.invalidate_coverage)
        self.save_consent = QCheckBox('위 내용을 이번 한 번 새 로컬 기록으로 저장하는 데 동의')
        self.withdraw_consent = QCheckBox('선택한 아크 기록을 이번 한 번 철회하는 데 동의')
        root.addWidget(self.save_consent);root.addWidget(self.withdraw_consent)
        self.batch_approval = QCheckBox('이번 AI 집필 한 번에만 현재 작가 아크 계획을 사용합니다')
        root.addWidget(self.batch_approval)
        self._batch_project = None
        self._batch_stamp = None
        self.batch_approval.toggled.connect(self._bind_batch)
        save = QPushButton('새 아크 기록 저장');save.clicked.connect(self.save_arc)
        remove = QPushButton('선택한 아크 철회');remove.clicked.connect(self.withdraw_arc)
        refresh=QPushButton('현재 아크 목록 읽기');refresh.clicked.connect(self.refresh)
        root.addWidget(save);root.addWidget(remove);root.addWidget(refresh)
        self.status=QLabel('저장·철회는 작가가 직접 누른 때에만 별도 JSON으로 기록합니다.')
        self.status.setWordWrap(True);root.addWidget(self.status)
        for obj in (self.start,self.end):obj.valueChanged.connect(self._revoke_save)
        self.title_input.textChanged.connect(self._revoke_save)
        for obj in self.fields.values():obj.textChanged.connect(self._revoke_save)

    def _revoke_save(self, *args):
        self.save_consent.setChecked(False)

    def invalidate(self):
        self.invalidate_full_plan()
        self.invalidate_coverage()
        self.save_consent.setChecked(False);self.withdraw_consent.setChecked(False)
        self.batch_approval.setChecked(False)
        self.preview.clear();self._bound=None
        self.status.setText('작품이 변경되어 아크 승인과 목록을 초기화했습니다.')

    def invalidate_full_plan(self, *_args):
        self._full_plan = None
        self._full_plan_identity = None
        self.full_arc_table.setRowCount(0)
        self.full_scene_preview.clear()
        self.full_plan_status.setText(
            '작품·기획 입력 또는 조회 범위가 변경됐습니다. 저장 설정을 다시 조회하세요.')

    def preview_full_plan(self):
        self.invalidate_full_plan()
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            snapshot = build_author_full_plan(
                session.store, str(session.project_id),
                through_episode=self.full_through.value(),
                arc_option=self.full_arc_count.value(),
                scene_count=self.full_scene_count.value())
        except (AuthorFullPlanError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.full_plan_status.setText(
                '저장된 작품 설정·원고의 현재 상태가 올바르지 않습니다. '
                '장르·소재·분위기·목표 회차 및 미저장 편집을 확인하세요.')
            return
        self._full_plan, self._full_plan_identity = snapshot, identity
        self.full_arc_table.setRowCount(len(snapshot.arcs))
        for i, arc in enumerate(snapshot.arcs):
            visible_end = min(arc.end_episode, snapshot.through_episode)
            for col, value in enumerate((
                    str(arc.number),
                    f'{arc.start_episode}~{arc.end_episode}화',
                    str(visible_end - arc.start_episode + 1))):
                self.full_arc_table.setItem(i, col, QTableWidgetItem(value))
        self.full_episode.setMaximum(snapshot.through_episode)
        self.full_episode.setValue(1)
        self.full_plan_status.setText(
            f'저장 목표 {snapshot.total_episodes}화 중 {snapshot.through_episode}화 · '
            f'아크 {len(snapshot.arcs)}개 · 회차 기획 {len(snapshot.episodes)}개 · '
            f'회차당 장면 {snapshot.scene_count}칸. '
            '기존 기획 모듈의 빈 칸일 뿐 실제 AI 기획·집필·저장은 하지 않았습니다.')
        self.show_full_plan_episode()

    def show_full_plan_episode(self, *_args):
        snapshot = self._full_plan
        if snapshot is None:
            self.full_scene_preview.clear()
            return
        number = self.full_episode.value()
        if not 1 <= number <= snapshot.through_episode:
            self.full_scene_preview.clear()
            return
        ep = snapshot.episodes[number - 1]
        try:
            slots = author_full_plan_scenes(snapshot, number)
        except AuthorFullPlanError:
            self.full_scene_preview.clear()
            return
        lines = [
            f'{number}화 / 아크 {ep.arc_number} · 기획 빈 칸',
            f'목표: {ep.goal}',
            '아직 확정된 사건·인물·복선·결말 없음 (작가가 직접 작성해야 함)',
        ]
        lines.extend(f'장면 {slot.scene_number}: 목표·장소·갈등을 직접 입력'
                     for slot in slots)
        self.full_scene_preview.setPlainText('\n'.join(lines))

    def prefill_full_plan_arc(self):
        snapshot, identity = self._full_plan, self._full_plan_identity
        row = self.full_arc_table.currentRow()
        if (snapshot is None or identity is None or
                not 0 <= row < len(snapshot.arcs)):
            self.full_plan_status.setText('기존 아크 목록에서 가져올 아크를 선택하세요.')
            return
        if (self.title_input.text().strip()
                or any(widget.toPlainText().strip()
                       for widget in self.fields.values())):
            self.full_plan_status.setText(
                '아래 수동 편집칸에 이미 내용이 있습니다. '
                '기존 글을 덮어쓰지 않으므로 직접 정리한 뒤 다시 선택하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != current:
                raise AuthorFullPlanError('작품이 변경됐습니다.')
            require_current_author_full_plan(
                snapshot, session.store, str(session.project_id))
            arc = snapshot.arcs[row]
            if arc.end_episode > snapshot.through_episode:
                raise AuthorFullPlanError('아크 마지막 회차까지 조회 범위를 확장하세요.')
        except (AuthorFullPlanError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.invalidate_full_plan()
            self.full_plan_status.setText('작가 기획·원고가 변경됐습니다. 다시 조회하세요.')
            return
        self.start.setValue(arc.start_episode)
        self.end.setValue(arc.end_episode)
        self.title_input.setText(arc.label)
        self.fields['objective'].setPlainText(arc.objective)
        self.save_consent.setChecked(False)
        self.full_plan_status.setText(
            '현재 아크 범위만 수동 입력칸에 옮겼습니다. '
            '갈등·복선·해소 및 목표를 작가가 수정하고 '
            '별도 저장 승인을 눌러야 기록됩니다. SQLite/JSON 변경 없음.')

    def handoff_full_plan_scene(self):
        snapshot, identity = self._full_plan, self._full_plan_identity
        episode = self.full_episode.value()
        if snapshot is None or identity is None:
            self.full_plan_status.setText('전체 회차 기획을 먼저 직접 조회하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if current != identity:
                raise AuthorFullPlanError('작품이 변경됐습니다.')
            require_current_author_full_plan(
                snapshot, session.store, str(session.project_id))
            author_full_plan_scenes(snapshot, episode)
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'author_scene_plan_panel', project_identity=identity):
                raise AuthorFullPlanError('기존 장면 설계표를 열 수 없습니다.')
            panel = getattr(self.authoring, 'author_scene_plan_panel', None)
            if panel is None or not panel.accept_full_plan_selection(
                    snapshot, episode, identity):
                raise AuthorFullPlanError('기존 장면 입력칸에 미저장 내용이 있습니다.')
        except (AuthorFullPlanError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.full_plan_status.setText(
                '작품·원고·장면 편집 상태가 변경됐거나 기존 입력이 있습니다. '
                '자동 덮어쓰기 없이 종료했습니다.')
            return
        self.full_plan_status.setText(
            f'{episode}화와 장면 {snapshot.scene_count}개 선택을 기존 설계표에 전달했습니다. '
            '장면 목표·갈등·장소 입력 및 별도 저장은 작가가 직접 해야 합니다.')

    def accept_ai_planning_candidate(self, source, arc_number, values, identity):
        """기존 아크 기록은 건드리지 않고 작가의 수동 요약만 입력칸으로 받는다."""
        try:
            session, current = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != current:
                raise AuthorAiPlanningError('작품이 변경됐습니다.')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
            arc = next((item for item in source.planning.arcs
                        if item.number == arc_number), None)
            if (arc is None or arc.end_episode > source.planning.through_episode
                    or self._folder is None):
                raise AuthorAiPlanningError('완전한 아크 범위와 저장 폴더를 선택하세요.')
            if (type(values) is not tuple or len(values) != 5
                    or any(type(value) is not str or not value.strip()
                           or len(value) > maximum
                           or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
                           for value, maximum in zip(values, (100, 400, 400, 400, 400)))):
                raise AuthorAiPlanningError('작가가 수정한 아크 내용이 올바르지 않습니다.')
            if (self.title_input.text().strip()
                    or any(field.toPlainText().strip() for field in self.fields.values())):
                self.status.setText(
                    '기존 아크 수동 입력이 있으므로 자동 덮어쓰지 않습니다. '
                    '먼저 직접 저장하거나 입력을 정리하세요.')
                return False
            records = read_author_arcs(self._folder, str(session.project_id))
            if any(not row.withdrawn and arc.start_episode <= row.end
                   and row.start <= arc.end_episode for row in records):
                self.status.setText(
                    '이 구간에 이미 저장된 활성 작가 아크가 있습니다. 덮어쓰지 않습니다.')
                return False
            self.batch_approval.setChecked(False)
            self.save_consent.setChecked(False)
            self.withdraw_consent.setChecked(False)
            self.start.setValue(arc.start_episode)
            self.end.setValue(arc.end_episode)
            self.title_input.setText(values[0])
            for field, value in zip(('objective', 'conflict', 'foreshadow', 'resolution'),
                                    values[1:]):
                self.fields[field].setPlainText(value)
            self.save_consent.setChecked(False)
            self.status.setText(
                f'{arc.start_episode}~{arc.end_episode}화의 작가 수정 요약만 '
                '기존 입력칸에 전달했습니다. 실제 JSON 저장은 별도의 작가 1회 승인과 '
                '저장 버튼이 필요합니다. AI 제안은 검수/출판 승인 아님.')
            return True
        except (AuthorAiPlanningError, AuthorArcError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.status.setText(
                '현재 원고·기획·아크 기록이 변경되었거나 인계할 수 없습니다. '
                '기존 기록을 보존했습니다.')
            return False

    def _project(self):
        session=self.authoring.session
        db,pid=session.required()
        current=(str(session.path),str(pid))
        return db,str(pid),current

    def _bind_batch(self, enabled):
        self._batch_project = None
        self._batch_stamp = None
        if enabled:
            try:
                _, pid, bound = self._project()
                if self._folder is None:
                    raise AuthorArcError('기록 폴더 선택 필요')
                from ..author_arc_ledger import arc_ledger_fingerprint
                self._batch_project = bound
                self._batch_stamp = arc_ledger_fingerprint(self._folder)
            except (AuthorArcError, ValueError, OSError):
                self.batch_approval.setChecked(False)
                self.status.setText('작품·로컬 아크 기록 폴더를 먼저 확인하세요.')

    def consume_batch_folder(self) -> str | None:
        if not self.batch_approval.isChecked():
            return None
        try:
            _, _, bound = self._project()
            from ..author_arc_ledger import arc_ledger_fingerprint
            if (self._folder is None or self._batch_project != bound
                    or self._batch_stamp != arc_ledger_fingerprint(self._folder)):
                raise AuthorArcError('아크 기록이 변경되었습니다.')
            return str(self._folder)
        finally:
            self.batch_approval.setChecked(False)

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'작가 아크 JSON 기록용 기존 로컬 폴더')
        if path:
            self._folder=Path(path)
            self.folder_label.setText('기존 로컬 폴더 선택됨 (원고 SQLite와 별도)')
            self.invalidate()

    def refresh(self):
        self.invalidate_coverage()
        self.preview.clear();self.withdraw_consent.setChecked(False)
        try:
            _,pid,bound=self._project()
            if self._folder is None:raise AuthorArcError('폴더를 먼저 선택하세요.')
            arcs=read_author_arcs(self._folder,pid)
            for arc in arcs:
                status='철회' if arc.withdrawn else '작가 기록'
                self.preview.addItem(f'{arc.start}~{arc.end}화 · {arc.title} · {status}')
                self.preview.item(self.preview.count()-1).setData(256,arc.arc_id)
            self._bound=bound
            self.status.setText(f'작가 아크 기록 {len(arcs)}개 조회. 현재 품질 PASS·출판 승인 없음.')
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('현재 작품의 아크 기록을 읽을 수 없습니다.')

    def save_arc(self):
        approved=self.save_consent.isChecked();self.save_consent.setChecked(False)
        try:
            db,pid,_=self._project()
            if self._folder is None:raise AuthorArcError('기존 계획 폴더 선택 필요')
            add_author_arc(db,pid,folder=self._folder,start=self.start.value(),
                end=self.end.value(),title=self.title_input.text(),
                objective=self.fields['objective'].toPlainText(),
                conflict=self.fields['conflict'].toPlainText(),
                foreshadow=self.fields['foreshadow'].toPlainText(),
                resolution=self.fields['resolution'].toPlainText(),
                explicit_author_save=approved)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('아크를 저장하지 않았습니다. 회차 범위·승인·입력값을 확인하세요.')

    def withdraw_arc(self):
        approved=self.withdraw_consent.isChecked();self.withdraw_consent.setChecked(False)
        try:
            _,pid,bound=self._project()
            current=self.preview.currentItem()
            if not approved or current is None or self._bound!=bound:
                raise AuthorArcError('기록과 철회 승인을 다시 선택하세요.')
            withdraw_author_arc(self._folder,pid,current.data(256),explicit_author_withdraw=True)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('아크 철회를 실행하지 않았습니다. 다시 확인하세요.')

    def clear_coverage_detail(self, *_args):
        self.coverage_detail_text.clear()
        self.coverage_detail_status.setText('회차·아크를 선택하고 별도 클릭으로 현재 저장 원문을 조회하세요.')

    def invalidate_coverage(self, *_args):
        self.clear_coverage_detail()
        self.coverage_detail_button.setEnabled(False)
        self._coverage_snapshot = None
        self._coverage_identity = None
        self.coverage_table.setRowCount(0)
        self.coverage_open.setEnabled(False)
        self.coverage_status.setText('아크·작품·원고·범위 변경 시 직접 다시 조회하세요.')

    def preview_saved_arc_coverage(self):
        self.invalidate_coverage()
        try:
            session, identity = _current_author_state(self.authoring)
            if self._folder is None:
                raise AuthorArcFinalCoverageError('기존 아크 폴더를 직접 선택하세요.')
            snapshot = build_author_arc_final_coverage(
                session.store, identity[1], folder=self._folder,
                through_episode=self.coverage_through.value())
        except (AuthorArcFinalCoverageError, BatchScopeBridgeError,
                AuthorArcError, ValueError, OSError, LookupError):
            self.coverage_status.setText('기존 아크·저장 최종본을 읽지 못했습니다. 자동 승인 없음.')
            return
        self._coverage_snapshot, self._coverage_identity = snapshot, identity
        self.coverage_table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            values = (row.title, f'{row.start}~{row.end}화',
                      str(row.stored_final), str(row.missing_final),
                      str(row.foreshadow_hits), str(row.resolution_hits),
                      '재확인' if row.canon_changed else '변경 없음',
                      '검토 후보' if row.order_candidate else '확정 아님')
            for col, value in enumerate(values):
                self.coverage_table.setItem(index, col, QTableWidgetItem(value))
        self.coverage_open.setEnabled(bool(snapshot.rows))
        self.coverage_detail_button.setEnabled(bool(snapshot.rows))
        self.coverage_status.setText(
            f'기존 아크 {len(snapshot.rows)}개 대조 / '
            f'작가 검토 후보 {snapshot.review_candidate_count}개. '
            '복선·해소 문장과 최종본의 정확한 문자열 비교이며 '
            '실제 서사 해소·품질 합격·출판 승인 판정이 아닙니다.')

    def open_saved_arc_coverage(self):
        snapshot, identity = self._coverage_snapshot, self._coverage_identity
        index = self.coverage_table.currentRow()
        number = self.coverage_episode.value()
        self._coverage_snapshot = None
        self._coverage_identity = None
        self.coverage_open.setEnabled(False)
        if (snapshot is None or identity is None
                or not 0 <= index < len(snapshot.rows)
                or self._folder is None
                or str(self._folder.resolve()) != snapshot.folder
                or self.coverage_through.value() != snapshot.through_episode):
            self.coverage_status.setText('조회한 아크를 다시 직접 선택하세요.')
            return
        arc = snapshot.rows[index]
        if not arc.start <= number <= min(arc.end, snapshot.through_episode):
            self.coverage_status.setText('선택한 아크 안의 저장 회차를 직접 지정하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise AuthorArcFinalCoverageError('작품이 변경됐습니다.')
            require_current_author_arc_final_coverage(
                snapshot, session.store, identity[1])
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=number)
            self.coverage_status.setText(decision.message)
        except (AuthorArcFinalCoverageError, BatchScopeBridgeError,
                AuthorArcError, ValueError, OSError, LookupError):
            self.coverage_status.setText('아크·원고가 변경됐거나 저장 회차를 열 수 없습니다.')


    def show_saved_arc_episode_evidence(self):
        """두 번째 작가 클릭: 현재 원고·아크를 재확인한 뒤 읽기 전용 표시."""
        self.clear_coverage_detail()
        snapshot, identity = self._coverage_snapshot, self._coverage_identity
        index = self.coverage_table.currentRow()
        number = self.coverage_episode.value()
        if (snapshot is None or identity is None
                or not 0 <= index < len(snapshot.rows)
                or self._folder is None
                or str(self._folder.resolve()) != snapshot.folder
                or self.coverage_through.value() != snapshot.through_episode):
            self.coverage_detail_status.setText('아크·조회 범위를 다시 직접 선택하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity or _busy(self.authoring) or _unsaved(self.authoring):
                raise AuthorArcFinalCoverageError('작품·미저장 원고·집필 상태가 변경됐습니다.')
            detail = read_author_arc_episode_evidence(
                snapshot, session.store, identity[1],
                arc_id=snapshot.rows[index].arc_id, episode=number)
            if (_busy(self.authoring) or _unsaved(self.authoring)
                    or _current_author_state(self.authoring)[1] != identity
                    or self.coverage_table.currentRow() != index
                    or self.coverage_episode.value() != number):
                raise AuthorArcFinalCoverageError('선택이나 집필 상태가 변경됐습니다.')
            self.coverage_detail_text.setPlainText(detail.final_text)
            self.coverage_detail_status.setText(
                f'{detail.episode}화 저장 최종본 전체 원문 · revision {detail.revision} · '
                f'복선 표현 {detail.foreshadow_count}회 (앞 {len(detail.foreshadow_offsets)}개 '
                f'문자 위치: {detail.foreshadow_offsets}) · '
                f'해소 표현 {detail.resolution_count}회 (앞 {len(detail.resolution_offsets)}개 '
                f'문자 위치: {detail.resolution_offsets}). '
                '문자열 발견은 서사 완성·QC 합격·출판 승인이 아닙니다.')
        except (AuthorArcFinalCoverageError, BatchScopeBridgeError,
                AuthorArcError, ValueError, OSError, LookupError):
            self.clear_coverage_detail()
            self.coverage_detail_status.setText(
                '아크·저장 원고·작품 또는 미저장/집필 상태가 변경됐습니다. 다시 조회하세요.')
