"""Offline world-canon CLI: explicit local file inputs; text redacted by default."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .novel_bible import NovelBibleError
from .novel_bible_cli import _local_text_file
from .world_canon import WORLD_CATEGORIES, WorldCanonStore


def _read(path: Path | None) -> str | None:
    if path is None:
        return None
    if str(path).startswith(("\\\\", "//", "file:")):
        raise NovelBibleError("원격 경로나 파일 URI는 입력할 수 없습니다.")
    return _local_text_file(path, 8192)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 Novel Bible 세계관 관리 (외부 서버 없음)")
    parser.add_argument("--database", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("world-create", "world-list", "world-show", "world-update", "world-delete"):
        command = actions.add_parser(action)
        command.add_argument("project_id")
        if action in ("world-show", "world-update", "world-delete"):
            command.add_argument("entry_id")
        if action in ("world-create", "world-list", "world-update"):
            command.add_argument("--category", choices=sorted(WORLD_CATEGORIES),
                                 required=action == "world-create")
        if action in ("world-create", "world-update"):
            command.add_argument("--name-file", type=Path, required=action == "world-create")
            command.add_argument("--description-file", type=Path,
                                 required=action == "world-create")
        if action in ("world-update", "world-delete"):
            command.add_argument("--revision", type=int, required=True)
        if action == "world-show":
            command.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)
    try:
        with WorldCanonStore(args.database) as store:
            if args.action == "world-create":
                entry = store.create_entry(args.project_id, category=args.category,
                    name=_read(args.name_file), description=_read(args.description_file))
                print("created", entry.entry_id, "category", entry.category,
                      "revision", entry.revision)
            elif args.action == "world-list":
                for entry in store.list_entries(args.project_id, category=args.category):
                    print(entry.entry_id, "category", entry.category,
                          "revision", entry.revision)
            elif args.action == "world-show":
                entry = store.get_entry(args.project_id, args.entry_id)
                print(entry.entry_id, "category", entry.category,
                      "revision", entry.revision)
                if args.reveal:
                    print("name", entry.name)
                    print("description", entry.description)
                else:
                    print("[redacted: use --reveal to view local world canon]")
            elif args.action == "world-update":
                entry = store.update_entry(args.project_id, args.entry_id,
                    expected_revision=args.revision, category=args.category,
                    name=_read(args.name_file), description=_read(args.description_file))
                print("saved", entry.entry_id, "category", entry.category,
                      "revision", entry.revision)
            elif args.action == "world-delete":
                store.delete_entry(args.project_id, args.entry_id,
                                   expected_revision=args.revision)
                print("deleted")
        return 0
    except (NovelBibleError, OSError, sqlite3.Error, UnicodeError):
        print("ERROR: 로컬 세계관 설정 작업이 실패했습니다. ID·종류·버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
