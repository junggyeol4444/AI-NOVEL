"""Offline event timeline CLI. Titles are redacted unless --reveal is supplied."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .event_timeline import EventTimelineStore, TimelineError
from .novel_bible import NovelBibleError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 Novel Bible 사건 타임라인")
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("event-add", "event-show", "event-list", "event-update",
                   "event-delete", "order-add", "order-remove", "event-audit"):
        cmd = commands.add_parser(action)
        cmd.add_argument("project_id")
        if action in ("event-show", "event-update", "event-delete"):
            cmd.add_argument("event_id")
        if action in ("order-add", "order-remove"):
            cmd.add_argument("before_id")
            cmd.add_argument("after_id")
        if action in ("event-add", "event-update"):
            cmd.add_argument("--title", required=True)
            cmd.add_argument("--when")
            cmd.add_argument("--anchor")
            cmd.add_argument("--offset-minutes", type=int)
        if action in ("event-update", "event-delete"):
            cmd.add_argument("--revision", type=int, required=True)
        if action in ("event-show", "event-list"):
            cmd.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)
    try:
        with EventTimelineStore(args.database) as store:
            if args.action == "event-add":
                item = store.create_event(args.project_id, title=args.title,
                    when=args.when, anchor_event_id=args.anchor,
                    offset_minutes=args.offset_minutes)
                print("saved", item.event_id, "revision", item.revision)
            elif args.action == "event-update":
                item = store.update_event(args.project_id, args.event_id, title=args.title,
                    when=args.when, anchor_event_id=args.anchor,
                    offset_minutes=args.offset_minutes, expected_revision=args.revision)
                print("saved", item.event_id, "revision", item.revision)
            elif args.action == "event-show":
                item = store.get_event(args.project_id, args.event_id)
                print("event", item.event_id, "revision", item.revision,
                      "when", item.when, "anchor", item.anchor_event_id,
                      "offset_minutes", item.offset_minutes)
                if args.reveal:
                    print("title", item.title)
            elif args.action == "event-list":
                for item in store.list_events(args.project_id):
                    print("event", item.event_id, "revision", item.revision,
                          "when", item.when, "anchor", item.anchor_event_id,
                          "offset_minutes", item.offset_minutes)
                    if args.reveal:
                        print("title", item.title)
            elif args.action == "event-delete":
                store.delete_event(args.project_id, args.event_id,
                                   expected_revision=args.revision)
                print("deleted")
            elif args.action == "order-add":
                report = store.add_order(args.project_id, args.before_id, args.after_id)
                print("order_saved", "precedence_count", report.precedence_count)
            elif args.action == "order-remove":
                store.remove_order(args.project_id, args.before_id, args.after_id)
                print("order_removed")
            elif args.action == "event-audit":
                report = store.audit(args.project_id)
                print("PASS", "events", report.event_count,
                      "precedence", report.precedence_count,
                      "unresolved", len(report.unresolved_event_ids),
                      "checked_pairs", report.checked_pairs)
        return 0
    except (NovelBibleError, OSError, sqlite3.Error, UnicodeError, RecursionError):
        print("ERROR: 사건 시간/순서 검사가 실패했습니다. 사건 ID·날짜·관계를 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
