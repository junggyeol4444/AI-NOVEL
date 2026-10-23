"""Offline, read-only author-language context and candidate-spelling review UI."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QFormLayout, QLabel, QSpinBox, QComboBox,
    QPushButton, QFileDialog, QPlainTextEdit,
)
from ..author_language_context import (build_author_language_context,
                                       review_discouraged_spelling)
from ..author_language_ledger import AuthorLanguageError


class AuthorLanguageReviewPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 언어 규칙 · 회차별 표기 검토 후보 (읽기 전용)', parent)
        self.authoring = authoring
        self.folder: Path | None = None
        root = QVBoxLayout(self)
        note = QLabel('검토 후보는 단순 표기 출현이며 오류 확정·문학 품질 PASS가 아닙니다. 원고 자동 변경 없음.')
        note.setWordWrap(True); root.addWidget(note)
        form = QFormLayout(); root.addLayout(form)
        self.episode = QSpinBox(); self.episode.setRange(1, 1000)
        form.addRow('검토할 저장 회차', self.episode)
        self.source = QComboBox(); self.source.addItem('저장 최종 원고', 'final_text')
        self.source.addItem('저장 초고', 'draft')
        form.addRow('원고 종류', self.source)
        choose = QPushButton('기존 로컬 작가 언어 규칙 폴더 선택')
        choose.clicked.connect(self.choose_folder); root.addWidget(choose)
        read = QPushButton('회차별 권장 표기·비권장 표현 후보 조회')
        read.clicked.connect(self.refresh); root.addWidget(read)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(285); root.addWidget(self.preview)
        self.status = QLabel('원고·모델·참고작에 쓰거나 외부 전송하지 않습니다.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.episode.valueChanged.connect(self._clear)
        self.source.currentIndexChanged.connect(self._clear)

    def _clear(self, *_):
        self.preview.clear()
        self.status.setText('선택이 변경됐습니다. 직접 다시 조회하세요.')

    def invalidate(self):
        self._clear()
        self.folder = None
        self.status.setText('작품이 변경됐습니다. 로컬 규칙 폴더를 다시 선택하세요.')

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, '기존 로컬 언어 규칙 폴더')
        if chosen:
            self.folder = Path(chosen)
            self._clear()

    def refresh(self):
        self.preview.clear()
        try:
            if self.folder is None:
                raise AuthorLanguageError('로컬 언어 규칙 폴더 선택 필요')
            store, project_id = self.authoring.session.required()
            number = self.episode.value()
            state = build_author_language_context(store, str(project_id),
                episode=number, folder=self.folder)
            if not state.configured:
                self.status.setText('이 회차의 활성 작가 언어 규칙이 없습니다. 자동 통과가 아닙니다.')
                return
            if state.stale:
                self.status.setText('작품 설정이 달라졌습니다. 언어 규칙을 수동으로 다시 확인하세요.')
                return
            episode = store.get_episode(str(project_id), number)
            manuscript = getattr(episode, str(self.source.currentData()))
            hints = review_discouraged_spelling(manuscript, state)
            lines = [f'{number}화 · 현재 작가 직접 기록 규칙 {len(state.applicable)}개',
                     '==== 작성 참고 문맥 (QC/출판 승인 아님) ====',
                     state.prompt_text,
                     '==== 현재 저장 원고의 비권장 표기 단순 검색 결과 (작가 검토 후보) ====']
            if hints:
                for hint in hints:
                    lines.append(f'- {hint.subject} / {hint.unexpected_form}: {hint.count}회 · 첫 위치 {hint.first_offset + 1}')
            else:
                lines.append('해당 규칙의 비권장 표기 출현이 발견되지 않았음. 품질 검증 PASS 아님.')
            self.preview.setPlainText('\n'.join(lines))
            self.status.setText('로컬 원고 읽기만 수행. 자동 교정·원고 저장·QC 승인 없음.')
        except (AuthorLanguageError, OSError, ValueError):
            self.status.setText('규칙 또는 회차 원고 조회를 완료하지 못했습니다.')
        except Exception:
            self.status.setText('로컬 회차 데이터를 읽을 수 없습니다. 원고는 변경하지 않았습니다.')
