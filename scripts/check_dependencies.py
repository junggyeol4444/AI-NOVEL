"""Offline check for stage-5 packaging/version policy. Python 3.11+ (tomllib)."""
from __future__ import annotations
import sys
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_EXTRAS = {"desktop", "api", "database", "queue", "documents", "quality", "dev", "build"}
REQUIRED_PACKAGES = {
    "desktop": {"pyside6", "httpx"},
    "api": {"fastapi", "uvicorn", "pydantic", "pydantic-settings"},
    "database": {"sqlalchemy", "psycopg", "pgvector"},
    "queue": {"celery", "redis"},
    "documents": {"ebooklib", "python-docx", "pypdf"},
    "quality": {"rapidfuzz"},
    "dev": {"pytest", "ruff"},
    "build": {"pyinstaller"},
}


def _name(spec: str) -> str:
    # Parse the distribution name before version specifier or extras.
    for sep in ("[", "<", ">", "=", "!", "~", " "):
        spec = spec.split(sep, 1)[0]
    return spec.lower().replace("_", "-")


def check() -> list[str]:
    issues: list[str] = []
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    if project.get("requires-python") != ">=3.12,<3.13":
        issues.append("Python requires-python constraint differs from stage-5 policy")
    if (ROOT / ".python-version").read_text(encoding="utf-8").strip() != "3.12":
        issues.append(".python-version differs from stage-5 policy")
    extras = project.get("optional-dependencies", {})
    if set(extras) != REQUIRED_EXTRAS:
        issues.append(f"Extras mismatch: {set(extras) ^ REQUIRED_EXTRAS}")
    for group, required in REQUIRED_PACKAGES.items():
        specs = extras.get(group, [])
        names = {_name(s) for s in specs}
        if not required.issubset(names):
            issues.append(f"Missing {group} dependencies: {required - names}")
        for spec in specs:
            if ">=" not in spec or "<" not in spec:
                issues.append(f"Unbounded dependency: {spec}")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for rule in (".env", "secrets/", "user_data/", "reference_uploads/", "manuscripts/"):
        if rule not in gitignore:
            issues.append(f"Missing gitignore rule: {rule}")
    if "uv.lock" in [line.strip() for line in gitignore.splitlines() if not line.lstrip().startswith("#")]:
        issues.append("uv.lock must not be ignored")
    return issues


if __name__ == "__main__":
    problems = check()
    if problems:
        print("FAIL:", *problems, sep="\n - ")
        sys.exit(1)
    print("PASS: stage-5 dependency manifest and version-control policy checks")
    print("NOTICE: no package install, lockfile resolution or Windows EXE build was performed")