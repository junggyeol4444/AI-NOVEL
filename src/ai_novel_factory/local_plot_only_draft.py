"""Finish a saved plot-only chapter with a real approved offline GGUF.

The multi-chapter authoring engine intentionally skips *all* saved episodes,
including legacy interrupted plot-only records. This fills that real gap:
the author selects exactly one already-saved, plot-only episode, requests
genuine prose from the configured local model, reviews an in-memory candidate,
and explicitly saves it as an UNAPPROVED draft. No existing scene, draft,
final, synopsis, model, reference file, or publication approval is replaced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .database.episodes import EpisodeStore, MAX_FIELD_BYTES
from .database.characters import CharacterStore
from .korean_draft_quality import has_foreign_script_corruption, screen_korean_draft
from .local_models import LocalExecutableProvider, LocalModelError, SceneDraftRequest, draft_scene
from .local_rewrite_canon_bridge import build_saved_rewrite_canon


class PlotOnlyDraftError(ValueError):
    """Sanitized error: never includes the author's text or private file paths."""


@dataclass(frozen=True)
class PlotOnlyLease:
    project_id: str
    episode: int
    episode_revision: int
    project_revision: int
    plot_sha256: str
    summary_sha256: str
    draft_sha256: str
    final_sha256: str
    scene_count: int


@dataclass(frozen=True)
class PlotOnlyDraftProposal:
    lease: PlotOnlyLease
    candidate: str = field(repr=False)
    requested_nonspace_chars: int = 5000
    resulting_nonspace_chars: int = 0
    remaining_nonspace_chars: int = 0
    model_calls: int = 0
    accepted_passages: int = 0
    stopped_by_author: bool = False
    status: str = 'UNREVIEWED_REAL_GGUF_PLOT_ONLY_CANDIDATE'
    sqlite_saved: bool = False
    final_changed: bool = False
    publication_approved: bool = False


def _digest(text: str) -> str:
    return sha256(text.encode('utf-8')).hexdigest()


def _source_lease(store: EpisodeStore, project_id: str, episode: int) -> PlotOnlyLease:
    row = store.get_episode(project_id, episode)
    scenes = store.list_scenes(project_id, episode)
    if (not row.plot.strip() or row.draft.strip()
            or row.final_text.strip() or scenes):
        raise PlotOnlyDraftError(
            '이 기능은 저장된 플롯만 있고 초고·장면·최종본이 없는 회차 전용입니다.')
    return PlotOnlyLease(
        project_id, episode, row.revision,
        store.get_project(project_id).revision,
        _digest(row.plot), _digest(row.summary), _digest(row.draft),
        _digest(row.final_text), len(scenes))


def require_current_plot_only_lease(
    store: EpisodeStore, lease: PlotOnlyLease,
) -> None:
    if not isinstance(store, EpisodeStore) or type(lease) is not PlotOnlyLease:
        raise PlotOnlyDraftError('현재 작품의 저장된 플롯 회차를 다시 선택하세요.')
    try:
        current = _source_lease(store, lease.project_id, lease.episode)
    except (ValueError, OSError):
        raise PlotOnlyDraftError(
            '회차에 초고·장면·최종본이 생겼거나 저장된 플롯이 변경됐습니다.') from None
    if current != lease:
        raise PlotOnlyDraftError(
            '모델 실행 후 작품·플롯·회차가 변경됐습니다. 원고를 저장하지 않습니다.')


def begin_plot_only_draft(
    store: EpisodeStore, project_id: str, episode: int,
) -> PlotOnlyLease:
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(episode) is not int
            or not 1 <= episode <= 1000):
        raise PlotOnlyDraftError('기존 작품과 1~1000화 중 저장된 플롯 회차를 선택하세요.')
    return _source_lease(store, project_id, episode)


