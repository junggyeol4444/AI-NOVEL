"""Read-only, local reference catalog coverage report (not a similarity check)."""
from __future__ import annotations
import argparse
from pathlib import Path
from ai_novel_factory.desktop.reference_coverage import read_reference_coverage

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only reference coverage, no manuscript access")
    parser.add_argument("catalog", type=Path, help="Absolute path to local reference catalog SQLite")
    args = parser.parse_args(argv)
    coverage = read_reference_coverage(args.catalog)
    print(coverage.label)
    return 2 if coverage.registered is None else 0

if __name__ == "__main__":
    raise SystemExit(main())
