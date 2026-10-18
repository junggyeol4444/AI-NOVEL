"""Stage 68: offline task-control and monitoring regression coverage."""
from __future__ import annotations
from contextlib import closing

import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from ai_novel_factory.local_task_queue import LocalTaskQueue, TaskQueueError
from ai_novel_factory.task_monitor import TaskMonitor


class TaskMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'tasks.db'
        self.queue = LocalTaskQueue(self.path)
        self.monitor = TaskMonitor(self.queue)
        self.queue.enqueue('work-1', 1, task_id='job1')

    def test_snapshot_and_filter(self):
        self.queue.enqueue('work-2', 2, task_id='job2')
        row = self.monitor.get('job1')
        self.assertEqual((row.status, row.progress, row.stage), ('QUEUED', 0, 'PENDING'))
        self.assertEqual(len(self.monitor.list_tasks()), 2)
        self.assertEqual([x.task_id for x in self.monitor.list_tasks(project_id='work-1')], ['job1'])

    def test_list_never_includes_draft_columns(self):
        fields = set(self.monitor.get('job1').__dataclass_fields__)
        self.assertEqual(fields, {'task_id','project_id','episode_number','status',
                                  'progress','stage','attempts','error_code'})

    def test_pause_queued_prevents_claim(self):
        row = self.monitor.request_pause('job1')
        self.assertEqual(row.status, 'PAUSED')
        self.assertIsNone(self.queue.claim())

    def test_resume_queued_allows_claim(self):
        self.monitor.request_pause('job1')
        self.assertEqual(self.monitor.request_resume('job1').status, 'QUEUED')
        self.assertEqual(self.queue.claim().task_id, 'job1')

    def test_cancel_queued_terminal(self):
        self.assertEqual(self.monitor.request_cancel('job1').status, 'CANCELLED')
        self.assertEqual(self.queue.get('job1').status, 'INTERRUPTED')
        self.assertEqual(self.queue.get('job1').error_code, 'TASK_CANCELLED')
        self.assertIsNone(self.queue.claim())

    def test_cancel_paused_queued(self):
        self.monitor.request_pause('job1')
        self.assertEqual(self.monitor.request_cancel('job1').status, 'CANCELLED')

    def test_duplicate_cancel_terminal_rejected(self):
        self.monitor.request_cancel('job1')
        with self.assertRaises(TaskQueueError): self.monitor.request_cancel('job1')

    def test_running_pause_then_ack_resume(self):
        started = threading.Event()
        finished = threading.Event()
        def handler(project, ep, checkpoint):
            started.set()
            checkpoint(40, 'WRITING')
            finished.set()
            return True
        self.monitor.request_pause('job1')
        # Job cannot run until resumed.
        self.assertIsNone(self.monitor.run_one_controlled(handler))
        self.monitor.request_resume('job1')
        self.queue.claim()
        self.monitor.request_pause('job1')
        th = threading.Thread(target=lambda: self.monitor.checkpoint('job1', 40, 'WRITING', polling_seconds=0.02))
        th.start()
        self.addCleanup(lambda: (self.monitor.request_resume('job1') if self.monitor.get('job1').status == 'PAUSED' else None, th.join(2)))
        deadline = time.monotonic()+2
        while self.monitor.get('job1').status != 'PAUSED' and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(self.monitor.get('job1').status, 'PAUSED')
        self.assertTrue(th.is_alive())
        self.monitor.request_resume('job1')
        th.join(2)
        self.assertFalse(th.is_alive())
        self.assertEqual(self.monitor.get('job1').status, 'RUNNING')
        self.assertEqual(self.monitor.get('job1').progress, 40)

    def test_cancel_while_paused_unblocks_cooperative_worker(self):
        paused_ready = threading.Event()
        entered = threading.Event()
        def handler(_p, _n, checkpoint):
            entered.set()
            checkpoint(45, 'WRITING')
            return True
        self.queue.claim()
        self.monitor.request_pause('job1')
        # Emulate a worker already claimed before pause request.
        worker = threading.Thread(target=lambda: self._checkpoint_cancellable(paused_ready))
        worker.start()
        deadline = time.monotonic()+2
        while self.monitor.get('job1').status != 'PAUSED' and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(self.monitor.get('job1').status, 'PAUSED')
        self.monitor.request_cancel('job1')
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(paused_ready.is_set())
        self.assertEqual(self.queue.finish('job1', succeeded=False, error_code='TASK_CANCELLED').status,
                         'INTERRUPTED')

    def _checkpoint_cancellable(self, flag):
        from ai_novel_factory.task_monitor import TaskCancelled
        try:
            self.monitor.checkpoint('job1', 45, 'WRITING', polling_seconds=.02)
        except TaskCancelled:
            flag.set()

    def test_running_pause_requested_vs_acknowledged(self):
        self.queue.claim()
        self.assertEqual(self.monitor.request_pause('job1').status, 'PAUSE_REQUESTED')

    def test_cancel_running_at_checkpoint(self):
        self.queue.claim()
        self.assertEqual(self.monitor.request_cancel('job1').status, 'CANCEL_REQUESTED')
        from ai_novel_factory.task_monitor import TaskCancelled
        with self.assertRaises(TaskCancelled): self.monitor.checkpoint('job1', 10, 'PLANNING')

    def test_cancel_running_wins_finish(self):
        self.queue.claim()
        self.monitor.request_cancel('job1')
        self.assertEqual(self.queue.finish('job1', succeeded=True).status, 'INTERRUPTED')
        self.assertEqual(self.monitor.get('job1').status, 'CANCELLED')

    def test_cancel_legacy_run_one_handler(self):
        def handler(*_):
            self.monitor.request_cancel('job1')
            return True
        self.assertEqual(self.queue.run_one(handler).status, 'INTERRUPTED')

    def test_success_100_progress_only_on_finish(self):
        def handler(project, episode, checkpoint):
            checkpoint(20, 'PLANNING')
            checkpoint(80, 'CHECKING')
            self.assertEqual(self.monitor.get('job1').progress, 80)
            return True
        self.assertEqual(self.monitor.run_one_controlled(handler).status, 'COMPLETED')
        self.assertEqual(self.monitor.get('job1').progress, 100)
        self.assertEqual(self.monitor.get('job1').stage, 'FINISHED')

    def test_nontrue_handler_is_failure(self):
        row = self.monitor.run_one_controlled(lambda *_: 'True')
        self.assertEqual((row.status,row.error_code), ('FAILED','HANDLER_NOT_SUCCESSFUL'))
        self.assertNotEqual(self.monitor.get('job1').progress, 100)

    def test_handler_error_does_not_leak_secret(self):
        def bad(*_): raise RuntimeError('secret novel body')
        self.assertEqual(self.monitor.run_one_controlled(bad).error_code, 'HANDLER_EXCEPTION')
        self.assertNotIn('secret novel body', self.path.read_bytes().decode('utf-8','ignore'))

    def test_async_controlled_handler(self):
        th = self.monitor.run_one_controlled_async(lambda p, e, progress: progress(90,'REVIEW') or True)
        th.join(2)
        self.assertFalse(th.is_alive())
        self.assertEqual(self.monitor.get('job1').status, 'COMPLETED')

    def test_checkpoint_requires_running(self):
        from ai_novel_factory.task_monitor import TaskCancelled
        with self.assertRaises(TaskCancelled): self.monitor.checkpoint('job1', 1, 'WRITING')

    def test_progress_rejects_invalid_and_backward(self):
        self.queue.claim()
        for percent, stage in ((-1,'WRITING'), (100,'WRITING'), (True,'WRITING'),
                               (10,'unexpected'), (10,'private manuscript')):
            with self.subTest(percent=percent,stage=stage), self.assertRaises(TaskQueueError):
                self.monitor.checkpoint('job1',percent,stage)
        self.monitor.checkpoint('job1', 50, 'WRITING')
        with self.assertRaises(TaskQueueError): self.monitor.checkpoint('job1',49,'CHECKING')

    def test_invalid_control_ids_and_missing_task(self):
        for name in ('', 'bad id', '한글', 'x\n'):
            for fn in (self.monitor.get, self.monitor.request_pause, self.monitor.request_resume,
                       self.monitor.request_cancel):
                with self.subTest(name=name,fn=fn), self.assertRaises(TaskQueueError): fn(name)
        for fn in (self.monitor.request_pause,self.monitor.request_resume,self.monitor.request_cancel):
            with self.assertRaises(TaskQueueError): fn('unknown')

    def test_resume_not_paused_rejected(self):
        with self.assertRaises(TaskQueueError): self.monitor.request_resume('job1')

    def test_no_pause_terminal(self):
        self.monitor.run_one_controlled(lambda *_: True)
        with self.assertRaises(TaskQueueError): self.monitor.request_pause('job1')

    def test_cancellation_request_cannot_be_overridden(self):
        self.queue.claim()
        self.monitor.request_cancel('job1')
        with self.assertRaises(TaskQueueError): self.monitor.request_pause('job1')
        with self.assertRaises(TaskQueueError): self.monitor.request_resume('job1')

    def test_restart_marks_running_interrupted(self):
        self.queue.claim()
        self.monitor.checkpoint('job1',20,'WRITING')
        reopened = LocalTaskQueue(self.path)
        self.assertEqual(reopened.get('job1').status, 'INTERRUPTED')
        self.assertEqual(TaskMonitor(reopened).get('job1').progress,20)

    def test_observer_does_not_interrupt_running(self):
        self.queue.claim()
        observer = TaskMonitor(LocalTaskQueue(self.path, recover_running=False))
        self.assertEqual(observer.get('job1').status, 'RUNNING')
        self.assertEqual(self.queue.get('job1').status, 'RUNNING')

    def test_queue_without_monitor_still_operates(self):
        self.assertEqual(self.queue.run_one(lambda *_: True).status, 'COMPLETED')

    def test_progress_survives_reopening_without_recovery(self):
        self.queue.claim()
        self.monitor.checkpoint('job1',65,'ASSEMBLING')
        new_monitor=TaskMonitor(LocalTaskQueue(self.path,recover_running=False))
        self.assertEqual((new_monitor.get('job1').progress,new_monitor.get('job1').stage),(65,'ASSEMBLING'))

    def test_no_external_network_in_monitor(self):
        from unittest.mock import patch
        with patch('socket.socket', side_effect=AssertionError('network')):
            self.monitor.list_tasks()
            self.monitor.request_pause('job1')
            self.monitor.request_resume('job1')
            self.monitor.request_cancel('job1')

    def test_legacy_queue_migration_retains_rows(self):
        old = Path(self.tmp.name) / 'legacy.db'
        with closing(sqlite3.connect(old)) as db, db:
            db.execute("CREATE TABLE local_tasks (task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, episode_number INTEGER NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, error_code TEXT)")
            db.execute("INSERT INTO local_tasks VALUES ('legacy','old',2,'QUEUED',0,NULL)")
        migrated=LocalTaskQueue(old)
        self.assertEqual(TaskMonitor(migrated).get('legacy').status,'QUEUED')
        self.assertEqual(TaskMonitor(migrated).request_pause('legacy').status,'PAUSED')

    def test_completed_not_approval(self):
        self.monitor.run_one_controlled(lambda *_: True)
        self.assertFalse(hasattr(self.monitor.get('job1'), 'publication_approved'))
        self.assertFalse(hasattr(self.monitor.get('job1'), 'manuscript'))

    def test_concurrent_cancel_finished_worker(self):
        started = threading.Event()
        continue_event = threading.Event()
        def handler(_p,_n,cp):
            cp(20,'WRITING')
            started.set()
            continue_event.wait(2)
            return True
        worker=self.monitor.run_one_controlled_async(handler)
        self.assertTrue(started.wait(2))
        self.monitor.request_cancel('job1')
        continue_event.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.monitor.get('job1').status, 'CANCELLED')


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class TaskMonitorGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls._created_app = QApplication.instance() is None
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        # Release GUI fixtures before Python unloads PySide6/shiboken6.
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        for widget in list(QApplication.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        cls.app.processEvents()
        if cls._created_app:
            cls.app.quit()
        cls.app = None

    def test_page_present_and_no_auto_connection(self):
        from ai_novel_factory.desktop.app import MainWindow
        window=MainWindow()
        try:
            self.assertIsNone(window.task_monitor.monitor)
            self.assertEqual(window.task_monitor.table.rowCount(),0)
            self.assertFalse(window.task_monitor.timer.isActive())
        finally:
            window.plot_editor.session.close()
            window.close()

    def test_open_existing_and_pause(self):
        from ai_novel_factory.desktop.task_monitor_widget import TaskMonitorWidget
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'queue.db'
            queue=LocalTaskQueue(path)
            queue.enqueue('p',1,task_id='a')
            widget=TaskMonitorWidget()
            try:
                widget.open_database(str(path))
                self.assertEqual(widget.table.rowCount(),1)
                widget.table.selectRow(0)
                widget.pause_button.click()
                self.assertEqual(TaskMonitor(queue).get('a').status,'PAUSED')
            finally:
                widget.timer.stop()
                widget.close()

    def test_invalid_file_does_not_create_db(self):
        from ai_novel_factory.desktop.task_monitor_widget import TaskMonitorWidget
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing.db'
            widget=TaskMonitorWidget()
            widget.open_database(str(path))
            self.assertFalse(path.exists())
            self.assertIsNone(widget.monitor)
            widget.close()

if __name__ == '__main__': unittest.main()
