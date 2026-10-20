"""Native offline cover-draft controls wired to existing procedural Stage 91.

The user must click the creation button and select an already existing local
folder. A cover/thumbnail pair is saved via exclusive O_EXCL writes; no user
artwork, SQLite content, reference novel, or publishing state is overwritten.
This does NOT assert copyright/originality or release approval.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton,
)

from ai_novel_factory.cover_art import (
    CoverArtError, CoverSpec, PALETTES, STYLES, save_cover_pair,
)


class CoverDraftWidget(QWidget):
    def __init__(self, session_getter, directory_getter, parent=None):
        super().__init__(parent)
        self.setObjectName('coverDraftWidget')
        self._session_getter = session_getter
        self._directory_getter = directory_getter
        self._identity = None
        root = QVBoxLayout(self)
        info = QLabel(
            '오프라인 표지 초안 · 현재 작품의 제목·필명만 이용합니다. '
            '참고소설 표지·원본 이미지는 읽지 않습니다. '
            '기존 cover.jpg / thumbnail.jpg는 절대 덮어쓰지 않습니다. '
            '실제 출판과 권리 검토는 별도 승인입니다.')
        info.setWordWrap(True)
        root.addWidget(info)
        form = QFormLayout()
        self.title_field = QLineEdit()
        self.title_field.setObjectName('coverDraftTitle')
        self.title_field.setAccessibleName('표지용 작품 제목')
        self.author_field = QLineEdit()
        self.author_field.setObjectName('coverDraftAuthor')
        self.author_field.setAccessibleName('표지용 필명')
        self.genre_field = QLineEdit()
        self.genre_field.setObjectName('coverDraftGenre')
        self.genre_field.setAccessibleName('표지에 표시할 장르')
        self.palette = QComboBox()
        self.palette.setObjectName('coverDraftPalette')
        for key, label in (
                ('nocturne', '밤하늘 계열'), ('ember', '붉은 계열'),
                ('verdant', '녹색 계열')):
            if key in PALETTES:
                self.palette.addItem(label, key)
        self.style = QComboBox()
        self.style.setObjectName('coverDraftStyle')
        for key, label in (
                ('orbital', '궤도형'), ('horizon', '지평선형'),
                ('spire', '첨탑형')):
            if key in STYLES:
                self.style.addItem(label, key)
        self.variation = QLineEdit()
        self.variation.setObjectName('coverDraftVariation')
        self.variation.setPlaceholderText('선택: 같은 작품의 다른 시안 구분 문자열')
        for label, field in (
                ('작품 제목', self.title_field), ('필명', self.author_field),
                ('장르', self.genre_field), ('색상', self.palette),
                ('형태', self.style), ('변형 (선택)', self.variation)):
            form.addRow(label, field)
        root.addLayout(form)
        actions = QHBoxLayout()
        self.generate_button = QPushButton('기존 로컬 출력 폴더에 표지 초안·썸네일 생성')
        self.generate_button.setObjectName('coverDraftGenerate')
        self.generate_button.clicked.connect(self.generate)
        actions.addWidget(self.generate_button)
        root.addLayout(actions)
        self.status = QLabel('출력 폴더를 지정한 뒤 생성 버튼을 눌러 주세요. 자동 생성하지 않습니다.')
        self.status.setObjectName('coverDraftStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.preview = QLabel('표지 미리보기 없음')
        self.preview.setObjectName('coverDraftPreview')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(140)
        self.preview.setMaximumHeight(250)
        root.addWidget(self.preview)

    def refresh(self):
        session = self._session_getter()
        if session is None or session.store is None or not session.project_id:
            self._identity = None
            self.title_field.clear()
            self.author_field.clear()
            self.genre_field.clear()
            self.preview.clear()
            self.status.setText('표지를 만들 작품을 먼저 열어 주세요.')
            return
        identity = (str(session.path), session.project_id)
        if self._identity == identity:
            return  # preserve user-edited cover fields and style selections
        try:
            project = session.store.get_project(session.project_id)
            rules = {rule.key: rule.value
                     for rule in session.store.list_rules(session.project_id)}
        except (OSError, ValueError):
            self.status.setText('현재 작품의 로컬 설정을 불러올 수 없습니다.')
            self._identity = None
            return
        self._identity = identity
        self.title_field.setText(project.title)
        # The existing NovelBible stores author under rules, not BibleProject.
        # The legacy '미정' marker is not a user-approved pen name.
        saved_author = rules.get('author', '')
        self.author_field.setText('' if saved_author == '미정' else saved_author)
        self.genre_field.setText(rules.get('genre', '') or '소설')
        self.preview.clear()
        self.preview.setText('표지 미리보기 없음')
        self.status.setText('직접 생성하기 전에는 표지 파일이 만들어지지 않습니다.')

    def generate(self):
        session = self._session_getter()
        if (not session or session.store is None or not session.project_id
                or self._identity != (str(session.path), session.project_id)):
            self.status.setText('작품을 다시 선택한 뒤 표지를 생성하세요.')
            return
        supplied = self._directory_getter()
        if not isinstance(supplied, str) or not supplied.strip():
            self.status.setText('먼저 기존 로컬 출력 폴더를 지정하세요.')
            return
        folder = Path(supplied)
        if (not folder.is_absolute() or folder.is_symlink()
                or not folder.is_dir()):
            self.status.setText('기존 로컬 폴더의 절대경로만 허용합니다.')
            return
        # Missing author is not silently replaced with an invented name.
        if not self.author_field.text().strip():
            self.status.setText('표지에 사용할 필명을 직접 입력하세요.')
            return
        spec = CoverSpec(
            title=self.title_field.text(), author=self.author_field.text(),
            genre=self.genre_field.text(), palette=self.palette.currentData(),
            style=self.style.currentData(), variation=self.variation.text())
        self.generate_button.setEnabled(False)
        try:
            result = save_cover_pair(spec, folder)
            # Only inspect the file just produced, never unrelated images.
            image = QPixmap(str(result.thumbnail_path))
            if image.isNull():
                self.preview.setText('JPEG 저장 완료 · 화면 미리보기는 표시하지 못했습니다.')
            else:
                self.preview.setPixmap(
                    image.scaledToHeight(190, Qt.TransformationMode.SmoothTransformation))
            self.status.setText(
                '표지 cover.jpg · 썸네일 thumbnail.jpg 로컬 저장 완료. '
                '원고·출판 승인 상태는 변경하지 않았습니다.')
        except (CoverArtError, OSError):
            self.status.setText(
                '표지 저장 실패 · 파일 중복, 글꼴/Pillow 또는 폴더 권한을 확인하세요. '
                '기존 파일은 변경하지 않았습니다.')
        finally:
            self.generate_button.setEnabled(True)
