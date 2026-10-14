"""Stage 49 offline episode CLI. Manuscript contents are redacted by default."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .episodes import EpisodeStore, CHECK_OUTCOMES
from .novel_bible import NovelBibleError
from .novel_bible_cli import _local_text_file


def _read(path: Path | None, limit: int) -> str | None:
    if path is None:
        return None
    if str(path).startswith(("\\\\", "//", "file:")):
        raise NovelBibleError("로컬 파일만 사용할 수 있습니다.")
    return _local_text_file(path, limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="회차 플롯·장면·원고·요약·수동 검사 기록 (오프라인)")
    parser.add_argument("--database", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("episode-create", "episode-list", "episode-show", "episode-set",
                 "episode-delete", "scene-add", "scene-list", "scene-set", "scene-delete",
                 "check-add", "check-list"):
        cmd = actions.add_parser(name)
        cmd.add_argument("project_id")
        if name != "episode-list":
            cmd.add_argument("episode", type=int)
        if name in ("scene-set", "scene-delete"):
            cmd.add_argument("scene_id")
        if name in ("episode-set", "episode-delete", "scene-add", "scene-set",
                    "scene-delete", "check-add"):
            cmd.add_argument("--revision", type=int, required=True)
        if name == "episode-create":
            cmd.add_argument("--plot-file", type=Path)
        if name == "episode-set":
            for field in ("plot", "draft", "final", "summary"):
                cmd.add_argument(f"--{field}-file", type=Path)
        if name in ("scene-add", "scene-set"):
            cmd.add_argument("--position", type=int, required=name == "scene-add")
            cmd.add_argument("--text-file", type=Path, required=name == "scene-add")
        if name == "check-add":
            cmd.add_argument("--category", required=True)
            cmd.add_argument("--outcome", choices=sorted(CHECK_OUTCOMES), required=True)
            cmd.add_argument("--note-file", type=Path)
        if name == "episode-show":
            cmd.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)
    try:
        with EpisodeStore(args.database) as store:
            if args.action == "episode-create":
                record = store.create_episode(args.project_id, args.episode,
                    plot=_read(args.plot_file, 80_000) or "")
                print("created episode", record.episode, "revision", record.revision)
            elif args.action == "episode-list":
                for record in store.list_episodes(args.project_id):
                    print("episode", record.episode, "revision", record.revision)
            elif args.action == "episode-show":
                print(store.snapshot(args.project_id, args.episode).to_json(reveal=args.reveal))
            elif args.action == "episode-set":
                changes = {}
                for key, limit in (("plot", 80_000), ("draft", 500_000),
                                   ("final", 500_000), ("summary", 80_000)):
                    value = _read(getattr(args, f"{key}_file"), limit)
                    if value is not None:
                        changes["final_text" if key == "final" else key] = value
                record = store.update_episode(args.project_id, args.episode,
                    expected_revision=args.revision, **changes)
                print("saved episode", record.episode, "revision", record.revision)
            elif args.action == "episode-delete":
                store.delete_episode(args.project_id, args.episode, expected_revision=args.revision)
                print("deleted")
            elif args.action == "scene-add":
                scene = store.add_scene(args.project_id, args.episode, args.position,
                    _read(args.text_file, 80_000), expected_revision=args.revision)
                print("created scene", scene.scene_id, "position", scene.position)
            elif args.action == "scene-list":
                for scene in store.list_scenes(args.project_id, args.episode):
                    print("scene", scene.scene_id, "position", scene.position)
            elif args.action == "scene-set":
                scene = store.update_scene(args.project_id, args.episode, args.scene_id,
                    expected_revision=args.revision, position=args.position,
                    text=_read(args.text_file, 80_000))
                print("saved scene", scene.scene_id, "position", scene.position)
            elif args.action == "scene-delete":
                store.delete_scene(args.project_id, args.episode, args.scene_id,
                                   expected_revision=args.revision)
                print("deleted")
            elif args.action == "check-add":
                check = store.add_check(args.project_id, args.episode, args.category,
                    args.outcome, _read(args.note_file, 8192) or "",
                    expected_revision=args.revision)
                print("created manual check", check.check_id, "content revision", check.content_revision)
            elif args.action == "check-list":
                current = store.get_episode(args.project_id, args.episode)
                for check in store.list_checks(args.project_id, args.episode):
                    print("manual check", check.check_id, check.category, check.outcome,
                          "revision", check.content_revision,
                          "stale", check.content_revision != current.revision)
        return 0
    except (NovelBibleError, OSError, sqlite3.Error, UnicodeError):
        print("ERROR: 로컬 회차 작업 실패. 작품·회차·버전·파일을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
