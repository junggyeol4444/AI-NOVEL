"""Stage 79: explicit opt-in local storage of non-authoritative reader proxies.

Only numeric indicators, identifiers, hashes and UTC timestamps are stored.
No source text, subjective commentary, manuscript approval or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .reader_simulation import (ReaderSimulationError, ReaderSimulationReport,
                                SceneReaderAnnotation, simulate_reader_profiles)


@dataclass(frozen=True)
class ReaderSimulationReceipt:
    project_id: str
    episode_number: int
    draft_sha256: str
    annotation_sha256: str
    status: str
    indicators_json: str
    recorded_at: str
    manuscript_approved: bool = False
    publication_approved: bool = False


class ReaderSimulationStore:
    """Local SQLite persistence. Records are references, not quality certificates."""

    def __init__(self, path: str | Path = ':memory:'):
        if isinstance(path, Path):
            path = str(path)
        if (type(path) is not str or not path or '\x00' in path or
                (path != ':memory:' and not Path(path).parent.is_dir())):
            raise ReaderSimulationError('invalid local reader database')
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute('''CREATE TABLE IF NOT EXISTS reader_proxy (
            project_id TEXT NOT NULL,
            episode_number INTEGER NOT NULL,
            draft_sha256 TEXT NOT NULL,
            annotation_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            indicators_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(project_id, episode_number, draft_sha256, annotation_sha256)
        )''')

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def record(self, report: ReaderSimulationReport, *, draft: str,
               scenes: tuple[SceneReaderAnnotation, ...]) -> ReaderSimulationReceipt:
        """Recompute all indicators to reject forged/altered reports before saving."""
        if type(report) is not ReaderSimulationReport:
            raise ReaderSimulationError('invalid reader report')
        current = simulate_reader_profiles(report.project_id, report.episode_number,
                                           draft, scenes=scenes)
        if report != current:
            raise ReaderSimulationError('reader report provenance mismatch')
        indicators = json.dumps({
            'methodology': report.methodology,
            'metrics': [{ 'dimension': m.dimension, 'score': m.score,
                         'observations': m.observations,
                         'required_observations': m.required_observations}
                        for m in report.metrics],
            'profiles': [{ 'profile': p.profile, 'score': p.score} for p in report.profiles],
            'unexamined': list(report.unexamined),
        }, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self._db:
            self._db.execute('''INSERT INTO reader_proxy
                (project_id, episode_number, draft_sha256, annotation_sha256,
                 status, indicators_json, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, episode_number, draft_sha256, annotation_sha256)
                DO UPDATE SET status=excluded.status,
                    indicators_json=excluded.indicators_json, recorded_at=excluded.recorded_at''',
                (report.project_id, report.episode_number, report.draft_sha256,
                 report.annotation_sha256, report.status, indicators, now))
        return ReaderSimulationReceipt(report.project_id, report.episode_number,
            report.draft_sha256, report.annotation_sha256, report.status, indicators, now)

    def read_current(self, project_id: str, episode_number: int, draft: str, *,
                     scenes: tuple[SceneReaderAnnotation, ...]) -> ReaderSimulationReceipt:
        """Only retrieve a receipt for the exact *current* draft and annotations."""
        report = simulate_reader_profiles(project_id, episode_number, draft, scenes=scenes)
        row = self._db.execute('''SELECT * FROM reader_proxy WHERE project_id=?
            AND episode_number=? AND draft_sha256=? AND annotation_sha256=?''',
            (report.project_id, report.episode_number, report.draft_sha256,
             report.annotation_sha256)).fetchone()
        if row is None:
            raise ReaderSimulationError('matching reader indicators not recorded')
        result = ReaderSimulationReceipt(**dict(row))
        # Detect database manipulation or incompatible old receipts.
        expected = json.dumps({
            'methodology': report.methodology,
            'metrics': [{'dimension': m.dimension, 'score': m.score,
                         'observations': m.observations,
                         'required_observations': m.required_observations}
                        for m in report.metrics],
            'profiles': [{'profile': p.profile, 'score': p.score} for p in report.profiles],
            'unexamined': list(report.unexamined),
        }, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        if result.status != report.status or result.indicators_json != expected:
            raise ReaderSimulationError('reader indicators integrity mismatch')
        return result
