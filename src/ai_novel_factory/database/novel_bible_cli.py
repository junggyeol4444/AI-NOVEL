"""Local-only Stage 41 CLI. Canon values are redacted unless explicitly revealed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .novel_bible import NovelBibleError, NovelBibleStore


def _local_text_file(path: Path, limit: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise NovelBibleError("입력 파일이 없거나 허용된 크기를 초과했습니다.")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise NovelBibleError("UTF-8 로컬 입력 파일을 읽을 수 없습니다.") from None


def _stat_file(path: Path):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise NovelBibleError("통계 항목이 중복되었습니다.")
            obj[key] = value
        return obj
    try:
        return json.loads(_local_text_file(path, 8192), object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise NovelBibleError("참고 통계 JSON 형식이 올바르지 않습니다.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Novel Bible 로컬 설정 관리 (외부 서버 없음)")
    parser.add_argument("--database", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("project-create")
    create.add_argument("title")
    actions.add_parser("project-list")
    project_delete = actions.add_parser("project-delete")
    project_delete.add_argument("project_id")
    set_rule = actions.add_parser("rule-set")
    set_rule.add_argument("project_id")
    set_rule.add_argument("key")
    set_rule.add_argument("--value-file", type=Path, required=True)
    set_rule.add_argument("--revision", type=int)
    rule_show = actions.add_parser("rule-show")
    rule_show.add_argument("project_id")
    rule_show.add_argument("key")
    rule_show.add_argument("--reveal", action="store_true")
    rule_list = actions.add_parser("rule-list")
    rule_list.add_argument("project_id")
    rule_delete = actions.add_parser("rule-delete")
    rule_delete.add_argument("project_id")
    rule_delete.add_argument("key")
    rule_delete.add_argument("--revision", type=int, required=True)
    context = actions.add_parser("context")
    context.add_argument("project_id")
    context.add_argument("--statistics-file", type=Path)
    args = parser.parse_args(argv)
    try:
        with NovelBibleStore(args.database) as store:
            if args.action == "project-create":
                print("created", store.create_project(args.title).project_id)
            elif args.action == "project-list":
                for p in store.list_projects():
                    print(p.project_id, "revision", p.revision)  # title private by default
            elif args.action == "project-delete":
                store.delete_project(args.project_id)
                print("deleted")
            elif args.action == "rule-set":
                rule = store.save_rule(args.project_id, args.key,
                                       _local_text_file(args.value_file, 8192),
                                       expected_revision=args.revision)
                print("saved", rule.key, "revision", rule.revision)
            elif args.action == "rule-show":
                rule = store.get_rule(args.project_id, args.key)
                print(rule.key, "revision", rule.revision)
                print(rule.value if args.reveal else "[redacted: use --reveal to view local canon]")
            elif args.action == "rule-list":
                for rule in store.list_rules(args.project_id):
                    print(rule.key, "revision", rule.revision)
            elif args.action == "rule-delete":
                store.delete_rule(args.project_id, args.key, expected_revision=args.revision)
                print("deleted")
            elif args.action == "context":
                stats = _stat_file(args.statistics_file) if args.statistics_file else None
                result = store.resolve_context(args.project_id, stats)
                print("project revision", result.project_revision)
                for field in result.fields:
                    print(field.key, field.source)  # no user canon text or reference prose
                print("overridden", len(result.overridden_reference_keys))
        return 0
    except (NovelBibleError, OSError):
        print("ERROR: 로컬 Novel Bible 작업이 실패했습니다. 입력값과 버전을 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
