"""Native Windows EXE UI automation, not in-process Qt source tests.

Attempt the actual author's sequence from compiled EXE; FAIL if the creation
or manuscript workflow cannot be reached. Always emit evidence, never upload.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from time import sleep

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"build"/"ci"
OUT.mkdir(parents=True,exist_ok=True)
EXE=ROOT/"dist"/"stage97"/"AI_Novel_Factory.exe"
report={"test":"compiled Windows EXE through real OS UI Automation",
        "runner":"Windows 2022", "user_data":False,"publishing":False,
        "steps":[],"blockers":[],"whole_user_journey":"FAIL"}
process=None
def mark(step,status,detail):
    v={"step":step,"status":status,"detail":str(detail)[:450]}
    report["steps"].append(v)
    print(json.dumps(v,ensure_ascii=False),flush=True)
    if status!="PASS":report["blockers"].append(v)
try:
    if os.name!="nt":raise RuntimeError("Windows required")
    if not EXE.is_file():raise RuntimeError("Built EXE absent")
    from pywinauto import Desktop
    import psutil
    env=dict(os.environ,ANF_AI_PROVIDER="disabled")
    env.pop("QT_QPA_PLATFORM",None)
    process=subprocess.Popen([str(EXE)],cwd=str(ROOT),env=env,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    sleep(5)
    if process.poll() is not None:raise RuntimeError("Real Windows GUI EXE exited early")
    mark("launch actual compiled Windows GUI","PASS",f"PID={process.pid}")
    # PyInstaller one-file bootloader may spawn the real Qt child process,
    # so matching the initial launch PID alone misses the actual GUI HWND.
    launcher=psutil.Process(process.pid)
    related={process.pid}|{p.pid for p in launcher.children(recursive=True)}
    candidates=[]
    for backend in ("uia","win32"):
        try:
            visible=Desktop(backend=backend).windows(visible_only=True)
            matches=[w for w in visible if w.process_id() in related
                     and "AI Novel Factory" in w.window_text()]
            if matches:
                candidates=matches
                mark("find actual executable GUI process","PASS",
                     f"backend={backend}, window_pid={matches[0].process_id()}, launcher_pid={process.pid}")
                break
        except Exception as search_error:
            print(f"UIA diagnostic {backend}: {type(search_error).__name__}",flush=True)
    if not candidates:
        mark("attach Windows UIAutomation to compiled EXE","BLOCKED",
             "Hosted runner desktop session exposes no visible Qt window for the actual EXE child process")
        raise RuntimeError("Windows hosted runner UIAutomation cannot enumerate compiled Qt window")
    window=candidates[0]
    mark("attach Windows UIAutomation to compiled EXE","PASS",window.window_text())
    controls=window.descendants()
    capture=[{"name":c.window_text(),"class":c.friendly_class_name()} for c in controls]
    (OUT/"native_ui_controls.json").write_text(
        json.dumps(capture,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    # Real buttons of the window, not source introspection.
    buttons=[str(c.window_text()) for c in controls if c.friendly_class_name()=="Button"]
    lst=[c for c in controls if c.window_text()=="작품"]
    if lst:
        mark("find novel menu in compiled EXE","PASS",lst[0].friendly_class_name())
        lst[0].click_input()
        sleep(0.7)
    else:
        mark("find novel menu in compiled EXE","BLOCKED","No accessible Novels menu")
    controls2=window.descendants()
    # Detect actual creation action, not generic local API connection button.
    candidates=[str(c.window_text()) for c in controls2
                if c.friendly_class_name()=="Button" and
                any(q in str(c.window_text()) for q in ("작품 생성","새 작품","작품 만들기"))]
    if not candidates:
        mark("user creates first novel from actual EXE","BLOCKED",
             "No create-novel action is exposed in compiled GUI")
    else:
        mark("user creates first novel from actual EXE","BLOCKED",
             "Possible creation control present but real persistence workflow unverified: "+str(candidates))
    mark("novel-to-bible-to-characters-to-scenes-to-local-AI-to-export","BLOCKED",
         "Requires successful creation from real GUI and connected authoring/publishing pages")
except BaseException as exc:
    mark("native GUI automation exception","BLOCKED",
         type(exc).__name__+": "+str(exc))
finally:
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill()
    report["whole_user_journey"]="BLOCKED" if report["blockers"] else "PASS"
    report["physical_user_pc_test"]="UNVERIFIED"
    report["release_ready"]=False
    (OUT/"native_windows_exe_user_journey.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"whole_user_journey":report["whole_user_journey"],
          "blockers":report["blockers"]},ensure_ascii=False),flush=True)
sys.exit(0 if not report["blockers"] else 1)
