"""Stage 40: validate an offline cumulative ZIP before distributing it.

No extraction, GitHub, network, cloud AI, or access to user manuscripts.
The check deliberately does not print archive entry names on failure.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import stat
import re

REQUIRED = frozenset({
    ".gitignore", ".env.example", ".editorconfig", ".python-version", "README.md", "pyproject.toml",
    "src/ai_novel_factory/references/profile_pipeline.py",
    "src/ai_novel_factory/references/similarity_baseline.py",
    "tests/test_stage40_reference_integration.py",
    "docs/stage40_reference_analysis_integration.md",
    "docs/stage40_test_results.json",
    "src/ai_novel_factory/database/novel_bible.py",
    "src/ai_novel_factory/database/novel_bible_cli.py",
    "tests/test_stage41_novel_bible.py",
    "docs/stage41_novel_bible.md",
    "docs/stage41_test_results.json",
    "src/ai_novel_factory/database/characters.py",
    "src/ai_novel_factory/database/character_cli.py",
    "tests/test_stage42_characters.py",
    "tests/test_stage42_release_verifier.py",
    "docs/stage42_characters.md",
    "docs/stage42_test_results.json",
    "src/ai_novel_factory/database/character_knowledge.py",
    "src/ai_novel_factory/database/knowledge_cli.py",
    "tests/test_stage43_character_knowledge.py",
    "tests/test_stage43_release_verifier.py",
    "docs/stage43_character_knowledge.md",
    "docs/stage43_test_results.json",
    "src/ai_novel_factory/database/world_canon.py",
    "src/ai_novel_factory/database/world_cli.py",
    "tests/test_stage44_world_canon.py",
    "tests/test_stage44_release_verifier.py",
    "docs/stage44_world_canon.md",
    "docs/stage44_test_results.json",
    "src/ai_novel_factory/database/relationships.py",
    "src/ai_novel_factory/database/relationship_cli.py",
    "tests/test_stage45_relationships.py",
    "tests/test_stage45_release_verifier.py",
    "docs/stage45_relationship_timeline.md",
    "docs/stage45_test_results.json",
    "src/ai_novel_factory/database/event_timeline.py",
    "src/ai_novel_factory/database/event_cli.py",
    "tests/test_stage46_event_timeline.py",
    "tests/test_stage46_release_verifier.py",
    "docs/stage46_event_timeline.md",
    "docs/stage46_test_results.json",
    "src/ai_novel_factory/database/foreshadow.py",
    "src/ai_novel_factory/database/foreshadow_cli.py",
    "tests/test_stage47_foreshadow.py",
    "tests/test_stage47_release_verifier.py",
    "docs/stage47_foreshadow.md",
    "docs/stage47_test_results.json",
    "docs/stage47_verification_log.txt",
    "src/ai_novel_factory/database/style_bible.py",
    "src/ai_novel_factory/database/style_cli.py",
    "tests/test_stage48_style_bible.py",
    "tests/test_stage48_release_verifier.py",
    "docs/stage48_style_bible.md",
    "docs/stage48_test_results.json",
    "docs/stage48_verification_log.txt",
    "src/ai_novel_factory/database/episodes.py",
    "src/ai_novel_factory/database/episode_cli.py",
    "tests/test_stage49_episodes.py",
    "tests/test_stage49_release_verifier.py",
    "docs/stage49_episodes.md",
    "docs/stage49_test_results.json",
    "docs/stage49_verification_log.txt",
})
ROOTS = frozenset({"src", "tests", "docs", "scripts", "packaging"})
TOP_FILES = frozenset({".gitignore", ".python-version", ".editorconfig",
                       ".env.example", "README.md", "pyproject.toml"})
PRIVATE_SEGMENTS = frozenset({".git", ".github", "__pycache__", "secrets", "user_data",
                              "manuscripts", "reference_uploads", "build", "dist"})
PRIVATE_SUFFIXES = (".sqlite3", ".db", ".log", ".pyc", ".pyo", ".pem", ".key", ".spec")
# Stage 85 included six fixed, non-sensitive unittest progress lines under .log.
# Preserve historical bytes only after strict content validation; arbitrary .log remains forbidden.
LEGACY_TEST_LOGS = frozenset(
    f"docs/stage85_worktree_driver_part{i}_background.log" for i in range(3, 9)
)
LEGACY_TEST_LINE = re.compile(rb"group [3-8]: total=\d{1,6}, skipped=\d{1,6}, exit=0, ok=True\n\Z")
MAX_FILES = 3000
MAX_ENTRY_BYTES = 20_000_000
MAX_TOTAL_BYTES = 80_000_000


def verify_archive(path: str | Path) -> tuple[str, ...]:
    """Return only fixed safe problem categories (never filenames or contents)."""
    issues: set[str] = set()
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= MAX_FILES:
                issues.add("invalid_entry_count")
            seen: set[str] = set()
            total = 0
            for info in entries:
                name = info.filename
                segments = name.rstrip("/").split("/")
                if (not name or name.startswith("/") or "\\" in name or "\x00" in name
                        or any(segment in {"", ".", ".."} for segment in segments)):
                    issues.add("unsafe_archive_path")
                    continue
                if name in seen:
                    issues.add("duplicate_entry")
                seen.add(name)
                if (segments[0] not in ROOTS and name not in TOP_FILES) or (
                    len(segments) == 1 and segments[0] in ROOTS and not info.is_dir()
                ):
                    issues.add("unexpected_archive_entry")
                if any(segment in PRIVATE_SEGMENTS for segment in segments) or (
                    name != ".env.example" and any(segment.startswith(".env") for segment in segments)
                ) or (name.lower().endswith(PRIVATE_SUFFIXES)
                      and name != "packaging/windows/AI_Novel_Factory.spec"
                      and name not in LEGACY_TEST_LOGS):
                    issues.add("private_or_build_artifact")
                if name in LEGACY_TEST_LOGS:
                    if info.file_size > 128 or not LEGACY_TEST_LINE.fullmatch(archive.read(info)):
                        issues.add("private_or_build_artifact")
                if stat.S_ISLNK(info.external_attr >> 16):
                    issues.add("symlink_entry")
                if info.file_size > MAX_ENTRY_BYTES:
                    issues.add("oversize_entry")
                total += info.file_size
            if total > MAX_TOTAL_BYTES:
                issues.add("oversize_archive")
            if not REQUIRED.issubset(seen):
                issues.add("missing_required_source")
            # Never decompress an archive whose declared limits/path checks failed.
            if not issues and archive.testzip() is not None:
                issues.add("corrupt_archive_member")
    except (BadZipFile, OSError, EOFError, ValueError, RuntimeError):
        issues.add("unreadable_archive")
    return tuple(sorted(issues))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="오프라인 누적 개발 ZIP 검증")
    parser.add_argument("archive", help="검증할 로컬 ZIP 경로")
    args = parser.parse_args(argv)
    problems = verify_archive(args.archive)
    if problems:
        print("FAIL: " + ", ".join(problems))
        return 1
    print("PASS: cumulative source ZIP integrity, privacy and required files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
