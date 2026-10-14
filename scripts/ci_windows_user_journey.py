"""One Windows consumer workflow, with a hard FAIL if desktop workflow is incomplete.

Actual Windows executable startup + real Qt interactions + persistent SQLite.
A seeded project only exercises the subset possible without GUI project creation;
the end-to-end consumer journey is NOT allowed to pass on this shortcut.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton
from ai_novel_factory.database.novel_bible import NovelBibleStore
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.desktop.app import MainWindow
from ai_novel_factory.desktop.navigation import SECTIONS

ARTIFACT = Path("build/ci")
ARTIFACT.mkdir(parents=True,exist_ok=True)
EXE = Path("dist/stage97/AI_Novel_Factory.exe")
steps=[]
blockers=[]
report={"platform":sys.platform,
    "environment":"GitHub hosted Windows 2022, automatic Qt offscreen interaction",
    "workflow":"new work -> save bible -> write episode -> generate draft -> preview/export",
    "test_data":"synthetic original only", "user_manuscript":False,
    "published":False,"cloud_ai":False,"approvals_granted":False,
    "launcher_exe":"UNVERIFIED", "interactive_app":"UNVERIFIED",
    "user_journey":"NOT_STARTED","steps":steps,"blockers":blockers}

def mark(step,result,detail=""):
    steps.append({"step":step,"result":result,"detail":detail})
    if result=="BLOCKED" or result=="FAIL":
        blockers.append({"step":step,"reason":detail})

def fail(code,text):
    mark(code,"FAIL",text)
    raise AssertionError(text)

try:
    assert os.name == "nt" and sys.version_info[:2]==(3,12), "Real Windows Python 3.12 required"
    assert EXE.is_file(), "Windows EXE not built"
    # Start the actual GUI mode, not only --check or --gui-smoke.
    env=dict(os.environ,QT_QPA_PLATFORM="offscreen",ANF_AI_PROVIDER="disabled",ANF_ENV="test")
    with subprocess.Popen([str(EXE.resolve())],cwd=Path.cwd(),env=env,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as process:
        time.sleep(4)
        if process.poll() is not None:
            fail("native_exe_normal_launch","Actual Windows GUI process quit unexpectedly")
        mark("native_exe_normal_launch","PASS","Real compiled EXE GUI stays running (no clicks inside binary)")
        process.terminate()
        process.wait(timeout=12)
    report["launcher_exe"]="PASS"

    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    window.show()
    app.processEvents()
    report["interactive_app"]="SOURCE_QT_ACTUAL_CONTROLS_NOT_BINARY_AUTOMATION"
    if not window.isVisible():fail("qt_window","Qt MainWindow not visible")
    mark("qt_window","PASS","Original desktop widgets rendered on Windows offscreen")

    # The real user starts in the Novels section, not in a pre-seeded database.
    index=next(i for i,s in enumerate(SECTIONS) if s.key=="novels")
    item=window.sidebar.item(index)
    QTest.mouseClick(window.sidebar.viewport(),Qt.MouseButton.LeftButton,
                     pos=window.sidebar.visualItemRect(item).center())
    app.processEvents()
    if window.pages.currentIndex()!=index:fail("navigate_novels","Sidebar click did not navigate")
    mark("navigate_novels","PASS","Actual Qt click, not method call")
    novelpage=window.pages.currentWidget()
    create=novelpage.findChildren(QPushButton)
    if not create:
        mark("create_new_novel_in_gui","BLOCKED",
             "Novels page has zero action buttons: user cannot create a project in desktop app")
    else:
        mark("create_new_novel_in_gui","BLOCKED",
             "Novels page has unverified controls; project creation not proven")
    pending=novelpage.findChildren(type(window.statusBar().findChildren(type(window.statusBar()))[0])) if False else []
    # Continue with separate *developer-seeded* partial UI path, never count as full E2E.
    with tempfile.TemporaryDirectory(prefix="anf_windows_user_flow_") as tmp:
        db=Path(tmp)/"fiction.sqlite"
        with NovelBibleStore(db) as setup:
            prj=setup.create_project("Synthetic Story")
            setup.save_rule(prj.project_id,"genre","fantasy")
        with EpisodeStore(db) as prep:
            assert prep.get_project(prj.project_id).title == "Synthetic Story"
        mark("developer_seeded_db","BYPASS","GUI has no project creation action; backing SQLite seeded outside UI")
        epis=next(i for i,s in enumerate(SECTIONS) if s.key=="episodes")
        QTest.mouseClick(window.sidebar.viewport(),Qt.MouseButton.LeftButton,
                         pos=window.sidebar.visualItemRect(window.sidebar.item(epis)).center())
        app.processEvents()
        if window.pages.currentIndex()!=epis:fail("navigate_episodes","Qt click failed")
        mark("navigate_episodes","PASS")
        # Automate OS picker response because Windows runner has no human file-picker.
        with patch.object(QFileDialog,"getOpenFileName",return_value=(str(db),"SQLite DB")):
            QTest.mouseClick(window.plot_editor.open_button,Qt.MouseButton.LeftButton)
        app.processEvents()
        if window.plot_editor.project_combo.count()<1:
            fail("load_project_into_episode_editor","Existing synthetic project not loaded from DB")
        mark("load_existing_project","PASS","UI button click opens actual SQLite; picker response automated")
        window.plot_editor.new_episode_number.setValue(1)
        QTest.mouseClick(window.plot_editor.create_episode_button,Qt.MouseButton.LeftButton)
        app.processEvents()
        with EpisodeStore(db) as verify:
            ep=verify.get_episode(prj.project_id,1)
            if ep.episode!=1:fail("create_episode","Episode was not persisted")
        mark("create_episode_via_gui","PASS","UI click persisted episode to actual SQLite")
        plot="Explorer finds a strange gate and chooses the north path."
        window.plot_editor.plot_input.setPlainText(plot)
        app.processEvents()
        QTest.mouseClick(window.plot_editor.save_plot_button,Qt.MouseButton.LeftButton)
        app.processEvents()
        with EpisodeStore(db) as verify:
            ep=verify.get_episode(prj.project_id,1)
            if ep.plot != plot:fail("persist_plot","Plot edit not durable after SQLite re-open")
        mark("save_plot_and_sqlite_reopen","PASS","UI event persisted exactly, independent DB connection")
        scene="North road, invented town. Goal find lantern, danger fog."
        window.plot_editor.scene_input.setPlainText(scene)
        app.processEvents()
        QTest.mouseClick(window.plot_editor.add_scene_button,Qt.MouseButton.LeftButton)
        app.processEvents()
        with EpisodeStore(db) as verify:
            snapshot=verify.snapshot(prj.project_id,1)
            if len(snapshot.scenes)!=1 or snapshot.scenes[0].text!=scene:
                fail("persist_scene","New scene not in SQLite after re-open")
        mark("add_scene_and_sqlite_reopen","PASS","UI click, real scene save and read-back")
        # What a reader expects next: one-click local AI generation from the same GUI.
        if not window.plot_editor.findChildren(QPushButton,"generateSceneWithLocalModel"):
            mark("draft_scene_using_gui","BLOCKED",
                "Episode editor has no local model generation button")
        # What a reader expects after editing: export directly from Publication section.
        publication=next(i for i,s in enumerate(SECTIONS) if s.key=="publication")
        QTest.mouseClick(window.sidebar.viewport(),Qt.MouseButton.LeftButton,
                         pos=window.sidebar.visualItemRect(window.sidebar.item(publication)).center())
        app.processEvents()
        if not window.pages.currentWidget().findChildren(QPushButton):
            mark("epub_txt_export_using_gui","BLOCKED",
                "Publication page only shows future feature placeholder; no EPUB/TXT export controls")
        window.sidebar.setCurrentRow(index)
        app.processEvents()
        screenshot=ARTIFACT/"windows_actual_user_journey.png"
        assert window.grab().save(str(screenshot),"PNG"), "Could not capture GUI"
        mark("screenshot","PASS","Saved actual Windows Qt view (synthetic)")
        window.close()
        app.processEvents()
        # Ensure post-run original database went out of scope before temp cleanup.
    report["user_journey"]="BLOCKED" if blockers else "PASS"
except BaseException as exc:
    report["user_journey"]="FAIL"
    mark("uncaught_exception","FAIL",f"{type(exc).__name__}: {str(exc)[:450]}")
finally:
    report["automatic_whole_product_acceptance"]="FAIL" if blockers else report["user_journey"]
    report["user_pc_visual_acceptance"]="UNVERIFIED"
    report["official_platform_upload"]="UNVERIFIED"
    with (ARTIFACT/"windows_actual_user_journey.json").open("x",encoding="utf8") as fp:
        json.dump(report,fp,ensure_ascii=False,indent=2)
        fp.write("\n")
    print(json.dumps(report,ensure_ascii=False))
sys.exit(0 if report["user_journey"]=="PASS" and not blockers else 1)
