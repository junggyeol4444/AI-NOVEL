"""Stage 85 / ANF-REQ-050: offline scheduled draft queue and audit tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.writing_scheduler import LocalWritingScheduler, ScheduleError


T = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = LocalTaskQueue(Path(self.temp.name) / 'queue.sqlite')
        self.scheduler = LocalWritingScheduler(self.queue)
        self.project = 'project-85'

    def tearDown(self):
        self.temp.cleanup()

    def schedule(self, **kwargs):
        args = dict(start_at=T, frequency='ONCE')
        args.update(kwargs)
        return self.scheduler.create_schedule(self.project, 2, **args)

    def tick(self, **kwargs):
        args = dict(now=T, dispatch_authorized=True)
        args.update(kwargs)
        return self.scheduler.tick(**args)

    def test_one_time_due_enqueues(self):
        s = self.schedule()
        (run,) = self.tick()
        self.assertEqual(run.schedule_id, s.schedule_id)
        self.assertEqual(run.status, 'QUEUED')
        self.assertEqual(self.queue.get(run.task_id).episode_number, 2)

    def test_one_time_disables(self):
        s = self.schedule()
        self.tick()
        result = self.scheduler.get_schedule(s.schedule_id)
        self.assertFalse(result.enabled)
        self.assertIsNone(result.next_due_utc)

    def test_no_early_execution(self):
        self.schedule(start_at=T + timedelta(seconds=1))
        self.assertEqual(self.tick(), ())

    def test_exact_due(self):
        self.schedule(start_at=T)
        self.assertEqual(len(self.tick()), 1)

    def test_no_second_one_time_run(self):
        self.schedule()
        self.tick()
        self.assertEqual(self.tick(), ())

    def test_no_auto_execution(self):
        self.schedule()
        (run,) = self.tick()
        self.assertEqual(self.queue.get(run.task_id).attempts, 0)
        self.assertEqual(self.queue.get(run.task_id).status, 'QUEUED')

    def test_no_implicit_approval(self):
        self.schedule()
        (run,) = self.tick()
        self.assertFalse(run.manuscript_approved)
        self.assertFalse(run.published)

    def test_utc_offset_normalized(self):
        local = T.astimezone(timezone(timedelta(hours=9)))
        s = self.schedule(start_at=local)
        self.assertEqual(s.next_due_utc, '2026-10-14T03:00:00Z')

    def test_reject_naive_time(self):
        with self.assertRaises(ScheduleError):
            self.schedule(start_at=T.replace(tzinfo=None))

    def test_reject_subsecond_time(self):
        with self.assertRaises(ScheduleError):
            self.schedule(start_at=T + timedelta(microseconds=1))

    def test_reject_non_datetime(self):
        with self.assertRaises(ScheduleError):
            self.schedule(start_at='2026-10-14')

    def test_reject_bad_frequency(self):
        with self.assertRaises(ScheduleError):
            self.schedule(frequency='MINUTELY')

    def test_reject_wrong_frequency_type(self):
        with self.assertRaises(ScheduleError):
            self.schedule(frequency=1)

    def test_reject_invalid_project(self):
        with self.assertRaises(ScheduleError):
            self.scheduler.create_schedule('bad project', 1, start_at=T)

    def test_reject_invalid_episode(self):
        for value in (0, -1, 1001, True, 2.0):
            with self.subTest(value=value), self.assertRaises(ScheduleError):
                self.scheduler.create_schedule(self.project, value, start_at=T)

    def test_reject_once_multiple(self):
        with self.assertRaises(ScheduleError):
            self.schedule(max_occurrences=2)

    def test_reject_bad_occurrences(self):
        for value in (0, -1, 1001, True, 1.2):
            with self.subTest(value=value), self.assertRaises(ScheduleError):
                self.schedule(frequency='DAILY', max_occurrences=value)

    def test_dispatch_authorization_required(self):
        self.schedule()
        with self.assertRaises(ScheduleError):
            self.tick(dispatch_authorized=False)
        self.assertEqual(self.scheduler.list_runs(next(iter(self._schedule_ids()))), ())

    def _schedule_ids(self):
        with self.queue._connect() as db:
            return [x[0] for x in db.execute('SELECT schedule_id FROM writing_schedules')]

    def test_non_bool_authorization_rejected(self):
        self.schedule()
        with self.assertRaises(ScheduleError):
            self.tick(dispatch_authorized=1)

    def test_invalid_tick_time(self):
        self.schedule()
        with self.assertRaises(ScheduleError):
            self.tick(now=T.replace(tzinfo=None))

    def test_invalid_tick_limit(self):
        for limit in (0, 101, True, 2.0):
            with self.subTest(limit=limit), self.assertRaises(ScheduleError):
                self.tick(limit=limit)

    def test_hourly_recurrence(self):
        s = self.schedule(frequency='HOURLY')
        self.tick()
        self.assertEqual(self.scheduler.get_schedule(s.schedule_id).next_due_utc,
                         '2026-10-14T04:00:00Z')

    def test_daily_recurrence(self):
        s = self.schedule(frequency='DAILY')
        self.tick()
        self.assertEqual(self.scheduler.get_schedule(s.schedule_id).next_due_utc,
                         '2026-10-15T03:00:00Z')

    def test_hourly_later_tick(self):
        s = self.schedule(frequency='HOURLY')
        self.tick()
        self.assertEqual(len(self.tick(now=T + timedelta(hours=1))), 1)
        self.assertEqual(len(self.scheduler.list_runs(s.schedule_id)), 2)

    def test_downtime_skips_catchup(self):
        s = self.schedule(frequency='HOURLY')
        (run,) = self.tick(now=T + timedelta(hours=5, minutes=1))
        self.assertEqual(run.skipped_missed_slots, 5)
        self.assertEqual(self.scheduler.get_schedule(s.schedule_id).next_due_utc,
                         '2026-10-14T09:00:00Z')

    def test_downtime_no_completion_claim(self):
        self.schedule(frequency='DAILY')
        (run,) = self.tick(now=T + timedelta(days=4))
        self.assertEqual(run.status, 'QUEUED')
        self.assertEqual(run.skipped_missed_slots, 4)
        self.assertEqual(self.queue.get(run.task_id).attempts, 0)

    def test_hourly_max_occurrences(self):
        s = self.schedule(frequency='HOURLY', max_occurrences=2)
        self.tick()
        self.tick(now=T + timedelta(hours=1))
        self.assertFalse(self.scheduler.get_schedule(s.schedule_id).enabled)
        self.assertEqual(self.scheduler.get_schedule(s.schedule_id).occurrence_count, 2)

    def test_disable_prevents_dispatch(self):
        s = self.schedule()
        self.scheduler.disable_schedule(s.schedule_id)
        self.assertEqual(self.tick(), ())

    def test_disable_idempotent(self):
        s = self.schedule()
        self.scheduler.disable_schedule(s.schedule_id)
        self.assertFalse(self.scheduler.disable_schedule(s.schedule_id).enabled)

    def test_disable_unknown(self):
        with self.assertRaises(ScheduleError):
            self.scheduler.disable_schedule('missing')

    def test_get_unknown(self):
        self.assertIsNone(self.scheduler.get_schedule('missing'))
        self.assertIsNone(self.scheduler.get_run('missing'))

    def test_invalid_identifiers(self):
        for f in (self.scheduler.get_schedule, self.scheduler.get_run,
                  self.scheduler.list_runs, self.scheduler.events):
            with self.subTest(f=f), self.assertRaises(ScheduleError):
                f('bad id')

    def test_event_for_enqueue(self):
        self.schedule()
        (run,) = self.tick()
        self.assertEqual([e.event for e in self.scheduler.events(run.run_id)], ['QUEUED'])

    def test_busy_prevents_duplicate_episode(self):
        s = self.schedule(frequency='HOURLY')
        first = self.tick()[0]
        second = self.tick(now=T + timedelta(hours=1))[0]
        self.assertEqual(second.status, 'SKIPPED_BUSY')
        self.assertIsNone(second.task_id)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(len(self.scheduler.list_runs(s.schedule_id)), 2)

    def test_failed_task_blocks_new_slot_without_retry_authorization(self):
        self.schedule(frequency='HOURLY')
        first = self.tick()[0]
        self.scheduler.execute_run(first.run_id, handler=lambda p, e: False,
                                   local_execution_approved=True, now=T)
        second = self.tick(now=T + timedelta(hours=1))[0]
        self.assertEqual(second.status, 'SKIPPED_BUSY')
        self.assertIsNone(second.task_id)

    def test_interrupted_task_blocks_new_slot(self):
        self.schedule(frequency='HOURLY')
        first = self.tick()[0]
        self.queue.claim_identified(first.task_id, self.project, 2)
        LocalTaskQueue(self.queue.path)
        second = self.tick(now=T + timedelta(hours=1))[0]
        self.assertEqual(second.status, 'SKIPPED_BUSY')

    def test_busy_logs_event(self):
        self.schedule(frequency='HOURLY')
        self.tick()
        skipped = self.tick(now=T + timedelta(hours=1))[0]
        self.assertEqual(self.scheduler.events(skipped.run_id)[0].event, 'SKIPPED_BUSY')

    def test_busy_with_other_schedule(self):
        self.schedule()
        self.schedule()
        runs = self.tick()
        self.assertEqual({r.status for r in runs}, {'QUEUED', 'SKIPPED_BUSY'})

    def test_other_episode_not_blocked(self):
        self.schedule()
        self.scheduler.create_schedule(self.project, 3, start_at=T)
        runs = self.tick()
        self.assertEqual([r.status for r in runs], ['QUEUED', 'QUEUED'])

    def test_other_project_not_blocked(self):
        self.schedule()
        self.scheduler.create_schedule('other', 2, start_at=T)
        self.assertEqual([r.status for r in self.tick()], ['QUEUED', 'QUEUED'])

    def test_limit_paginates(self):
        for n in range(4):
            self.scheduler.create_schedule(self.project, n + 1, start_at=T)
        self.assertEqual(len(self.tick(limit=2)), 2)
        self.assertEqual(len(self.tick(limit=2)), 2)
        self.assertEqual(len(self.tick(limit=2)), 0)

    def test_run_success(self):
        self.schedule()
        run = self.tick()[0]
        result = self.scheduler.execute_run(run.run_id, handler=lambda p, e: True,
                                            local_execution_approved=True, now=T)
        self.assertEqual(result.status, 'COMPLETED')
        self.assertEqual(result.attempts, 1)
        self.assertEqual([e.event for e in self.scheduler.events(run.run_id)],
                         ['QUEUED', 'OBSERVED_RUNNING', 'OBSERVED_COMPLETED'])

    def test_run_handler_receives_identity(self):
        self.schedule()
        run = self.tick()[0]
        called = []
        self.scheduler.execute_run(run.run_id, handler=lambda p, e: called.append((p, e)) or True,
                                   local_execution_approved=True, now=T)
        self.assertEqual(called, [(self.project, 2)])

    def test_handler_false_is_failure(self):
        self.schedule()
        run = self.tick()[0]
        result = self.scheduler.execute_run(run.run_id, handler=lambda p, e: False,
                                            local_execution_approved=True, now=T)
        self.assertEqual((result.status, result.error_code), ('FAILED', 'HANDLER_NOT_SUCCESSFUL'))

    def test_handler_non_bool_is_failure(self):
        self.schedule()
        run = self.tick()[0]
        result = self.scheduler.execute_run(run.run_id, handler=lambda p, e: 1,
                                            local_execution_approved=True, now=T)
        self.assertEqual(result.status, 'FAILED')

    def test_handler_exception_is_sanitized(self):
        self.schedule()
        run = self.tick()[0]
        def boom(*_):
            raise RuntimeError('SECRET_MANUSCRIPT_TEXT')
        result = self.scheduler.execute_run(run.run_id, handler=boom,
                                            local_execution_approved=True, now=T)
        self.assertEqual(result.error_code, 'HANDLER_EXCEPTION')
        self.assertNotIn('SECRET_MANUSCRIPT_TEXT', repr(self.scheduler.events(run.run_id)))

    def test_execution_requires_authorization(self):
        self.schedule()
        run = self.tick()[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.execute_run(run.run_id, handler=lambda p, e: True,
                                       local_execution_approved=False, now=T)
        self.assertEqual(self.queue.get(run.task_id).status, 'QUEUED')

    def test_execution_non_bool_authorization(self):
        self.schedule()
        run = self.tick()[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.execute_run(run.run_id, handler=lambda p, e: True,
                                       local_execution_approved=1, now=T)

    def test_execution_requires_callable(self):
        self.schedule()
        run = self.tick()[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.execute_run(run.run_id, handler=None,
                                       local_execution_approved=True, now=T)

    def test_execution_cannot_repeat_completed(self):
        self.schedule()
        run = self.tick()[0]
        self.scheduler.execute_run(run.run_id, handler=lambda p, e: True,
                                   local_execution_approved=True, now=T)
        with self.assertRaises(ScheduleError):
            self.scheduler.execute_run(run.run_id, handler=lambda p, e: True,
                                       local_execution_approved=True, now=T)

    def test_skipped_not_executable(self):
        self.schedule(frequency='HOURLY')
        self.tick()
        skipped = self.tick(now=T + timedelta(hours=1))[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.execute_run(skipped.run_id, handler=lambda p, e: True,
                                       local_execution_approved=True, now=T)

    def test_external_worker_status_observed(self):
        self.schedule()
        run = self.tick()[0]
        claimed = self.queue.claim_identified(run.task_id, self.project, 2)
        self.assertIsNotNone(claimed)
        self.queue.finish(run.task_id, succeeded=True)
        result = self.scheduler.refresh_run(run.run_id, now=T)
        self.assertEqual(result.status, 'COMPLETED')

    def test_refresh_idempotent_events(self):
        self.schedule()
        run = self.tick()[0]
        self.scheduler.refresh_run(run.run_id, now=T)
        self.scheduler.refresh_run(run.run_id, now=T)
        self.assertEqual(len(self.scheduler.events(run.run_id)), 1)

    def test_queue_recovery_logged(self):
        self.schedule()
        run = self.tick()[0]
        self.queue.claim_identified(run.task_id, self.project, 2)
        LocalTaskQueue(self.queue.path)  # crash recovery converts RUNNING to INTERRUPTED
        result = self.scheduler.refresh_run(run.run_id, now=T)
        self.assertEqual((result.status, result.error_code), ('INTERRUPTED', 'WORKER_INTERRUPTED'))

    def test_no_retry_on_handler_exception(self):
        self.schedule()
        run = self.tick()[0]
        self.scheduler.execute_run(run.run_id, handler=lambda p, e: False,
                                   local_execution_approved=True, now=T)
        with self.assertRaises(ScheduleError):
            self.scheduler.retry_run(run.run_id, now=T, retry_authorized=True)

    def test_retry_transient_error(self):
        self.schedule()
        run = self.tick()[0]
        self.queue.claim_identified(run.task_id, self.project, 2)
        self.queue.finish(run.task_id, succeeded=False, error_code='LOCAL_PROVIDER_TIMEOUT')
        result = self.scheduler.retry_run(run.run_id, now=T, retry_authorized=True)
        self.assertEqual(result.status, 'QUEUED')
        self.assertEqual(result.attempts, 1)
        self.assertEqual([e.event for e in self.scheduler.events(run.run_id)],
                         ['QUEUED', 'OBSERVED_FAILED', 'RETRY_QUEUED'])

    def test_retry_requires_authorization(self):
        self.schedule()
        run = self.tick()[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.retry_run(run.run_id, now=T, retry_authorized=False)

    def test_retry_non_bool_authorization(self):
        self.schedule()
        run = self.tick()[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.retry_run(run.run_id, now=T, retry_authorized=1)

    def test_retry_cannot_exceed_budget(self):
        self.schedule()
        run = self.tick()[0]
        self.queue.claim_identified(run.task_id, self.project, 2)
        self.queue.finish(run.task_id, succeeded=False, error_code='LOCAL_PROVIDER_TIMEOUT')
        with self.assertRaises(ScheduleError):
            self.scheduler.retry_run(run.run_id, now=T, retry_authorized=True, max_attempts=1)

    def test_retry_bad_budget(self):
        self.schedule()
        run = self.tick()[0]
        for n in (0, 6, True):
            with self.subTest(n=n), self.assertRaises(ScheduleError):
                self.scheduler.retry_run(run.run_id, now=T, retry_authorized=True, max_attempts=n)

    def test_retry_only_once_per_failure(self):
        self.schedule()
        run = self.tick()[0]
        self.queue.claim_identified(run.task_id, self.project, 2)
        self.queue.finish(run.task_id, succeeded=False, error_code='LOCAL_PROVIDER_TIMEOUT')
        self.scheduler.retry_run(run.run_id, now=T, retry_authorized=True)
        with self.assertRaises(ScheduleError):
            self.scheduler.retry_run(run.run_id, now=T, retry_authorized=True)

    def test_retry_skipped_rejected(self):
        self.schedule(frequency='HOURLY')
        self.tick()
        skipped = self.tick(now=T + timedelta(hours=1))[0]
        with self.assertRaises(ScheduleError):
            self.scheduler.retry_run(skipped.run_id, now=T, retry_authorized=True)

    def test_reopen_persists_runs(self):
        s = self.schedule()
        first = self.tick()[0]
        new = LocalWritingScheduler(LocalTaskQueue(self.queue.path, recover_running=False))
        self.assertEqual(new.get_schedule(s.schedule_id), self.scheduler.get_schedule(s.schedule_id))
        self.assertEqual(new.get_run(first.run_id), first)

    def test_reopen_does_not_autodispatch(self):
        self.schedule()
        run = self.tick()[0]
        LocalWritingScheduler(LocalTaskQueue(self.queue.path, recover_running=False))
        self.assertEqual(self.queue.get(run.task_id).attempts, 0)

    def test_parallel_tick_at_most_once(self):
        self.schedule()
        results, errors = [], []
        def call():
            try:
                results.extend(self.tick())
            except Exception as exc:
                errors.append(exc)
        a, b = threading.Thread(target=call), threading.Thread(target=call)
        a.start(); b.start(); a.join(); b.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)

    def test_event_contains_only_metadata(self):
        self.schedule()
        run = self.tick()[0]
        with self.queue._connect() as db:
            text = str(db.execute('SELECT * FROM writing_schedule_events').fetchall())
        self.assertNotIn('manuscript', text.lower())
        self.assertNotIn('prompt', text.lower())
        self.assertEqual(len(self.scheduler.events(run.run_id)), 1)

    def test_atomic_dispatch_failure_rolls_back(self):
        s = self.schedule()
        with self.queue._connect() as db:
            db.execute('''CREATE TRIGGER block_scheduled_enqueue BEFORE INSERT ON local_tasks
                BEGIN SELECT RAISE(ABORT, 'blocked'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.tick()
        self.assertEqual(self.scheduler.get_schedule(s.schedule_id).occurrence_count, 0)
        self.assertEqual(self.scheduler.list_runs(s.schedule_id), ())

    def test_scheduler_never_changes_episode_db(self):
        self.schedule()
        self.tick()
        with self.queue._connect() as db:
            self.assertNotIn('bible_episodes', {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")})


if __name__ == '__main__':
    unittest.main()
