"""작가가 직접 선택한 다섯 장편 기록과 저장 원고의 회차별 읽기 전용 대조.

이 표는 누락/변경 가능성을 표시하는 작업 도구이지 문학 품질, 사실 진위,
저작권, 모델 실행, QC PASS 또는 출판 승인 판정이 아니다. 파일/DB 쓰기 없음.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from .database.episodes import EpisodeStore
from .author_arc_ledger import read_author_arcs, arc_ledger_fingerprint, canon_fingerprint
from .author_scene_plan import read_author_scene_plans, scene_plan_fingerprint
from .author_fact_ledger import read_author_facts, ledger_fingerprint
from .author_language_ledger import read_author_language_rules, language_ledger_fingerprint
from .author_memory_delta import list_author_memory_deltas, memory_delta_fingerprint


class ContinuityCoverageError(ValueError):
    """실제 원고·파일 경로를 오류 메시지에 넣지 않는다."""


@dataclass(frozen=True)
class ContinuityCoverageRow:
    episode: int
    revision: int | None
    final_chars: int
    arcs: int
    scene_plans: int
    facts: int
    language_rules: int
    memory_deltas: int
    stale_sources: int
    missing_sources: tuple[str, ...]


@dataclass(frozen=True)
class ContinuityCoverageSnapshot:
    project_id: str
    through_episode: int
    folders: tuple[str, str, str, str, str]
    fingerprint: str
    rows: tuple[ContinuityCoverageRow, ...]
    missing_final: int
    stale_source_count: int


def _folders(values) -> tuple[str, str, str, str, str]:
    if not isinstance(values, (list, tuple)) or len(values) != 5:
        raise ContinuityCoverageError('아크·장면·사실·말투·기억 폴더 5개를 직접 선택하세요.')
    paths = []
    for value in values:
        if not isinstance(value, (str, Path)):
            raise ContinuityCoverageError('기존 로컬 기록 폴더를 직접 선택하세요.')
        path = Path(value)
        if (not path.is_absolute() or path.is_symlink() or not path.is_dir()
                or str(path).startswith(('\\\\', '//'))):
            raise ContinuityCoverageError('기존 로컬 기록 폴더를 직접 선택하세요.')
        paths.append(str(path.resolve()))
    if len(set(paths)) != 5:
        raise ContinuityCoverageError('다섯 종류의 기록 폴더를 각각 구분하여 선택하세요.')
    return tuple(paths)


def build_continuity_coverage(store: EpisodeStore, project_id: str, *,
                              through_episode: int, folders) -> ContinuityCoverageSnapshot:
    """저장 원고와 5종 작가 기록을 모두 읽고 지문을 묶는다. 쓰기 없음."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or store.get_project(project_id) is None):
        raise ContinuityCoverageError('기존 작품을 먼저 열어 주세요.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ContinuityCoverageError('조회 범위는 1~1000화입니다.')
    folders = _folders(folders)
    try:
        arcs = tuple(a for a in read_author_arcs(folders[0], project_id) if not a.withdrawn)
        scenes = tuple(p for p in read_author_scene_plans(folders[1], project_id) if not p.revoked)
        facts = tuple(f for f in read_author_facts(folders[2], project_id) if not f.retracted)
        languages = tuple(r for r in read_author_language_rules(folders[3], project_id) if not r.withdrawn)
        memories = tuple(m for m in list_author_memory_deltas(folders[4], project_id) if not m.retracted)
        stamps = (arc_ledger_fingerprint(folders[0]), scene_plan_fingerprint(folders[1]),
                  ledger_fingerprint(folders[2]), language_ledger_fingerprint(folders[3]),
                  memory_delta_fingerprint(folders[4]))
        canon = canon_fingerprint(store, project_id)
        saved = {e.episode: e for e in store.list_episodes(project_id)}
    except (ValueError, OSError, UnicodeError, TypeError):
        raise ContinuityCoverageError('작가 기록 또는 저장 원고를 읽지 못했습니다.') from None

    # 과거 근거 회차의 revision과 원고 내용이 달라지면 과거 기록은 현재 근거가 아니다.
    def source_stale(number, revision, digest):
        episode = saved.get(number)
        return (episode is None or episode.revision != revision
                or sha256(episode.final_text.encode('utf-8')).hexdigest() != digest)

    rows = []
    digest_rows = []
    for number in range(1, through_episode + 1):
        episode = saved.get(number)
        active_arcs = [a for a in arcs if a.start <= number <= a.end]
        active_scenes = [s for s in scenes if s.episode == number]
        active_facts = [f for f in facts if f.valid_from <= number <= f.valid_until]
        active_languages = [r for r in languages if r.first_episode <= number <= r.last_episode]
        active_memories = [m for m in memories if m.valid_from <= number <= m.valid_through]
        stale = sum(a.canon_sha256 != canon for a in active_arcs)
        stale += sum(s.canon_sha256 != canon or
                     (s.arc_sha256 is not None and s.arc_sha256 != stamps[0])
                     for s in active_scenes)
        stale += sum(source_stale(f.source_episode, f.source_revision, f.source_sha256)
                     for f in active_facts)
        stale += sum(r.canon_sha256 != canon for r in active_languages)
        stale += sum(source_stale(m.source_episode, m.source_revision, m.source_sha256)
                     for m in active_memories)
        missing = []
        if episode is None or not episode.final_text.strip():
            missing.append('저장 최종본')
        if not active_arcs:
            missing.append('아크 기록')
        if not active_scenes:
            missing.append('장면 설계')
        if not active_facts:
            missing.append('인물·복선·시간선 사실')
        if not active_languages:
            missing.append('표기·말투 규칙')
        if not active_memories:
            missing.append('이전 기억 변화')
        row = ContinuityCoverageRow(
            number, episode.revision if episode else None,
            len(episode.final_text) if episode else 0,
            len(active_arcs), len(active_scenes), len(active_facts),
            len(active_languages), len(active_memories), stale, tuple(missing))
        rows.append(row)
        # 지문에는 원고 내용 전체를 포함하되 화면/결과에 본문은 내보내지 않는다.
        digest_rows.append((number, episode.revision if episode else None,
                            sha256(json.dumps((episode.plot, episode.draft,
                                              episode.final_text, episode.summary),
                                             ensure_ascii=False).encode('utf-8')).hexdigest()
                            if episode else None))
    digest = sha256(json.dumps((project_id, through_episode, folders, canon,
                                stamps, digest_rows), ensure_ascii=False,
                               separators=(',', ':')).encode('utf-8')).hexdigest()
    return ContinuityCoverageSnapshot(
        project_id, through_episode, folders, digest, tuple(rows),
        sum('저장 최종본' in r.missing_sources for r in rows),
        sum(r.stale_sources for r in rows))


def require_current_continuity_coverage(snapshot: ContinuityCoverageSnapshot,
                                        store: EpisodeStore, project_id: str) -> None:
    """명시적 두 번째 클릭 시 파일·원고 지문과 범위를 모두 재확인."""
    if not isinstance(snapshot, ContinuityCoverageSnapshot) or snapshot.project_id != project_id:
        raise ContinuityCoverageError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_continuity_coverage(
        store, project_id, through_episode=snapshot.through_episode,
        folders=snapshot.folders)
    if current.fingerprint != snapshot.fingerprint or current.rows != snapshot.rows:
        raise ContinuityCoverageError('원고 또는 작가 기록이 변경됐습니다. 다시 조회하세요.')