"""Manual authoring form construction; all side effects are button initiated."""
from .auto_batch_panel import AutoBatchPanel

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QComboBox, QCheckBox, QScrollArea,
)

class AuthoringControls:
    def build_controls(self):
        root = QVBoxLayout(self)
        self.status = QLabel('로컬 전용 · 사용자 승인 전 AI 실행 및 출판 없음')
        self.status.setObjectName('authoringStatus')
        root.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.layout = QVBoxLayout(body)
        self.fields = {}
        self.buttons = {}
        self._section('1. 작품 생성 / 기존 DB')
        self._field('db', '로컬 DB 파일 경로')
        self._button('choose_new_database', '새 SQLite 저장 위치 선택',
                     self._choose_new_database)
        self._button('choose_existing_database', '기존 SQLite 파일 선택',
                     self._choose_existing_database)
        self._field('title', '작품 제목')
        self._field('author', '작가 이름')
        self._field('premise', '최상위 설정', multiline=True)
        self._field('genre', '장르')
        self._field('subject', '소재/핵심 아이디어')
        self._field('target_episodes', '목표 회차 수 (1~1000000)')
        self._field('characters_per_episode', '회차당 목표 글자 수')
        self._field('mood', '분위기')
        self._button('create', '새 작품 생성', self._create, 'createProjectButton')
        self._button('open', '기존 작품 열기', self._open, 'openAuthoringProjectButton')
        self._button('author_progress', '장편 회차별 현황 열기 (읽기 전용)',
                     self._show_author_progress, 'authoringProgressOpen')
        self._section('2. Novel Bible')
        self._field('bible', '설정', multiline=True)
        self._button('save_bible', '설정 저장',
                     lambda: self.session.save_bible(self._text('bible')))
        self._section('3. 회차와 장면')
        self.episodes = QComboBox()
        self.episodes.setObjectName('authoringEpisodeSelector')
        self.form.addRow('기존 회차', self.episodes)
        self.number = QSpinBox()
        self.number.setRange(1, 1000000)
        self.form.addRow('새 회차 번호', self.number)
        self._field('plot', '회차 플롯', multiline=True)
        self._button('create_episode', '새 회차 생성',
                     lambda: self.session.create_episode(self.number.value(), self._text('plot')))
        self._button('save_plot', '회차 플롯 저장',
                     lambda: self.session.save_plot(self._text('plot')))
        self.scenes = QComboBox()
        self.scenes.setObjectName('authoringSceneSelector')
        self.form.addRow('장면 선택', self.scenes)
        self._field('scene', '장면 플롯', multiline=True)
        self._button('add_scene', '장면 추가', lambda: self.session.add_scene(''))
        self._button('save_scene', '장면 저장',
                     lambda: self.session.save_scene(self._text('scene')))
        self._section('4. 실제 로컬 모델 초고 (별도 실행 승인)')
        for key, label in [('executable', '신뢰한 실행 파일 절대 경로'),
                           ('arguments', '실행 인수'), ('goal', '장면 목표'),
                           ('conflict', '갈등'), ('location', '장소'),
                           ('characters', '등장인물 (쉼표 구분)')]:
            self._field(key, label)
        self._button('choose_model', '로컬 AI 실행 파일 찾기', self._choose_model_executable)
        self._button('choose_gguf', '소설 집필용 로컬 GGUF 직접 선택',
                     self._choose_gguf_model)
        self.approved = QCheckBox('이 로컬 실행 파일의 이번 실행을 승인합니다')
        self.approved.setObjectName('authoringLocalModelApproval')
        self.form.addRow(self.approved)
        self._button('generate', '로컬 AI 초고 생성', self._generate,
                     'generateSceneWithLocalModel')
        self._field('draft', '검토 가능한 초고', multiline=True)
        self._button('save_draft', '검토한 초고 SQLite 저장',
                     lambda: self.session.save_draft(self._text('draft')),
                     'saveAuthoringDraftButton')
        self._section('5. 사용자 직접 검수·최종 원고 저장')
        self._field('final_text', '검수·수정한 최종 원고', multiline=True)
        self.final_reviewed = QCheckBox('제가 원고를 직접 읽고 검수했습니다')
        self.final_reviewed.setObjectName('authoringHumanFinalReview')
        self.form.addRow(self.final_reviewed)
        self.final_quality_ack = QCheckBox(
            '자동 일관성·유사성 등 품질 검사가 미완료일 수 있음을 확인합니다')
        self.final_quality_ack.setObjectName('authoringFinalIncompleteQualityAcknowledged')
        self.form.addRow(self.final_quality_ack)
        self._button('save_final', '검수한 최종본 저장 (기존 원고 덮어쓰기 금지)',
                     self._save_final, 'saveHumanReviewedFinalButton')
        self._section('6. 비공개 TXT + EPUB')
        self._field('export_dir', '기존 출력 폴더 절대 경로')
        self._button('choose_export_dir', '비공개 내보내기 폴더 선택',
                     self._choose_export_directory)
        self._field('price', 'EPUB 메타데이터 KRW 가격 (명시적 입력)')
        self._button('export', '비공개 TXT + EPUB 내보내기',
                     lambda: self.session.export(self._text('export_dir'), self._text('price')),
                     'exportAuthoringTxtEpubButton')
        self.form.addRow(QLabel('게시·원격 업로드·출판 승인 없음. 기존 파일 덮어쓰기 금지.'))
        self.auto_panel = AutoBatchPanel(self, self)
        self.layout.addWidget(self.auto_panel)
        self.layout.addStretch(1)
        self.episodes.currentIndexChanged.connect(self._select_episode)
        self.scenes.currentIndexChanged.connect(self._select_scene)

    def _section(self, title):
        group = QGroupBox(title)
        self.form = QFormLayout(group)
        self.layout.addWidget(group)

    def _field(self, key, label, multiline=False):
        field = QPlainTextEdit() if multiline else QLineEdit()
        field.setObjectName('authoring_' + key)
        field.setAccessibleName(label)
        field.setAccessibleDescription('작품 집필 입력: ' + label)
        if multiline:
            field.setMaximumHeight(95)
        self.fields[key] = field
        self.form.addRow(label, field)

    def _text(self, key):
        field = self.fields[key]
        return field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()

    def _set(self, key, text):
        field = self.fields[key]
        if isinstance(field, QPlainTextEdit):
            field.setPlainText(text)
        else:
            field.setText(text)

    def _button(self, key, title, fn, object_name=None):
        button = QPushButton(title)
        button.setObjectName(object_name or 'authoring_' + key)
        button.setAccessibleName(title)
        self.buttons[key] = button
        self.form.addRow(button)
        button.clicked.connect(lambda: self._run(fn, title + ' 완료'))
