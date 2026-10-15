"""Take synthetic Qt offscreen studio screenshots without real user content.

CI-only evidence. These frames are not physical Windows desktop screenshots
and must never be counted as real user/human acceptance.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys


def main(directory: str) -> int:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import Qt, QStandardPaths
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from ai_novel_factory.desktop.app import MainWindow

    QStandardPaths.setTestModeEnabled(True)
    app = QApplication.instance() or QApplication([])
    output = Path(directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    window = MainWindow()
    try:
        if not window.korean_font_supported:
            raise AssertionError('Synthetic screenshots require Korean font glyphs')
        window.show()
        app.processEvents()
        studio = window.studio
        checks = []
        def shot(name: str):
            app.processEvents()
            filename = output / (name + '.png')
            ok = window.grab().save(str(filename), 'PNG')
            if not ok or filename.stat().st_size < 3000:
                raise AssertionError('Failed synthetic screenshot: ' + name)
            checks.append(name)

        shot('01-first-start')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioNewButton'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        studio.new_title.setText('합성 실험작 — 거울탑')
        studio.new_author.setText('가상 작가')
        studio.new_genre.setText('가상 도시 판타지')
        studio.new_subject.setPlainText('창작 도시와 새 주인공의 여정')
        studio.new_premise.setPlainText('원본 참고작과 무관한 가상의 등불 설정')
        studio.new_mood.setText('신비')
        shot('02-create-wizard')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioCreateProjectButton'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        if not window.authoring.session.project_id:
            raise AssertionError('Synthetic studio project not created')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioFirstEpisodeButton'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        studio.editor.setPlainText(
            '합성 테스트 원고. 조용한 도시의 지붕 위로 처음 보는 별들이 지나갔다. '
            '이것은 사용자의 실제 원고나 참고 소설이 아닙니다.')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioSaveManuscript'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        if window.authoring.session.episode().draft != studio.editor.toPlainText():
            raise AssertionError('Synthetic studio save not confirmed')
        shot('03-novel-writer')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioHomeButton'),
                         Qt.MouseButton.LeftButton)
        shot('04-project-progress')
        (output / 'evidence.json').write_text(
            json.dumps({'synthetic_only': True,
                        'human_windows_acceptance': 'NOT_TESTED',
                        'reference_similarity_corpus': 'NOT_RUN',
                        'screenshots': checks}, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8')
        return 0
    finally:
        window.close()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: ci_studio_snapshots.py OUTPUT_DIR', file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
