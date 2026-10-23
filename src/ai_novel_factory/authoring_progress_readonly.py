"""Offline read-only project progress; records are not QC or publication approvals."""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import sqlite3

class ProgressReadError(ValueError):
    """Never include author data or private paths in errors."""

@dataclass(frozen=True)
class ChapterProgress:
    number: int
    revision: int | None
    final_sha256: str = field(default="", repr=False)
    has_draft: bool = False
    has_final: bool = False
    current_check_records: int = 0
    review_receipt: str = "NOT_RECORDED"
    next_action: str = "CREATE_EPISODE"
    publication_approved: bool = False

@dataclass(frozen=True)
class ProgressOverview:
    through_episode: int
    chapters: tuple[ChapterProgress, ...]
    saved_count: int
    draft_count: int
    final_count: int
    review_receipt_count: int
    missing_count: int
    publication_approved: bool = False

def _local_uri(database_path: str | Path) -> str:
    path = Path(database_path)
    if (not path.is_absolute() or str(path).startswith(("\\\\", "//"))
            or path.is_symlink() or not path.is_file()):
        raise ProgressReadError("기존 로컬 SQLite 파일을 직접 선택하세요.")
    return path.resolve(strict=True).as_uri() + "?mode=ro"

def load_author_progress(database_path: str | Path, project_id: str,
                         *, through_episode: int = 250) -> ProgressOverview:
    if (type(project_id) is not str or not project_id
            or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise ProgressReadError("기존 작품과 1~1000화 범위를 확인하세요.")
    try:
        with sqlite3.connect(_local_uri(database_path), uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
            if db.execute("SELECT 1 FROM bible_projects WHERE project_id=?",
                          (project_id,)).fetchone() is None:
                raise ProgressReadError("선택한 SQLite에 해당 작품이 없습니다.")
            saved = {int(r["episode"]): r for r in db.execute(
                "SELECT episode, revision, draft, final_text FROM bible_episodes "
                "WHERE project_id=? AND episode BETWEEN 1 AND ? ORDER BY episode",
                (project_id, through_episode))}
            checks = {int(r["episode"]): int(r["n"]) for r in db.execute(
                "SELECT episode, COUNT(*) AS n FROM bible_episode_checks "
                "WHERE project_id=? AND episode BETWEEN 1 AND ? "
                "AND content_revision=(SELECT revision FROM bible_episodes e "
                "WHERE e.project_id=bible_episode_checks.project_id "
                "AND e.episode=bible_episode_checks.episode) GROUP BY episode",
                (project_id, through_episode))}
            has_review_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='bible_human_review_events'").fetchone() is not None
            receipts = {}
            if has_review_table:
                for r in db.execute(
                    "SELECT episode, action, revision FROM bible_human_review_events "
                    "WHERE project_id=? AND episode BETWEEN 1 AND ? ORDER BY rowid",
                    (project_id, through_episode)):
                    receipts[int(r["episode"])] = (str(r["action"]), int(r["revision"]))
    except (sqlite3.Error, OSError, UnicodeError):
        raise ProgressReadError("SQLite 읽기 전용 현황을 불러오지 못했습니다.") from None
    rows: list[ChapterProgress] = []
    for number in range(1, through_episode + 1):
        item = saved.get(number)
        if item is None:
            rows.append(ChapterProgress(number, None))
            continue
        revision = int(item["revision"])
        draft = bool((item["draft"] or "").strip())
        final = str(item["final_text"] or "")
        final_exists = bool(final.strip())
        receipt = receipts.get(number)
        receipt_state = ("RECORDED_UNVERIFIED" if receipt and
                         receipt == ("REVIEWED", revision) else
                         "REVOKED_OR_STALE" if receipt else "NOT_RECORDED")
        action = ("WRITE_DRAFT" if not draft else
                  "WRITE_OR_REVIEW_FINAL" if not final_exists else
                  "CHECK_AND_AUTHOR_REVIEW")
        rows.append(ChapterProgress(number, revision,
                                    sha256(final.encode("utf-8")).hexdigest(),
                                    draft, final_exists, checks.get(number, 0),
                                    receipt_state, action))
    chapters = tuple(rows)
    return ProgressOverview(through_episode, chapters,
                            sum(x.revision is not None for x in chapters),
                            sum(x.has_draft for x in chapters),
                            sum(x.has_final for x in chapters),
                            sum(x.review_receipt == "RECORDED_UNVERIFIED" for x in chapters),
                            sum(x.revision is None for x in chapters))

def require_current_chapter(database_path: str | Path, project_id: str,
                            chapter: ChapterProgress) -> None:
    if not isinstance(chapter, ChapterProgress) or chapter.revision is None:
        raise ProgressReadError("저장되지 않은 회차는 이동할 수 없습니다.")
    latest = load_author_progress(database_path, project_id,
                                  through_episode=chapter.number).chapters[-1]
    if (latest.revision != chapter.revision
            or latest.final_sha256 != chapter.final_sha256):
        raise ProgressReadError("원고가 변경됐습니다. 현황을 다시 조회하세요.")
