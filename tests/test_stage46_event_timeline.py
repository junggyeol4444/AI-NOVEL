"""Stage 46 / ANF-REQ-036: absolute and relative time with strict-order conflicts."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from ai_novel_factory.database.event_timeline import (
    EventTimelineStore, TimelineError, _offset, _when,
)
from ai_novel_factory.database.event_cli import main as event_cli
from ai_novel_factory.database.novel_bible import NovelBibleError


class EventTimelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / 'novel.db'
        self.store = EventTimelineStore(self.db)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project('원작 아닌 새 작품').project_id

    def event(self, title='사건', when=None, anchor=None, offset=None, project=None):
        return self.store.create_event(project or self.project, title=title,
            when=when, anchor_event_id=anchor, offset_minutes=offset)

    def test_empty_audit(self):
        a = self.store.audit(self.project)
        self.assertEqual((a.event_count, a.precedence_count, a.checked_pairs), (0, 0, 0))

    def test_create_unknown_date(self):
        item = self.event()
        self.assertIsNone(item.when)
        self.assertEqual(self.store.audit(self.project).unresolved_event_ids, (item.event_id,))

    def test_date_roundtrip(self):
        self.assertEqual(self.event(when='2026-10-12').when, '2026-10-12')

    def test_datetime_timezone_utc(self):
        self.assertEqual(self.event(when='2026-10-12T12:34:56+09:00').when,
                         '2026-10-12T03:34:56+00:00')

    def test_datetime_z_utc(self):
        self.assertEqual(self.event(when='2026-10-12T00:00:00Z').when,
                         '2026-10-12T00:00:00+00:00')

    def test_datetime_fraction_rejected(self):
        with self.assertRaises(TimelineError):
            self.event(when='2026-10-12T12:00:00.123+00:00')

    def test_naive_datetime_rejected(self):
        with self.assertRaises(TimelineError):
            self.event(when='2026-10-12T12:00:00')

    def test_invalid_dates_rejected(self):
        for value in ('2026-02-30', '2026-13-01', '2026-1-2', '', 'yesterday',
                      '2026-10-12\x00', '2026-10-12T10:00:00+25:00', 7, True):
            with self.subTest(value=value), self.assertRaises(TimelineError):
                self.event(when=value)

    def test_date_extreme_overflow_safe(self):
        with self.assertRaises(TimelineError):
            self.event(when='9999-12-31')
        self.assertEqual(self.store.audit(self.project).event_count, 0)

    def test_relative_positive_minutes(self):
        a = self.event(when='2026-10-12T00:00:00+00:00')
        b = self.event(anchor=a.event_id, offset=90)
        self.assertEqual(b.offset_minutes, 90)
        self.assertEqual(self.store.audit(self.project).checked_pairs, 1)

    def test_relative_negative_minutes(self):
        a = self.event(when='2026-10-12T00:00:00+00:00')
        b = self.event(anchor=a.event_id, offset=-30)
        self.assertEqual(self.store.audit(self.project).checked_pairs, 1)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_relative_zero_allowed(self):
        a = self.event(when='2026-10-12T00:00:00+00:00')
        b = self.event(anchor=a.event_id, offset=0)
        self.assertEqual(self.store.audit(self.project).checked_pairs, 0)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_zero_offset_unknown_time_strict_order_rejected(self):
        a = self.event(when='2026-10-12')
        b = self.event(anchor=a.event_id, offset=0)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_zero_offset_unknown_anchor_strict_order_rejected(self):
        a = self.event()
        b = self.event(anchor=a.event_id, offset=0)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, b.event_id, a.event_id)

    def test_sibling_relative_reverse_order_rejected_without_absolute_time(self):
        root = self.event()
        later = self.event(anchor=root.event_id, offset=60)
        earlier = self.event(anchor=root.event_id, offset=30)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, later.event_id, earlier.event_id)

    def test_sibling_relative_same_offset_strict_order_rejected(self):
        root = self.event(when='2026-10-12')
        first = self.event(anchor=root.event_id, offset=60)
        second = self.event(anchor=root.event_id, offset=60)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, first.event_id, second.event_id)

    def test_relative_chain(self):
        a = self.event(when='2026-10-12T00:00:00+00:00')
        b = self.event(anchor=a.event_id, offset=60)
        c = self.event(anchor=b.event_id, offset=60)
        self.assertEqual(self.store.audit(self.project).checked_pairs, 3)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, c.event_id, a.event_id)

    def test_relative_unresolved_anchor(self):
        a = self.event()
        b = self.event(anchor=a.event_id, offset=60)
        self.assertEqual(set(self.store.audit(self.project).unresolved_event_ids),
                         {a.event_id, b.event_id})

    def test_missing_anchor_rejected(self):
        with self.assertRaises(TimelineError):
            self.event(anchor='a' * 32, offset=30)
        self.assertEqual(self.store.audit(self.project).event_count, 0)

    def test_anchor_without_offset(self):
        a = self.event()
        with self.assertRaises(TimelineError):
            self.event(anchor=a.event_id)

    def test_offset_without_anchor(self):
        with self.assertRaises(TimelineError):
            self.event(offset=1)

    def test_absolute_and_relative_rejected(self):
        a = self.event()
        with self.assertRaises(TimelineError):
            self.event(when='2026-10-12', anchor=a.event_id, offset=30)

    def test_bool_offset_rejected(self):
        with self.assertRaises(TimelineError):
            _offset(True)

    def test_float_offset_rejected(self):
        with self.assertRaises(TimelineError):
            _offset(1.0)

    def test_large_offset_rejected(self):
        with self.assertRaises(TimelineError):
            _offset(525600001)

    def test_min_offset_valid(self):
        self.assertEqual(_offset(-525600000), -525600000)

    def test_invalid_title_rejected(self):
        for title in ('', '  ', 'x'*121, 'bad\nline', None):
            with self.subTest(title=str(title)[:8]), self.assertRaises(TimelineError):
                self.event(title=title)

    def test_first_revision(self):
        self.assertEqual(self.event().revision, 1)

    def test_update_requires_matching_revision(self):
        item = self.event()
        newer = self.store.update_event(self.project, item.event_id, title='변경',
                                        when='2026-10-12', expected_revision=1)
        self.assertEqual(newer.revision, 2)
        with self.assertRaises(TimelineError):
            self.store.update_event(self.project, item.event_id, title='옛 수정',
                                    expected_revision=1)
        self.assertEqual(self.store.get_event(self.project, item.event_id).title, '변경')

    def test_update_cycle_rolls_back(self):
        a = self.event()
        b = self.event(anchor=a.event_id, offset=5)
        with self.assertRaises(TimelineError):
            self.store.update_event(self.project, a.event_id, title='역참조',
                                    anchor_event_id=b.event_id, offset_minutes=10,
                                    expected_revision=1)
        self.assertIsNone(self.store.get_event(self.project, a.event_id).anchor_event_id)
        self.assertEqual(self.store.get_event(self.project, a.event_id).revision, 1)

    def test_update_time_conflict_rolls_back(self):
        a = self.event(when='2026-10-01')
        b = self.event(when='2026-10-02')
        self.store.add_order(self.project, a.event_id, b.event_id)
        with self.assertRaises(TimelineError):
            self.store.update_event(self.project, a.event_id, title='충돌',
                                    when='2026-10-03', expected_revision=1)
        self.assertEqual(self.store.get_event(self.project, a.event_id).when, '2026-10-01')

    def test_update_anchor_not_in_project(self):
        a = self.event()
        p2 = self.store.create_project('별개').project_id
        foreign = self.event(project=p2)
        with self.assertRaises(TimelineError):
            self.store.update_event(self.project, a.event_id, title='다른 작품',
                anchor_event_id=foreign.event_id, offset_minutes=10, expected_revision=1)

    def test_explicit_valid_order(self):
        a = self.event(when='2026-10-01')
        b = self.event(when='2026-10-02')
        result = self.store.add_order(self.project, a.event_id, b.event_id)
        self.assertEqual((result.precedence_count, result.checked_pairs), (1, 1))

    def test_reverse_date_conflict(self):
        a = self.event(when='2026-10-02')
        b = self.event(when='2026-10-01')
        with self.assertRaisesRegex(TimelineError, '상충'):
            self.store.add_order(self.project, a.event_id, b.event_id)
        self.assertEqual(self.store.audit(self.project).precedence_count, 0)

    def test_same_precise_instant_conflict(self):
        a = self.event(when='2026-10-01T00:00:00Z')
        b = self.event(when='2026-10-01T00:00:00Z')
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_same_day_unknown_time_inconclusive(self):
        a = self.event(when='2026-10-01')
        b = self.event(when='2026-10-01')
        self.assertEqual(self.store.add_order(self.project, a.event_id, b.event_id).precedence_count, 1)

    def test_date_only_vs_instant_midnight(self):
        a = self.event(when='2026-10-01')
        b = self.event(when='2026-10-01T00:00:00Z')
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_same_day_later_instant_possible(self):
        a = self.event(when='2026-10-01')
        b = self.event(when='2026-10-01T12:00:00Z')
        self.assertEqual(self.store.add_order(self.project, a.event_id, b.event_id).checked_pairs, 1)

    def test_transitive_date_conflict(self):
        a = self.event(when='2026-10-03')
        b = self.event()
        c = self.event(when='2026-10-01')
        self.store.add_order(self.project, a.event_id, b.event_id)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, b.event_id, c.event_id)
        self.assertEqual(self.store.audit(self.project).precedence_count, 1)

    def test_explicit_cycle_rejected(self):
        a, b, c = self.event(), self.event(), self.event()
        self.store.add_order(self.project, a.event_id, b.event_id)
        self.store.add_order(self.project, b.event_id, c.event_id)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, c.event_id, a.event_id)
        self.assertEqual(self.store.audit(self.project).precedence_count, 2)

    def test_self_order_rejected(self):
        a = self.event()
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, a.event_id)

    def test_duplicate_order_rejected(self):
        a, b = self.event(), self.event()
        self.store.add_order(self.project, a.event_id, b.event_id)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_order_remove(self):
        a, b = self.event(), self.event()
        self.store.add_order(self.project, a.event_id, b.event_id)
        self.store.remove_order(self.project, a.event_id, b.event_id)
        self.assertEqual(self.store.audit(self.project).precedence_count, 0)

    def test_missing_order_remove_rejected(self):
        a, b = self.event(), self.event()
        with self.assertRaises(TimelineError):
            self.store.remove_order(self.project, a.event_id, b.event_id)

    def test_cross_project_order_rejected(self):
        a = self.event()
        other = self.store.create_project('별개').project_id
        b = self.event(project=other)
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)

    def test_project_isolation(self):
        a = self.event()
        other = self.store.create_project('별개').project_id
        self.assertEqual(self.store.list_events(other), ())
        with self.assertRaises(TimelineError):
            self.store.get_event(other, a.event_id)

    def test_delete_event(self):
        a = self.event()
        self.store.delete_event(self.project, a.event_id, expected_revision=1)
        self.assertEqual(self.store.list_events(self.project), ())

    def test_delete_stale_revision(self):
        a = self.event()
        self.store.update_event(self.project, a.event_id, title='변경', expected_revision=1)
        with self.assertRaises(TimelineError):
            self.store.delete_event(self.project, a.event_id, expected_revision=1)

    def test_delete_anchor_blocked(self):
        a = self.event()
        self.event(anchor=a.event_id, offset=5)
        with self.assertRaises(TimelineError):
            self.store.delete_event(self.project, a.event_id, expected_revision=1)

    def test_delete_order_endpoint_blocked(self):
        a, b = self.event(), self.event()
        self.store.add_order(self.project, a.event_id, b.event_id)
        with self.assertRaises(TimelineError):
            self.store.delete_event(self.project, a.event_id, expected_revision=1)

    def test_delete_project_cascades(self):
        a = self.event()
        self.event(anchor=a.event_id, offset=5)
        self.store.delete_project(self.project)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM bible_timeline_events').fetchone()[0], 0)

    def test_project_revision_increases(self):
        start = self.store.get_project(self.project).revision
        a = self.event()
        self.assertEqual(self.store.get_project(self.project).revision, start+1)
        self.store.update_event(self.project, a.event_id, title='변경', expected_revision=1)
        self.assertEqual(self.store.get_project(self.project).revision, start+2)

    def test_failed_change_no_revision_bump(self):
        a = self.event(when='2026-10-02')
        b = self.event(when='2026-10-01')
        rev = self.store.get_project(self.project).revision
        with self.assertRaises(TimelineError):
            self.store.add_order(self.project, a.event_id, b.event_id)
        self.assertEqual(self.store.get_project(self.project).revision, rev)

    def test_persistence_after_reopen(self):
        a = self.event(when='2026-10-01')
        b = self.event(anchor=a.event_id, offset=60)
        self.store.close()
        self.store = EventTimelineStore(self.db)
        self.addCleanup(self.store.close)
        self.assertEqual(self.store.get_event(self.project, b.event_id).anchor_event_id, a.event_id)
        self.assertEqual(self.store.audit(self.project).checked_pairs, 1)

    def test_external_corrupt_anchor_detected(self):
        a = self.event()
        self.store._db.execute('UPDATE bible_timeline_events SET anchor_event_id=?, offset_minutes=5',
                               ('f'*32,))
        self.store._db.commit()
        with self.assertRaises(TimelineError):
            self.store.audit(self.project)

    def test_external_corrupt_title_detected(self):
        self.event()
        self.store._db.execute('UPDATE bible_timeline_events SET title=?', ('   ',))
        self.store._db.commit()
        with self.assertRaises(TimelineError):
            self.store.list_events(self.project)

    def test_direct_foreign_key_protects_order(self):
        a = self.event()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute('INSERT INTO bible_timeline_order VALUES (?, ?, ?)',
                                   (self.project, a.event_id, 'a'*32))
        self.store._db.rollback()

    def test_empty_list(self):
        self.assertEqual(self.store.list_events(self.project), ())

    def test_ordered_list_stable(self):
        self.event('가')
        self.event('나')
        self.assertEqual(len(self.store.list_events(self.project)), 2)

    def test_unicode_title(self):
        self.assertEqual(self.event('새벽의 약속 🌙').title, '새벽의 약속 🌙')

    def test_when_validation_no_secret_in_errors(self):
        with self.assertRaises(TimelineError) as context:
            _when('TOP_SECRET_123')
        self.assertNotIn('TOP_SECRET_123', str(context.exception))

    def test_cli_add_audit_show_redacted(self):
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(event_cli(['--database', str(self.db), 'event-add', self.project,
                '--title', '비밀 사건', '--when', '2026-10-01']), 0)
        self.assertNotIn('비밀 사건', out.getvalue())
        uid = out.getvalue().split()[1]
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(event_cli(['--database', str(self.db), 'event-show',
                                        self.project, uid]), 0)
        self.assertNotIn('비밀 사건', out.getvalue())
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(event_cli(['--database', str(self.db), 'event-audit', self.project]), 0)
        self.assertIn('PASS', out.getvalue())

    def test_cli_reveal_opt_in(self):
        a = self.event('개인 비밀')
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(event_cli(['--database', str(self.db), 'event-show',
                self.project, a.event_id, '--reveal']), 0)
        self.assertIn('개인 비밀', out.getvalue())

    def test_cli_invalid_order_fails_closed(self):
        a = self.event(when='2026-10-03')
        b = self.event(when='2026-10-01')
        out = StringIO()
        with redirect_stdout(out):
            code = event_cli(['--database', str(self.db), 'order-add', self.project,
                              a.event_id, b.event_id])
        self.assertEqual(code, 1)
        self.assertIn('ERROR', out.getvalue())
        self.assertNotIn('2026-10-03', out.getvalue())

    def test_cli_no_remote_db(self):
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(event_cli(['--database', '//server/share/db',
                                        'event-audit', self.project]), 1)
        self.assertIn('ERROR', out.getvalue())

    def test_cli_subprocess_offline(self):
        run = subprocess.run([sys.executable, '-m', 'ai_novel_factory.database.event_cli',
            '--database', str(self.db), 'event-audit', self.project],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
            env={'PYTHONPATH': 'src', 'PATH': '/usr/bin:/bin'} if sys.platform != 'win32' else None)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