def propose_plot_only_draft(
    database_path: str | Path, project_id: str, episode: int,
    provider: LocalExecutableProvider, *,
    expected_lease: PlotOnlyLease,
    target_nonspace_chars: int = 5000,
    max_model_calls: int = 8,
    explicit_author_model_run: bool,
    should_stop: Callable[[], bool] | None = None,
) -> PlotOnlyDraftProposal:
    """Generate actual original chapter prose, without modifying SQLite.

    Never treats model-generated prose as a saved final or quality approval.
    Cooperative cancellation occurs between local blocking model calls.
    """
    if (explicit_author_model_run is not True
            or type(provider) is not LocalExecutableProvider
            or type(expected_lease) is not PlotOnlyLease
            or expected_lease.project_id != project_id
            or expected_lease.episode != episode
            or type(target_nonspace_chars) is not int
            or not 1000 <= target_nonspace_chars <= 50000
            or type(max_model_calls) is not int
            or not 1 <= max_model_calls <= 12
            or (should_stop is not None and not callable(should_stop))):
        raise PlotOnlyDraftError('저장 플롯·분량·로컬 모델 호출에 대한 별도 승인이 필요합니다.')
    path = Path(database_path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise PlotOnlyDraftError('기존 로컬 SQLite 파일만 선택할 수 있습니다.')
    with EpisodeStore(path) as store:
        require_current_plot_only_lease(store, expected_lease)
        row = store.get_episode(project_id, episode)
        canon = build_saved_rewrite_canon(store, path, project_id, episode)
        with CharacterStore(path) as characters:
            people = characters.list_characters(project_id)
        cast = tuple(p.name for p in people if p.name in row.plot)[:16]
        if not cast:
            cast = tuple(p.name for p in people[:8])
        if not cast:
            cast = ('작가가 설정한 등장인물',)
        plot = row.plot
        if len(plot) > 2600:
            plot = plot[:1250] + '\n[저장 플롯 중간 발췌 생략]\n' + plot[-1250:]
        written = ''
        calls = 0
        accepted = 0
        stopped = False
        for number in range(1, max_model_calls + 1):
            if should_stop is not None and should_stop():
                stopped = True
                break
            current_count = screen_korean_draft(
                written, target_chars=target_nonspace_chars).nonspace_chars
            remaining = target_nonspace_chars - current_count
            if remaining <= 0:
                break
            context = (
                '[작가 저장 Novel Bible·인물 성격/말투·회차별 실제 문맥]\n'
                + canon.text
                + '\n[이 회차에 작가가 이미 저장한 플롯]\n' + plot
                + '\n[이번 미검수 후보의 이미 생성된 실제 원고 끝부분]\n'
                + written[-2700:]
                + '\n[원문 플롯을 사건과 대사로 구체화. 뒤 회차의 미래 사건을 '
                  '이미 일어난 사건으로 서술 금지. 이전 출력 문장 재출력 금지. '
                  '소설 본문만 작성, 제목/요약/QC 합격 주장 금지.]')
            if len(context) > 18000:
                raise PlotOnlyDraftError('저장된 작가 문맥이 로컬 모델 입력 한도를 넘습니다.')
            allocated = min(10000, max(100, remaining))
            request = SceneDraftRequest(
                project_id, episode, number, context,
                f'목표 분량 {allocated}자. 저장된 이 회차 플롯을 기반으로 '
                '실제 독창적인 한국어 장편소설 본문을 집필하고 '
                '앞서 생성된 본문 뒤의 새로운 장면만 출력하라.',
                '플롯에 기록된 실제 인물 목표·갈등·인과를 장면으로 전개',
                '저장된 플롯의 시간과 장소',
                cast, target_chars=allocated)
            try:
                passage = draft_scene(request, provider).draft
            except LocalModelError:
                if not written:
                    raise PlotOnlyDraftError(
                        '승인된 로컬 GGUF가 실제 소설 본문을 생성하지 못했습니다.') from None
                break
            calls += 1
            if (type(passage) is not str or not passage.strip()
                    or has_foreign_script_corruption(passage)
                    or len(passage) > 30000):
                break
            passage = passage.strip()
            if (passage in written[-7000:]
                    or (len(written) >= 120
                        and written[-120:] in passage[:500])):
                break
            next_text = (written + '\n\n' + passage) if written else passage
            if (len(next_text) > 100000
                    or len(next_text.encode('utf-8')) > MAX_FIELD_BYTES['draft']):
                break
            if screen_korean_draft(
                    next_text, target_chars=target_nonspace_chars
            ).nonspace_chars <= current_count:
                break
            written = next_text
            accepted += 1
        if not written:
            raise PlotOnlyDraftError(
                '실제 새 소설 본문이 없어 기존 플롯 회차를 그대로 유지했습니다.')
        require_current_plot_only_lease(store, expected_lease)
        actual = screen_korean_draft(
            written, target_chars=target_nonspace_chars).nonspace_chars
        return PlotOnlyDraftProposal(
            expected_lease, written, target_nonspace_chars,
            actual, max(0, target_nonspace_chars - actual),
            calls, accepted, stopped)


def save_plot_only_draft(
    store: EpisodeStore, lease: PlotOnlyLease, manuscript: str, *,
    explicit_author_save: bool,
) -> int:
    """The ONLY write: author-reviewed candidate becomes an UNAPPROVED draft."""
    if (explicit_author_save is not True
            or type(lease) is not PlotOnlyLease
            or type(manuscript) is not str
            or not manuscript.strip() or '\x00' in manuscript
            or any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127
                   for c in manuscript)
            or len(manuscript.encode('utf-8')) > MAX_FIELD_BYTES['draft']):
        raise PlotOnlyDraftError('작가가 직접 검토한 초고와 별도 저장 승인이 필요합니다.')
    require_current_plot_only_lease(store, lease)
    # Existing EpisodeStore performs its own episode-revision CAS in SQLite.
    # This never modifies plot, scenes, final manuscript, or publication gate.
    saved = store.update_episode(
        lease.project_id, lease.episode,
        expected_revision=lease.episode_revision,
        draft=manuscript)
    return saved.revision
