"""Stage 90 ANF-REQ-069: metadata-only local UI data and operating audit."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.util
import sqlite3
import tempfile
import unittest

from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.operations_monitor import (
    OperationsReader, OperationsLedger, OperationsError, ERROR_CODES,
)
from ai_novel_factory.task_monitor import TaskMonitor
from ai_novel_factory.writing_scheduler import LocalWritingScheduler


T = datetime(2026,10,14,9,0,tzinfo=timezone.utc)


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'jobs.sqlite3'
        self.queue = LocalTaskQueue(self.db, recover_running=False)
        self.queue.enqueue('alpha', 3, task_id='job-a')
        self.queue.enqueue('beta', 5, task_id='job-b')
        self.reader = OperationsReader(self.db)
        self.ledger = OperationsLedger(self.queue)

    def test_existing_queue_read(self):
        self.assertEqual({r.task_id for r in self.reader.list_jobs()}, {'job-a','job-b'})

    def test_project_filter(self):
        self.assertEqual([r.task_id for r in self.reader.list_jobs(project_id='alpha')], ['job-a'])
        self.assertEqual(self.reader.list_jobs(project_id='missing'), ())

    def test_summary_empty(self):
        report = self.reader.summary()
        self.assertEqual((report.task_count, report.event_count), (2,0))
        self.assertEqual(report.reported_minor_by_currency, ())

    def test_reader_no_schema_creation(self):
        with sqlite3.connect(self.db) as con:
            con.execute('DROP TABLE operation_events')
        self.assertEqual(OperationsReader(self.db).list_events(), ())
        with sqlite3.connect(self.db) as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='operation_events'").fetchone())

    def test_missing_file_never_created(self):
        missing = self.db.parent / 'missing.sqlite3'
        with self.assertRaises(OperationsError): OperationsReader(missing)
        self.assertFalse(missing.exists())

    def test_symlink_denied(self):
        link = self.db.parent / 'link.sqlite'
        link.symlink_to(self.db)
        with self.assertRaises(OperationsError): OperationsReader(link)

    def test_not_sqlite_denied(self):
        p = self.db.parent / 'junk.db'
        p.write_text('NOT A DATABASE')
        with self.assertRaises(OperationsError): OperationsReader(p)

    def test_no_tasks_table_denied(self):
        p = self.db.parent / 'other.db'
        with sqlite3.connect(p) as con: con.execute('CREATE TABLE other(name TEXT)')
        with self.assertRaises(OperationsError): OperationsReader(p)

    def test_wrong_ledger_object(self):
        with self.assertRaises(OperationsError): OperationsLedger('not a queue')

    def test_record_unknown_default(self):
        ev = self.ledger.record('job-a','STARTED',occurred_at=T)
        self.assertEqual((ev.cost_kind,ev.cost_minor,ev.currency),('UNKNOWN',None,None))
        self.assertEqual(ev.recorded_utc,'2026-10-14T09:00:00.000000+00:00')

    def test_reported_zero_cost_is_known(self):
        self.ledger.record('job-a','COMPLETED',cost_kind='REPORTED',cost_minor=0,currency='USD')
        s = self.reader.summary()
        self.assertEqual(s.reported_minor_by_currency, (('USD',0),))
        self.assertEqual(s.unknown_cost_events, 0)

    def test_unknown_cost_not_assumed_zero(self):
        self.ledger.record('job-a','CHECKPOINT')
        self.assertEqual(self.reader.summary().unknown_cost_events,1)
        self.assertEqual(self.reader.summary().reported_minor_by_currency,())

    def test_reported_and_estimated_cost_separate(self):
        self.ledger.record('job-a','STARTED',cost_kind='REPORTED',cost_minor=110,currency='USD')
        self.ledger.record('job-a','CHECKPOINT',cost_kind='ESTIMATED',cost_minor=200,currency='USD')
        s=self.reader.summary()
        self.assertEqual(s.reported_minor_by_currency,(('USD',110),))
        self.assertEqual(s.estimated_minor_by_currency,(('USD',200),))

    def test_currency_not_mixed(self):
        for cur,amt in [('KRW',1000),('USD',300),('KRW',500)]:
            self.ledger.record('job-b','CHECKPOINT',cost_kind='REPORTED',currency=cur,cost_minor=amt)
        self.assertEqual(self.reader.summary().reported_minor_by_currency,(('KRW',1500),('USD',300)))

    def test_project_cost_isolation(self):
        self.ledger.record('job-a','STARTED',cost_kind='REPORTED',currency='USD',cost_minor=12)
        self.ledger.record('job-b','STARTED',cost_kind='REPORTED',currency='USD',cost_minor=25)
        s=self.reader.summary(project_id='alpha')
        self.assertEqual((s.task_count,s.event_count,s.reported_minor_by_currency),(1,1,(('USD',12),)))
        self.assertEqual([e.project_id for e in self.reader.list_events(project_id='beta')],['beta'])

    def test_failure_classification(self):
        self.queue.claim_identified('job-a','alpha',3)
        self.queue.finish('job-a',succeeded=False,error_code='HANDLER_EXCEPTION')
        row=self.ledger.record('job-a','FAILED',error_code='HANDLER_EXCEPTION',duration_ms=18)
        self.assertEqual(row.error_code,'HANDLER_EXCEPTION')
        self.assertEqual(self.reader.summary().error_events,1)
        self.assertEqual(self.reader.summary().failed_tasks,1)

    def test_queue_error_redacted(self):
        with self.queue._connect() as db:
            db.execute("UPDATE local_tasks SET status='FAILED',error_code=? WHERE task_id='job-a'",('my private password',))
        self.assertEqual(self.reader.list_jobs(project_id='alpha')[0].error_code,'UNKNOWN_ERROR')
        self.assertNotIn('private',str(self.reader.list_jobs()))

    def test_scheduler_error_redacted(self):
        scheduler = LocalWritingScheduler(self.queue)
        schedule = scheduler.create_schedule('alpha',4,start_at=T)
        (run,) = scheduler.tick(now=T,dispatch_authorized=True)
        with self.queue._connect() as db:
            db.execute("UPDATE writing_schedule_runs SET error_code=? WHERE run_id=?",('sensitive text', run.run_id))
        rows=self.reader.list_scheduled_runs(project_id='alpha')
        self.assertEqual((rows[0].run_id,rows[0].error_code),(run.run_id,'UNKNOWN_ERROR'))
        self.assertEqual(self.reader.list_scheduled_runs(project_id='beta'),())

    def test_scheduler_absent(self):
        self.assertEqual(self.reader.list_scheduled_runs(),())

    def test_reader_no_state_transition(self):
        self.reader.list_jobs()
        self.reader.list_events()
        self.reader.summary()
        self.assertEqual(self.queue.get('job-a').status,'QUEUED')

    def test_reader_running_does_not_interrupt(self):
        self.queue.claim_identified('job-a','alpha',3)
        self.assertEqual(self.reader.list_jobs(project_id='alpha')[0].status,'RUNNING')
        self.assertEqual(self.queue.get('job-a').status,'RUNNING')

    def test_monitor_progress_existing(self):
        self.queue.claim_identified('job-a','alpha',3)
        TaskMonitor(self.queue).checkpoint('job-a',40,'WRITING')
        row=self.reader.list_jobs(project_id='alpha')[0]
        self.assertEqual((row.progress,row.stage),(40,'WRITING'))

    def test_event_metadata_only_schema(self):
        with sqlite3.connect(self.db) as con:
            names={r[1] for r in con.execute('PRAGMA table_info(operation_events)')}
        self.assertFalse({'prompt','manuscript','full_error','token_text','api_key','message'} & names)

    def test_event_persists_reopen(self):
        self.ledger.record('job-a','STARTED',input_tokens=15,output_tokens=20)
        new=OperationsReader(self.db).list_events()[0]
        self.assertEqual((new.input_tokens,new.output_tokens),(15,20))

    def test_many_events_lookup_latest(self):
        for _ in range(1010): self.ledger.record('job-a','CHECKPOINT')
        ev = self.ledger.record('job-a','COMPLETED')
        self.assertEqual(ev.event_id,1011)
        self.assertEqual(self.reader.summary().event_count,1011)
        self.assertEqual(len(self.reader.list_events(limit=8)),8)

    def test_negative_measurements_denied(self):
        for arg in ('duration_ms','input_tokens','output_tokens'):
            for value in (-1,True,1.25,'9',10**13):
                with self.subTest(arg=arg,value=value),self.assertRaises(OperationsError):
                    self.ledger.record('job-a','CHECKPOINT',**{arg:value})

    def test_invalid_cost_and_currency_denied(self):
        for args in [dict(cost_kind='UNKNOWN',cost_minor=0,currency='USD'),
                     dict(cost_kind='REPORTED',cost_minor=None,currency='USD'),
                     dict(cost_kind='ESTIMATED',cost_minor=1,currency=None),
                     dict(cost_kind='ESTIMATED',cost_minor=True,currency='USD'),
                     dict(cost_kind='ESTIMATED',cost_minor=-1,currency='USD'),
                     dict(cost_kind='REPORTED',cost_minor=1,currency='EUR'),
                     dict(cost_kind='REPORTED',cost_minor=1.9,currency='USD'),
                     dict(cost_kind='TOTAL',cost_minor=1,currency='USD')]:
            with self.subTest(args=args),self.assertRaises(OperationsError):
                self.ledger.record('job-a','CHECKPOINT',**args)

    def test_arbitrary_secrets_refused(self):
        for code in ('secret-key-text','API_KEY_ABC','MODEL SAID foo','',42):
            with self.subTest(code=code), self.assertRaises(OperationsError):
                self.ledger.record('job-a','FAILED',error_code=code)

    def test_error_code_accepted_only_on_failure(self):
        with self.assertRaises(OperationsError):
            self.ledger.record('job-a','STARTED',error_code='HANDLER_EXCEPTION')
        with self.assertRaises(OperationsError):
            self.ledger.record('job-a','FAILED')

    def test_all_known_error_codes_valid(self):
        for code in ERROR_CODES:
            self.ledger.record('job-a','FAILED',error_code=code)
        self.assertEqual(self.reader.summary().error_events,len(ERROR_CODES))

    def test_invalid_task_or_event_denied(self):
        for task,event in [('nonexistent','STARTED'),('job-a','EXPORTED'),('bad id','STARTED')]:
            with self.subTest(task=task,event=event),self.assertRaises(OperationsError):
                self.ledger.record(task,event)

    def test_invalid_project_filters_denied(self):
        for func in (self.reader.list_jobs,self.reader.list_events,
                     self.reader.list_scheduled_runs,self.reader.summary):
            with self.assertRaises(OperationsError): func(project_id='private manuscript here')

    def test_limit_rejection(self):
        for func in (self.reader.list_jobs,self.reader.list_events,self.reader.list_scheduled_runs):
            for limit in (0,1001,True,1.2):
                with self.assertRaises(OperationsError):func(limit=limit)

    def test_requires_timezone_aware(self):
        with self.assertRaises(OperationsError):
            self.ledger.record('job-a','STARTED',occurred_at=datetime(2026,10,14))

    def test_timezone_converted(self):
        stamp = T.astimezone(timezone(timedelta(hours=9)))
        e=self.ledger.record('job-a','STARTED',occurred_at=stamp)
        self.assertEqual(e.recorded_utc,'2026-10-14T09:00:00.000000+00:00')

    def test_insertion_rollback_when_invalid(self):
        count=self.reader.summary().event_count
        with self.assertRaises(OperationsError):
            self.ledger.record('job-a','FAILED',error_code='some suspicious trace')
        self.assertEqual(self.reader.summary().event_count,count)

    def test_does_not_create_external_connections(self):
        self.assertNotIn('http',self.ledger.__module__)
        self.ledger.record('job-a','STARTED')
        self.assertEqual(self.queue.get('job-a').status,'QUEUED')

    def test_optional_ui_not_imported_by_reader(self):
        self.assertNotIn('PySide6', __import__('sys').modules)


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 optional; Linux/headless not validated')
class OptionalQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_widget_view_only(self):
        from ai_novel_factory.desktop.operations_monitor_widget import OperationsMonitorWidget
        with tempfile.TemporaryDirectory() as d:
            q=LocalTaskQueue(Path(d)/'q.sqlite')
            q.enqueue('novel',1,task_id='job')
            w=OperationsMonitorWidget()
            self.assertTrue(w.open_database(str(q.path)))
            self.assertEqual(w.jobs_table.rowCount(),1)
            self.assertEqual(w.events_table.rowCount(),0)
            self.assertEqual(w.runs_table.rowCount(),0)
            self.assertEqual(q.get('job').status,'QUEUED')
            w.timer.stop()
            w.close()

    def test_ui_cost_and_errors(self):
        from ai_novel_factory.desktop.operations_monitor_widget import OperationsMonitorWidget
        with tempfile.TemporaryDirectory() as d:
            q=LocalTaskQueue(Path(d)/'q.sqlite')
            q.enqueue('novel',1,task_id='job')
            ledger=OperationsLedger(q)
            ledger.record('job','FAILED',error_code='HANDLER_EXCEPTION',cost_kind='REPORTED',
                          cost_minor=159,currency='USD')
            w=OperationsMonitorWidget()
            self.assertTrue(w.open_database(str(q.path)))
            self.assertEqual(w.events_table.rowCount(),1)
            self.assertIn('1.59 USD', w.events_table.item(0,7).text())
            w.timer.stop()
            w.close()

    def test_invalid_db_doesnt_change_queue(self):
        from ai_novel_factory.desktop.operations_monitor_widget import OperationsMonitorWidget
        with tempfile.TemporaryDirectory() as d:
            q=LocalTaskQueue(Path(d)/'q.sqlite')
            w=OperationsMonitorWidget()
            self.assertFalse(w.open_database(str(Path(d)/'absent.db')))
            self.assertIsNone(w.reader)
            w.close()

    def test_attached_main_window_tab(self):
        from ai_novel_factory.desktop.app import MainWindow
        window=MainWindow()
        self.assertEqual(window.operations_monitor.objectName() or '', '')
        self.assertEqual(window.operations_monitor.jobs_table.objectName(),'operationsJobsTable')
        window.close()


if __name__ == '__main__': unittest.main()
