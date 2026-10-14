"""Offline command-line viewer usable without PySide6 or a server.

Example:
  python -m ai_novel_factory.references.profile_cli --database ./profile.db import book.txt
  python -m ai_novel_factory.references.profile_cli --database ./profile.db list
  python -m ai_novel_factory.references.profile_cli --database ./profile.db show <reference-id>
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ai_novel_factory.database import CatalogError, ReferenceCatalog
from ai_novel_factory.database.reference_profiles import ProfileStorageError, ReferenceProfileStore
from .plaintext_parser import ReferenceParseError
from .profile_pipeline import import_reference_profile
from .reference_profile import render_reference_profile
from .profile_collection import combine_saved_profiles, render_profile_collection
from .genre_patterns import GENRE_NAMES, render_genre_pattern
from ai_novel_factory.database.genre_patterns import GenreStorageError, GenrePatternStore
from ai_novel_factory.database.pattern_strengths import (PatternStrengthStore, PatternStrengthStorageError)
from .pattern_strength import (PatternStrengthError, preview_strengths, render_strength_preview)
from ai_novel_factory.database.element_selections import (ElementSelectionStore, ElementSelectionStorageError)
from .element_selection import (FEATURE_KEYS, ElementSelectionError, render_element_selection)
from .pattern_library import (
    PatternLibraryError, ReferencePatternLibrary, render_library_page, render_library_comparison,
)

from .related_pattern_search import (RelatedPatternSearch, RelatedPatternError, render_related_patterns)
from ai_novel_factory.database.pattern_usage import (
    PatternUsageStore, PatternUsageError, render_usage_record,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Novel Factory: 완전 오프라인 참고작 프로필")
    parser.add_argument("--database", type=Path, required=True, help="사용자 PC의 SQLite DB 파일 경로")
    actions = parser.add_subparsers(dest="action", required=True)
    importer = actions.add_parser("import", help="참고작 파일 분석·등록")
    importer.add_argument("file", type=Path)
    importer.add_argument("--encoding", default=None)
    actions.add_parser("list", help="등록된 분석 프로필 목록")
    viewer = actions.add_parser("show", help="프로필 보고서 표시")
    viewer.add_argument("reference_id")
    viewer.add_argument("--episodes", type=int, default=30)
    compare = actions.add_parser("compare", help="저장된 2~50개 프로필을 오프라인 통합 분석")
    compare.add_argument("reference_ids", nargs="+", help="list에서 확인한 서로 다른 참고작 ID")
    compare.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    delete = actions.add_parser("delete", help="원본/메타데이터는 유지하고 통계 프로필만 삭제")
    delete.add_argument("reference_id")
    genre_assign = actions.add_parser("genre-assign", help="사용자가 프로필의 장르를 직접 지정")
    genre_assign.add_argument("reference_id")
    genre_assign.add_argument("genre", choices=tuple(GENRE_NAMES))
    genre_unassign = actions.add_parser("genre-unassign", help="장르 분류 해제")
    genre_unassign.add_argument("reference_id")
    genre_tags = actions.add_parser("genre-tags", help="장르 분류된 참고작 ID 조회")
    genre_tags.add_argument("--genre", choices=tuple(GENRE_NAMES), default=None)
    genre_build = actions.add_parser("genre-build", help="장르별 통계 패턴 구성·선정정보 로컬 저장")
    genre_build.add_argument("genre", choices=tuple(GENRE_NAMES))
    genre_build.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    genre_show = actions.add_parser("genre-show", help="저장한 장르 패턴 오프라인 재계산·표시")
    genre_show.add_argument("genre", choices=tuple(GENRE_NAMES))
    genre_show.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    actions.add_parser("genre-list", help="장르 패턴 선정 목록")
    genre_delete = actions.add_parser("genre-delete", help="장르 선정 정보만 삭제")
    genre_delete.add_argument("genre", choices=tuple(GENRE_NAMES))
    genre_delete.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    library_list = actions.add_parser("pattern-list", help="원문 없는 저장 장르 패턴 라이브러리 검색")
    library_list.add_argument("--search", default="", help="장르 코드·한글 이름·가중치에서만 검색")
    library_list.add_argument("--genre", choices=tuple(GENRE_NAMES), default=None)
    library_list.add_argument("--weighting", choices=("equal", "characters"), default=None)
    library_list.add_argument("--status", choices=("all", "current", "stale"), default="all")
    library_list.add_argument("--limit", type=int, default=50)
    library_list.add_argument("--offset", type=int, default=0)
    library_show = actions.add_parser("pattern-show", help="라이브러리의 최신 장르 패턴 상세 표시")
    library_show.add_argument("genre", choices=tuple(GENRE_NAMES))
    library_show.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    library_compare = actions.add_parser("pattern-compare", help="서로 다른 2~12개 장르 패턴 평균 비교")
    library_compare.add_argument("genres", nargs="+", choices=tuple(GENRE_NAMES))
    library_compare.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    strength_set = actions.add_parser("strength-set", help="참고작별 통계 패턴 강도 0~100 저장")
    strength_set.add_argument("reference_id")
    strength_set.add_argument("strength", type=int)
    strength_show = actions.add_parser("strength-show", help="참고작별 강도 확인 (미설정은 50)")
    strength_show.add_argument("reference_id")
    strength_reset = actions.add_parser("strength-reset", help="강도 기본값 50으로 초기화")
    strength_reset.add_argument("reference_id")
    actions.add_parser("strength-list", help="사용자가 변경한 강도 설정 목록")
    strength_preview = actions.add_parser("strength-preview", help="장르 패턴 강도에 따른 익명 통계 미리보기")
    strength_preview.add_argument("genre", choices=tuple(GENRE_NAMES))
    strength_preview.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    element_save = actions.add_parser("elements-save", help="장르별로 참고할 통계 요소 1~6개만 선택·저장")
    element_save.add_argument("genre", choices=tuple(GENRE_NAMES))
    element_save.add_argument("keys", nargs="+", help="허용된 고정 통계 항목 코드만 사용")
    element_save.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    element_show = actions.add_parser("elements-show", help="저장된 통계 요소 선택 확인 (구성·강도 재검증)")
    element_show.add_argument("genre", choices=tuple(GENRE_NAMES))
    element_show.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    actions.add_parser("elements-list", help="선택된 참고 요소 레시피와 유효성 확인")
    element_delete = actions.add_parser("elements-delete", help="선택 설정만 삭제 (원본 분석 데이터 유지)")
    element_delete.add_argument("genre", choices=tuple(GENRE_NAMES))
    element_delete.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    related = actions.add_parser("pattern-related", help="저장된 참고 요소로 관련 장르 통계 패턴 검색")
    related.add_argument("genre", choices=tuple(GENRE_NAMES))
    related.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    related.add_argument("--limit", type=int, default=10)
    related.add_argument("--min-similarity", type=float, default=0.0)
    usage_add = actions.add_parser("usage-add", help="사용자가 선택한 패턴 통계 사용 기록 추가")
    usage_add.add_argument("genre", choices=tuple(GENRE_NAMES))
    usage_add.add_argument("--pattern-genre", choices=tuple(GENRE_NAMES), default=None)
    usage_add.add_argument("--weighting", choices=("equal", "characters"), default="equal")
    usage_list = actions.add_parser("usage-list", help="원문 없는 로컬 패턴 사용 이력 조회")
    usage_list.add_argument("--genre", choices=tuple(GENRE_NAMES), default=None)
    usage_list.add_argument("--pattern-genre", choices=tuple(GENRE_NAMES), default=None)
    usage_list.add_argument("--status", choices=("all", "current", "stale"), default="all")
    usage_list.add_argument("--limit", type=int, default=50)
    usage_list.add_argument("--offset", type=int, default=0)
    usage_show = actions.add_parser("usage-show", help="한 건의 패턴 사용 기록 확인")
    usage_show.add_argument("usage_id")
    usage_delete = actions.add_parser("usage-delete", help="기록 한 건만 명시적으로 삭제")
    usage_delete.add_argument("usage_id")
    args = parser.parse_args(argv)
    try:
        with ReferenceCatalog(args.database) as catalog:
            store = ReferenceProfileStore(catalog)
            if args.action == "import":
                result = import_reference_profile(args.file, catalog=catalog, encoding=args.encoding)
                print(f"등록 ID: {result.reference.reference_id}")
                print(render_reference_profile(result.profile))
            elif args.action == "list":
                for row in store.list():
                    print(f"{row.reference_id}  {row.file_name}  {row.episode_count}화  {row.status}")
                print(f"분석 프로필: {store.count()}개")
            elif args.action == "show":
                # Only the already registered basename is displayed.
                record = catalog.get(args.reference_id)
                print(f"참고작: {record.file_name}")
                print(render_reference_profile(store.get(args.reference_id), episode_limit=args.episodes))
            elif args.action == "compare":
                result = combine_saved_profiles(store, args.reference_ids, weighting=args.weighting)
                print(render_profile_collection(result))
            elif args.action.startswith("usage-"):
                usage = PatternUsageStore(catalog)
                if args.action == "usage-add":
                    print(render_usage_record(usage.record(
                        args.genre, pattern_genre=args.pattern_genre, weighting=args.weighting)))
                elif args.action == "usage-show":
                    print(render_usage_record(usage.get(args.usage_id)))
                elif args.action == "usage-list":
                    wanted = {"all": None, "current": True, "stale": False}[args.status]
                    for entry in usage.list(source_genre=args.genre, pattern_genre=args.pattern_genre,
                                            current=wanted, limit=args.limit, offset=args.offset):
                        status = "최신" if entry.current else "재검토 필요"
                        print(f"{entry.usage_id}  {entry.source_genre} -> {entry.pattern_genre}  "
                              f"{entry.weighting}  {status}  {entry.created_at}")
                elif args.action == "usage-delete":
                    print("사용 기록 삭제됨" if usage.delete(args.usage_id) else "사용 기록 없음")
            elif args.action == "pattern-related":
                result = RelatedPatternSearch(catalog).search(
                    args.genre, weighting=args.weighting, limit=args.limit,
                    min_similarity=args.min_similarity)
                print(render_related_patterns(result))
            elif args.action.startswith("elements-"):
                selections = ElementSelectionStore(catalog)
                if args.action == "elements-save":
                    print(render_element_selection(selections.save(
                        args.genre, args.keys, weighting=args.weighting)))
                elif args.action == "elements-show":
                    print(render_element_selection(selections.get(
                        args.genre, weighting=args.weighting)))
                elif args.action == "elements-list":
                    for entry in selections.list():
                        status = "사용 가능" if entry.current else "재구축·강도 재설정 필요"
                        print(f"{entry.genre}  {entry.weighting}  {','.join(entry.selected_keys)}  {status}")
                elif args.action == "elements-delete":
                    print("삭제됨" if selections.delete(args.genre, weighting=args.weighting)
                          else "선택 설정 없음")
            elif args.action.startswith("strength-"):
                strengths = PatternStrengthStore(catalog)
                if args.action == "strength-set":
                    strengths.set(args.reference_id, args.strength)
                    print(f"강도 저장 완료: {args.reference_id} = {args.strength}")
                elif args.action == "strength-show":
                    print(f"{args.reference_id}: {strengths.get(args.reference_id)}")
                elif args.action == "strength-reset":
                    strengths.reset(args.reference_id)
                    print(f"강도 기본값 복원: {args.reference_id} = 50")
                elif args.action == "strength-list":
                    for entry in strengths.list_overrides():
                        print(f"{entry.reference_id}: {entry.strength}")
                elif args.action == "strength-preview":
                    print(render_strength_preview(preview_strengths(
                        GenrePatternStore(catalog), strengths, args.genre,
                        weighting=args.weighting)))
            elif args.action.startswith("pattern-"):
                library = ReferencePatternLibrary(GenrePatternStore(catalog))
                if args.action == "pattern-list":
                    status = {"all": None, "current": True, "stale": False}[args.status]
                    print(render_library_page(library.search(
                        query=args.search, genre=args.genre, weighting=args.weighting,
                        current=status, limit=args.limit, offset=args.offset)))
                elif args.action == "pattern-show":
                    print(render_genre_pattern(library.get(args.genre, weighting=args.weighting)))
                elif args.action == "pattern-compare":
                    print(render_library_comparison(library.compare(
                        args.genres, weighting=args.weighting)))
            elif args.action.startswith("genre-"):
                genres = GenrePatternStore(catalog)
                if args.action == "genre-assign":
                    genres.assign(args.reference_id, args.genre)
                    print(f"장르 지정 완료: {args.genre}")
                elif args.action == "genre-unassign":
                    print("해제됨" if genres.unassign(args.reference_id) else "지정된 장르 없음")
                elif args.action == "genre-tags":
                    for ref, genre in genres.list_assignments(args.genre):
                        print(f"{ref}  {genre}")
                elif args.action == "genre-build":
                    print(render_genre_pattern(genres.build(args.genre, weighting=args.weighting)))
                elif args.action == "genre-show":
                    print(render_genre_pattern(genres.get(args.genre, weighting=args.weighting)))
                elif args.action == "genre-list":
                    for entry in genres.list_patterns():
                        state = "최신 구성" if entry.current else "재구축 필요"
                        print(f"{entry.genre}  {entry.weighting}  {entry.reference_count}개  {state}")
                elif args.action == "genre-delete":
                    print("삭제됨" if genres.delete(args.genre, weighting=args.weighting)
                          else "저장된 장르 패턴 없음")
            else:
                print("삭제됨" if store.delete(args.reference_id) else "등록된 프로필 없음")
        return 0
    except (CatalogError, ProfileStorageError, ReferenceParseError, GenreStorageError, PatternLibraryError, PatternStrengthStorageError, PatternStrengthError,
            ElementSelectionStorageError, ElementSelectionError, RelatedPatternError, PatternUsageError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
