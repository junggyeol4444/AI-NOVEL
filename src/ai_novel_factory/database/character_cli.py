"""Offline character canon CLI: redacted by default, explicit file inputs."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .characters import CharacterError, CharacterStore
from .novel_bible import NovelBibleError
from .novel_bible_cli import _local_text_file


def _read(path: Path | None) -> str | None:
    return None if path is None else _local_text_file(path, 8192)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 Novel Bible 인물 관리 (외부 서버 없음)")
    parser.add_argument("--database", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("character-create", "character-list", "character-show",
                   "character-update", "character-delete"):
        command = actions.add_parser(action)
        command.add_argument("project_id")
        if action in ("character-show", "character-update", "character-delete"):
            command.add_argument("character_id")
        if action in ("character-create", "character-update"):
            for field in ("name", "personality", "goal", "speech", "secret"):
                command.add_argument(f"--{field}-file", type=Path,
                                     required=(action == "character-create" and field != "secret"))
        if action in ("character-update", "character-delete"):
            command.add_argument("--revision", type=int, required=True)
        if action == "character-show":
            command.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)
    try:
        with CharacterStore(args.database) as store:
            if args.action == "character-create":
                obj = store.create_character(
                    args.project_id, name=_read(args.name_file),
                    personality=_read(args.personality_file), goal=_read(args.goal_file),
                    speech_style=_read(args.speech_file), secret=_read(args.secret_file) or "")
                print("created", obj.character_id, "revision", obj.revision)
            elif args.action == "character-list":
                for obj in store.list_characters(args.project_id):
                    print(obj.character_id, "revision", obj.revision)
            elif args.action == "character-show":
                obj = store.get_character(args.project_id, args.character_id)
                print(obj.character_id, "revision", obj.revision)
                if args.reveal:
                    for field in ("name", "personality", "goal", "speech_style", "secret"):
                        print(field, getattr(obj, field))
                else:
                    print("[redacted: use --reveal to view local character canon]")
            elif args.action == "character-update":
                obj = store.update_character(
                    args.project_id, args.character_id, expected_revision=args.revision,
                    name=_read(args.name_file), personality=_read(args.personality_file),
                    goal=_read(args.goal_file), speech_style=_read(args.speech_file),
                    secret=_read(args.secret_file))
                print("saved", obj.character_id, "revision", obj.revision)
            elif args.action == "character-delete":
                store.delete_character(args.project_id, args.character_id,
                                       expected_revision=args.revision)
                print("deleted")
        return 0
    except (NovelBibleError, CharacterError, OSError, sqlite3.Error):
        print("ERROR: 로컬 인물 설정 작업이 실패했습니다. 입력값과 버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
