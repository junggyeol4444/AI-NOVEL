"""Offline Style Bible CLI; private text hidden unless --reveal is requested."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .novel_bible import NovelBibleError
from .novel_bible_cli import _stat_file
from .world_cli import _read
from .style_bible import StyleBibleStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 Style Bible 관리 (네트워크 없음)")
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("style-set", "style-show", "style-list", "style-delete", "context"):
        command = commands.add_parser(action)
        command.add_argument("project_id")
        if action in ("style-set", "style-show", "style-delete"):
            command.add_argument("key")
        if action == "style-set":
            command.add_argument("--directive-file", type=Path, required=True)
            command.add_argument("--revision", type=int)
        if action == "style-delete":
            command.add_argument("--revision", type=int, required=True)
        if action in ("style-show", "context"):
            command.add_argument("--reveal", action="store_true")
        if action == "context":
            command.add_argument("--statistics-file", type=Path)
    args = parser.parse_args(argv)
    try:
        with StyleBibleStore(args.database) as store:
            if args.action == "style-set":
                item = store.save_style_rule(args.project_id, args.key,
                    _read(args.directive_file), expected_revision=args.revision)
                print("saved", item.key, "revision", item.revision)
            elif args.action == "style-show":
                item = store.get_style_rule(args.project_id, args.key)
                print(item.key, "revision", item.revision)
                print(item.directive if args.reveal else "[redacted: use --reveal]")
            elif args.action == "style-list":
                for item in store.list_style_rules(args.project_id):
                    print(item.key, "revision", item.revision)
            elif args.action == "style-delete":
                store.delete_style_rule(args.project_id, args.key,
                                        expected_revision=args.revision)
                print("deleted")
            elif args.action == "context":
                stats = _stat_file(args.statistics_file) if args.statistics_file else None
                context = store.build_generation_context(args.project_id, stats)
                if args.reveal:
                    print(context.to_json())  # explicit local sensitive export
                else:
                    print("project revision", context.project_revision)
                    for field in context.fields:
                        print(field.key, field.source)
                    print("style overrides", len(context.overridden_style_keys))
                    print("reference overrides", len(context.overridden_reference_keys))
        return 0
    except (NovelBibleError, OSError, sqlite3.Error, UnicodeError):
        print("ERROR: 로컬 Style Bible 작업이 실패했습니다. 입력값과 버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
