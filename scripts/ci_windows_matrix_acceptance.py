"""Combine only genuine current-run Windows CI artifacts and actual executable checks.

This is an automated engineering gate, not consent to publish or a physical GUI
acceptance. Origin of input logs is verified by CI's own artifact plumbing.
"""
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import stage99_windows_acceptance as stage99

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "ci"
EXE = ROOT / "dist" / "stage97" / "AI_Novel_Factory.exe"

def main() -> int:
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise SystemExit("genuine Windows Python 3.12 runner required")
    report = json.loads((EVIDENCE / "matrix_groups.json").read_text("utf8"))
    groups = report["groups_detail"]
    if (len(groups) != 8 or sorted(g["group"] for g in groups) != list(range(1, 9))
            or report.get("module_coverage_exact") is not True
            or report.get("all_exit_codes_zero") is not True
            or report.get("total") != report.get("passed", 0) + report.get("skipped", 0)
            or any(not g["success"] or g["exit_code"] != 0 for g in groups)):
        raise SystemExit("incomplete or failing 8-group regression evidence")
    exe_report = json.loads((EVIDENCE / "stage97_build.json").read_text("utf8"))
    if not (exe_report.get("windows_exe_built") is True
            and exe_report.get("windows_runtime_verified") is True
            and stage99.is_pe_file(EXE)):
        raise SystemExit("real native build or PE header validation failed")
    with EXE.open("rb") as fd:
        digest = sha256(fd.read()).hexdigest()
    if exe_report.get("exe_sha256") != digest:
        raise SystemExit("EXE SHA-256 differs from native build report")
    smoke = {}
    codes = {}
    env = dict(os.environ, ANF_AI_PROVIDER="disabled", ANF_ENV="test",
               QT_QPA_PLATFORM="offscreen")
    for mode, expected in stage99.CHECKS.items():
        run = subprocess.run([str(EXE), mode], cwd=ROOT, env=env, timeout=60,
                             capture_output=True, text=True, errors="replace")
        codes[mode] = run.returncode
        smoke[mode] = (run.returncode == 0 and expected in run.stdout)
    result = stage99.assess(os_name=os.name, python_version=sys.version_info[:2],
                exe_exists=EXE.is_file(), pe_valid=True,
                smoke=smoke, regression=report)
    result["mode"] = "matrix_artifact_evidence_plus_new_native_windows_build"
    result["exe_sha256"] = digest
    result["real_unittest_count"] = report["total"]
    result["real_passed"] = report["passed"]
    result["real_skipped"] = report["skipped"]
    result["real_exit_codes"] = {str(g["group"]): g["exit_code"] for g in groups}
    result["real_native_exe_smoke_exit_codes"] = codes
    result["real_native_exe_smoke"] = smoke
    result["official_platform_api_upload"] = "UNVERIFIED"
    result["physical_display_user_review"] = "UNVERIFIED"
    result["actual_user_manuscript_quality"] = "UNVERIFIED"
    result["release_approved"] = False
    result["production_branch_modified"] = False
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    dest = EVIDENCE / "windows_matrix_acceptance.json"
    with dest.open("x", encoding="utf8") as fd:
        json.dump(result, fd, ensure_ascii=False, indent=2, sort_keys=True)
        fd.write("\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["windows_acceptance_met"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
