"""Stage 47 offline CLI: authored titles and notes are redacted by default."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .foreshadow import ForeshadowStore, ForeshadowError
from .novel_bible import NovelBibleError
from .novel_bible_cli import _local_text_file


def _read(path: Path | None, *, title: bool = False) -> str:
    if path is None:
        return ""
    value = _local_text_file(path, 8192)
    return value.rstrip("\r\n") if title else value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="오프라인 Novel Bible 복선 관리")
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("thread-create", "thread-list", "thread-show", "thread-update",
                 "thread-delete", "thread-status", "thread-history", "event-add",
                 "event-update", "event-delete", "foreshadow-audit"):
        cmd = commands.add_parser(name)
        cmd.add_argument("project_id")
        if name not in ("thread-create", "thread-list", "foreshadow-audit"):
            cmd.add_argument("thread_id")
        if name in ("event-update", "event-delete"):
            cmd.add_argument("event_id")
        if name in ("thread-create", "thread-update"):
            cmd.add_argument("--title-file", type=Path, required=True)
        if name in ("thread-create", "thread-status", "event-add", "event-update"):
            cmd.add_argument("--episode", type=int, required=True)
        if name in ("event-add", "event-update"):
            cmd.add_argument("--event-action", choices=("REVISIT", "RESOLVE", "ABANDON"),
                             required=True)
        if name in ("thread-create", "event-add", "event-update"):
            cmd.add_argument("--note-file", type=Path)
        if name in ("thread-update", "thread-delete", "event-add", "event-update", "event-delete"):
            cmd.add_argument("--revision", type=int, required=True)
        if name in ("thread-show", "thread-history"):
            cmd.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)
    try:
        with ForeshadowStore(args.database) as store:
            if args.action == "thread-create":
                obj = store.create_thread(args.project_id, title=_read(args.title_file, title=True),
                    episode=args.episode, note=_read(args.note_file))
                print("created", obj.thread_id, "revision", obj.revision)
            elif args.action == "thread-list":
                for obj in store.list_threads(args.project_id):
                    print("thread", obj.thread_id, "revision", obj.revision)
            elif args.action == "thread-show":
                obj = store.get_thread(args.project_id, args.thread_id)
                print("thread", obj.thread_id, "revision", obj.revision)
                if args.reveal:
                    print("title", obj.title)
            elif args.action == "thread-update":
                obj = store.update_thread(args.project_id, args.thread_id,
                    title=_read(args.title_file, title=True), expected_revision=args.revision)
                print("saved", obj.thread_id, "revision", obj.revision)
            elif args.action == "thread-delete":
                store.delete_thread(args.project_id, args.thread_id,
                    expected_revision=args.revision)
                print("deleted")
            elif args.action == "thread-status":
                obj = store.get_at(args.project_id, args.thread_id, args.episode)
                print("status", obj.status, "effective_episode", obj.effective_episode,
                      "revision", obj.revision)
            elif args.action == "thread-history":
                store.audit(args.project_id)
                for event in store.history(args.project_id, args.thread_id):
                    print("event", event.event_id, "episode", event.episode,
                          "action", event.action)
                    if args.reveal:
                        print("note", event.note)
            elif args.action == "event-add":
                obj = store.add_event(args.project_id, args.thread_id, episode=args.episode,
                    action=args.event_action, note=_read(args.note_file),
                    expected_revision=args.revision)
                print("saved", obj.event_id)
            elif args.action == "event-update":
                obj = store.update_event(args.project_id, args.thread_id, args.event_id,
                    episode=args.episode, action=args.event_action, note=_read(args.note_file),
                    expected_revision=args.revision)
                print("saved", obj.event_id)
            elif args.action == "event-delete":
                store.delete_event(args.project_id, args.thread_id, args.event_id,
                    expected_revision=args.revision)
                print("deleted")
            elif args.action == "foreshadow-audit":
                report = store.audit(args.project_id)
                print("PASS", "threads", report.thread_count, "events", report.event_count,
                    "OPEN", report.open_count, "DEVELOPING", report.developing_count,
                    "RESOLVED", report.resolved_count, "ABANDONED", report.abandoned_count)
        return 0
    except (NovelBibleError, ForeshadowError, sqlite3.Error, OSError, UnicodeError):
        print("ERROR: 로컬 복선 기록 작업이 실패했습니다. 입력과 버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
