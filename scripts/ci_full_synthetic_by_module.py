"""Isolated CI-only unittest runner: bounded, documented failures, never user data.

Run only inside a disposable CI checkout with dummy tests and disabled providers.
Isolation prevents a hanging test module from concealing the remaining modules.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def run_all(root: Path, destination: Path, *, timeout: int = 150) -> int:
    if not (root / "tests").is_dir() or not (root / "pyproject.toml").is_file():
        raise ValueError("Expected a repository checkout with test modules")
    destination.mkdir(parents=True, exist_ok=True)
    candidates = sorted((root / "tests").glob("test_*.py"))
    if not candidates:
        raise ValueError("No test modules found")
    records = []
    total_tests = 0
    total_skips = 0
    for pos, file in enumerate(candidates, 1):
        print(f"[{pos}/{len(candidates)}] RUN {file.name}", flush=True)
        started = time.monotonic()
        command = [sys.executable, "-X", "faulthandler", "-m", "unittest",
                   "discover", "-s", "tests", "-p", file.name, "-v"]
        try:
            proc = subprocess.run(command, cwd=root, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout,
                                  check=False)
            log = proc.stdout
            match = re.findall(r"Ran\s+(\d+)\s+tests?\s+in", log)
            count = int(match[-1]) if match else 0
            skipped = re.findall(r"OK\s*\(skipped=(\d+)\)", log)
            skips = int(skipped[-1]) if skipped else 0
            result = "PASS" if proc.returncode == 0 and count else "FAIL"
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout or b""
            log = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            log += "\n[CI] MODULE_TIMEOUT after bounded wait\n"
            result, count, skips, exit_code = "TIMEOUT", 0, 0, None
        (destination / f"{file.stem}.log").write_text(log, encoding="utf-8")
        elapsed = round(time.monotonic() - started, 2)
        records.append({"module": file.name, "result": result, "tests": count,
                        "skipped": skips, "elapsed_s": elapsed, "exit_code": exit_code})
        total_tests += count
        total_skips += skips
        print(f"[{pos}/{len(candidates)}] {result} {file.name}: "
              f"{count} tests, {skips} skipped, {elapsed}s", flush=True)
        if result != "PASS":
            # Print a concise diagnostic while retaining full log as artifact.
            for line in log.splitlines()[-60:]:
                if "FAILED" in line or "ERROR:" in line or "FAIL:" in line or "Timeout" in line:
                    print("  ", line[:300], flush=True)
    fails = [record for record in records if record["result"] != "PASS"]
    report = {"modules_total": len(candidates), "modules_pass": len(candidates)-len(fails),
              "modules_fail": len(fails), "tests_run": total_tests, "tests_skipped": total_skips,
              "result": "FAIL" if fails else "PASS", "modules": records}
    (destination / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    print(f"FINAL {report['result']}: {len(candidates)} modules, "
          f"{total_tests} tests, {total_skips} skipped, {len(fails)} failed modules", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--timeout", type=int, default=150)
    args = cli.parse_args()
    if not 5 <= args.timeout <= 600:
        cli.error("Per-module timeout must be between 5 and 600 seconds")
    raise SystemExit(run_all(args.root.resolve(), args.output.resolve(), timeout=args.timeout))
