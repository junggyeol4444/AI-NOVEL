"""Local-only knowledge canon CLI. Fact descriptions never printed by default."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from .character_knowledge import CharacterKnowledgeStore, KnowledgeError
from .novel_bible import NovelBibleError
from .novel_bible_cli import _local_text_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 인물별 회차 지식 관리 (외부 서버 없음)")
    parser.add_argument("--database", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("fact-create", "fact-list", "fact-show", "fact-delete",
                 "event-set", "event-list", "event-delete", "knowledge-at", "knowledge-check"):
        cmd = actions.add_parser(name)
        cmd.add_argument("project_id")
        if name in ("fact-show", "fact-delete"):
            cmd.add_argument("fact_id")
        if name in ("event-set", "event-list", "event-delete", "knowledge-at", "knowledge-check"):
            cmd.add_argument("character_id")
        if name in ("event-set", "event-delete", "knowledge-at"):
            cmd.add_argument("fact_id")
            cmd.add_argument("episode", type=int)
        if name == "event-list":
            cmd.add_argument("--fact-id")
        if name == "knowledge-check":
            cmd.add_argument("episode", type=int)
            cmd.add_argument("--fact-id", action="append", required=True)
        if name == "fact-create":
            cmd.add_argument("--text-file", type=Path, required=True)
        if name == "fact-show":
            cmd.add_argument("--reveal", action="store_true")
        if name in ("fact-delete", "event-delete", "event-set"):
            cmd.add_argument("--revision", type=int)
        if name == "event-set":
            flags = cmd.add_mutually_exclusive_group(required=True)
            flags.add_argument("--knows", action="store_true")
            flags.add_argument("--does-not-know", action="store_true")
    args = parser.parse_args(argv)
    try:
        with CharacterKnowledgeStore(args.database) as store:
            if args.action == "fact-create":
                fact = store.create_fact(args.project_id, _local_text_file(args.text_file, 8192))
                print("created", fact.fact_id, "revision", fact.revision)
            elif args.action == "fact-list":
                for fact in store.list_facts(args.project_id):
                    print(fact.fact_id, "revision", fact.revision)
            elif args.action == "fact-show":
                fact = store.get_fact(args.project_id, args.fact_id)
                print(fact.fact_id, "revision", fact.revision)
                print(fact.description if args.reveal else "[redacted: use --reveal to view local canon]")
            elif args.action == "fact-delete":
                if args.revision is None:
                    raise KnowledgeError("삭제에는 버전이 필요합니다.")
                store.delete_fact(args.project_id, args.fact_id, expected_revision=args.revision)
                print("deleted")
            elif args.action == "event-set":
                event = store.save_event(args.project_id, args.character_id, args.fact_id,
                                         args.episode, knows=args.knows,
                                         expected_revision=args.revision)
                print("saved", event.episode, "revision", event.revision)
            elif args.action == "event-list":
                for event in store.list_events(args.project_id, args.character_id,
                                               fact_id=args.fact_id):
                    print(event.fact_id, "episode", event.episode, "knows", event.knows,
                          "revision", event.revision)
            elif args.action == "event-delete":
                if args.revision is None:
                    raise KnowledgeError("삭제에는 버전이 필요합니다.")
                store.delete_event(args.project_id, args.character_id, args.fact_id,
                                   args.episode, expected_revision=args.revision)
                print("deleted")
            elif args.action == "knowledge-at":
                state = store.knowledge_at(args.project_id, args.character_id,
                                           args.fact_id, args.episode)
                print(state.status, "effective_episode", state.effective_episode)
            elif args.action == "knowledge-check":
                result = store.check_uses(args.project_id, args.character_id,
                                          args.episode, args.fact_id)
                if not result.allowed:
                    for violation in result.violations:
                        print("ERROR", violation.fact_id, violation.reason)
                    return 2
                print("PASS: all referenced facts known at episode")
        return 0
    except (NovelBibleError, OSError, sqlite3.Error):
        print("ERROR: 로컬 지식 기록 작업이 실패했습니다. ID와 회차·버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
