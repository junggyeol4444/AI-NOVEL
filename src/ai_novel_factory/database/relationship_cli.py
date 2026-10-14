"""Offline, explicit Novel Bible relationship timeline CLI (redacted by default)."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .novel_bible import NovelBibleError
from .novel_bible_cli import _local_text_file
from .relationships import RelationshipStore


def _read(path: Path | None) -> str | None:
    if path is None:
        return None
    if str(path).startswith(("\\\\", "//", "file:")):
        raise NovelBibleError("원격 경로나 파일 URI는 입력할 수 없습니다.")
    return _local_text_file(path, 8192)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 Novel Bible 인물 관계 회차별 관리")
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("relationship-set", "relationship-show", "relationship-history",
                   "relationship-list", "relationship-delete"):
        cmd = commands.add_parser(action)
        cmd.add_argument("project_id")
        if action != "relationship-list":
            cmd.add_argument("first_character_id")
            cmd.add_argument("second_character_id")
        if action in ("relationship-set", "relationship-show", "relationship-list",
                      "relationship-delete"):
            cmd.add_argument("--episode", type=int, required=True)
        if action == "relationship-set":
            cmd.add_argument("--relationship-file", type=Path, required=True)
            cmd.add_argument("--notes-file", type=Path)
            cmd.add_argument("--revision", type=int)
        if action == "relationship-delete":
            cmd.add_argument("--revision", type=int, required=True)
        if action in ("relationship-show", "relationship-history", "relationship-list"):
            cmd.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)
    try:
        with RelationshipStore(args.database) as store:
            if args.action == "relationship-set":
                note = _read(args.notes_file)
                item = store.save_relation(args.project_id, args.first_character_id,
                    args.second_character_id, args.episode,
                    relationship=_read(args.relationship_file),
                    notes="" if note is None else note, expected_revision=args.revision)
                print("saved", "episode", item.episode, "revision", item.revision)
            elif args.action == "relationship-delete":
                store.delete_event(args.project_id, args.first_character_id,
                    args.second_character_id, args.episode, expected_revision=args.revision)
                print("deleted")
            elif args.action == "relationship-show":
                state = store.get_at(args.project_id, args.first_character_id,
                                     args.second_character_id, args.episode)
                print("status", state.status, "episode", state.requested_episode,
                      "effective_episode", state.effective_episode,
                      "revision", state.revision)
                if state.status == "recorded":
                    if args.reveal:
                        print("relationship", state.relationship)
                        print("notes", state.notes)
                    else:
                        print("[redacted: use --reveal to view local canon]")
            elif args.action == "relationship-history":
                for item in store.history(args.project_id, args.first_character_id,
                                          args.second_character_id):
                    print("episode", item.episode, "revision", item.revision)
                    if args.reveal:
                        print("relationship", item.relationship)
                        print("notes", item.notes)
            elif args.action == "relationship-list":
                for item in store.list_at(args.project_id, args.episode):
                    print(item.first_character_id, item.second_character_id,
                          "effective_episode", item.effective_episode,
                          "revision", item.revision)
                    if args.reveal:
                        print("relationship", item.relationship)
                        print("notes", item.notes)
        return 0
    except (NovelBibleError, OSError, sqlite3.Error, UnicodeError):
        print("ERROR: 로컬 관계 기록 작업이 실패했습니다. ID·회차·버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
