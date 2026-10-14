"""Automated Qt GUI screen-navigation and screenshot check, no account/user input."""
from pathlib import Path
import json
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget
from ai_novel_factory.desktop.app import MainWindow
from ai_novel_factory.desktop.navigation import SECTIONS

app = QApplication.instance() or QApplication([])
window = MainWindow()
window.show()
app.processEvents()
assert window.sidebar.count() == len(SECTIONS) == 12
assert window.pages.count() == 12
for i, section in enumerate(SECTIONS):
    window.sidebar.setCurrentRow(i)
    app.processEvents()
    assert window.pages.currentIndex() == i
    title = window.pages.widget(i).findChild(QLabel, "title_"+section.key)
    assert title is not None and title.text() == section.label
# Distinguish visible navigation from implemented functionality.
placeholders=[]
connected=[]
for i, section in enumerate(SECTIONS):
    page=window.pages.widget(i)
    pending=page.findChild(QLabel, "pending_"+section.key)
    if pending is not None and "후속 개발" in pending.text():
        placeholders.append(section.key)
    else:
        connected.append(section.key)
assert len(placeholders)+len(connected)==len(SECTIONS)
assert window.statusBar().currentMessage().startswith("로컬 UI 준비됨")
assert "AI/출판 비활성" in window.statusBar().currentMessage()
window.sidebar.setCurrentRow(9)
app.processEvents()
tabs = window.pages.widget(9).findChild(QTabWidget, "episodeWorkTabs")
assert tabs is not None and tabs.count() == 3
assert "회차" in tabs.tabText(0)
window.sidebar.setCurrentRow(0)
app.processEvents()
out=Path("build/ci")
out.mkdir(parents=True,exist_ok=True)
grab=window.grab()
assert not grab.isNull()
assert grab.save(str(out/"gui_nav.png"),"PNG")
report={"platform":"offscreen_Qt", "screens_checked":12, "episode_tabs":3,
        "status_network_off_and_publication_disabled":True,
        "image_width":grab.width(),"image_height":grab.height(),
        "physical_user_acceptance":"UNVERIFIED", "publication_executed":False,
        "user_data_used":False,
        "functional_widgets_connected":connected,
        "placeholder_only_sections":placeholders,
        "placeholder_count":len(placeholders),
        "gui_functional_release_gate":"BLOCKED" if placeholders else "READY_FOR_MORE_TESTING"}
(out/"gui_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
window.close()
app.processEvents()
print(json.dumps(report,ensure_ascii=False))
