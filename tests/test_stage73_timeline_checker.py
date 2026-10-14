"""Stage 73: explicitly marked timeline/date/time/order checking, offline."""
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from ai_novel_factory.database.event_timeline import EventTimelineStore
from ai_novel_factory.timeline_checker import (
    TimelineMention, TimelineOrderClaim, TimelineCheckerError,
    check_timeline, check_episode_timeline, _definite_order, _intervals_overlap,
)


class TimelineCheckerTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = EventTimelineStore(Path(tmp.name) / 'events.db')
        self.addCleanup(self.store.close)
        self.project = self.store.create_project('오리지널 소설').project_id
        self.other = self.store.create_project('별개 작품').project_id
        self.first = self.store.create_event(self.project, title='사건 A', when='2026-10-01').event_id
        self.second = self.store.create_event(self.project, title='사건 B', when='2026-10-02').event_id
        self.text = '첫 사건이 일어났다. 그 뒤 둘째 사건을 회상한다.'
        self.a = TimelineMention(self.first, 0, len('첫 사건'), '첫 사건')
        at = self.text.index('둘째 사건')
        self.b = TimelineMention(self.second, at, at+5, '둘째 사건')

    def check(self, mentions=None, orders=(), manuscript=None, **kwargs):
        return check_timeline(self.store, self.project, 7,
                              self.text if manuscript is None else manuscript,
                              (self.a, self.b) if mentions is None else mentions,
                              orders, **kwargs)

    def test_empty_annotations_do_not_certify_entire_prose(self):
        result = self.check(mentions=())
        self.assertTrue(result.passed_declared_claims)
        self.assertEqual(result.examined_mentions, 0)
        self.assertIn('NOT_FULL_QC', result.status)
        self.assertFalse(result.persisted)
        self.assertFalse(result.publication_approved)

    def test_exact_day_matches(self):
        result = self.check(mentions=(replace(self.a, claimed_when='2026-10-01'),))
        self.assertEqual(result.findings, ())

    def test_wrong_day_flags_conflict(self):
        result = self.check(mentions=(replace(self.a, claimed_when='2026-10-05'),))
        self.assertEqual(result.findings[0].code, 'TIME_CONFLICT')
        self.assertEqual(result.findings[0].start, 0)

    def test_day_and_instant_inside_day_compatible(self):
        x = replace(self.a, claimed_when='2026-10-01T22:59:00+09:00')
        self.assertEqual(self.check(mentions=(x,)).findings, ())

    def test_day_ends_exclusively_at_midnight(self):
        x = replace(self.a, claimed_when='2026-10-02T00:00:00+00:00')
        self.assertEqual(self.check(mentions=(x,)).findings[0].code, 'TIME_CONFLICT')

    def test_timezone_converted_instant(self):
        event = self.store.create_event(self.project, title='시간대', when='2026-10-01T09:00:00+09:00')
        x = replace(self.a, event_id=event.event_id, claimed_when='2026-10-01T00:00:00+00:00')
        self.assertEqual(self.check(mentions=(x,)).findings, ())

    def test_precise_instant_mismatch(self):
        event = self.store.create_event(self.project, title='시간대', when='2026-10-01T09:00:00+09:00')
        x = replace(self.a, event_id=event.event_id, claimed_when='2026-10-01T00:01:00+00:00')
        self.assertEqual(self.check(mentions=(x,)).findings[0].code, 'TIME_CONFLICT')

    def test_unknown_date_reported_inconclusive(self):
        unknown = self.store.create_event(self.project, title='미정').event_id
        x = replace(self.a, event_id=unknown, claimed_when='2026-10-01')
        self.assertEqual(self.check(mentions=(x,)).findings[0].code, 'TIME_UNVERIFIABLE')

    def test_relative_date_offset(self):
        rel = self.store.create_event(self.project, title='상대', anchor_event_id=self.first,
                                      offset_minutes=60).event_id
        x = replace(self.a, event_id=rel, claimed_when='2026-10-01')
        self.assertEqual(self.check(mentions=(x,)).findings, ())
        y = replace(x, claimed_when='2026-10-03')
        self.assertEqual(self.check(mentions=(y,)).findings[0].code, 'TIME_CONFLICT')

    def test_relative_unknown_root_stays_unverifiable(self):
        root = self.store.create_event(self.project, title='불명').event_id
        rel = self.store.create_event(self.project, title='다음', anchor_event_id=root,
                                      offset_minutes=60).event_id
        x = replace(self.a, event_id=rel, claimed_when='2026-10-01')
        self.assertEqual(self.check(mentions=(x,)).findings[0].code, 'TIME_UNVERIFIABLE')

    def test_explicit_order_matches(self):
        r = self.check(orders=(TimelineOrderClaim(self.first, self.second),))
        self.assertEqual(r.findings, ())
        self.assertEqual(r.examined_order_claims, 1)

    def test_reverse_order_conflicts_with_dates(self):
        r = self.check(orders=(TimelineOrderClaim(self.second, self.first),))
        self.assertEqual(r.findings[0].code, 'ORDER_CONFLICT')

    def test_same_event_order_conflict(self):
        r = self.check(mentions=(self.a,), orders=(TimelineOrderClaim(self.first, self.first),))
        self.assertEqual(r.findings[0].code, 'ORDER_CONFLICT')

    def test_same_timestamp_strict_order_conflict(self):
        x = self.store.create_event(self.project, title='동시1', when='2026-10-01T00:00:00Z').event_id
        y = self.store.create_event(self.project, title='동시2', when='2026-10-01T09:00:00+09:00').event_id
        r = self.check(mentions=(replace(self.a,event_id=x),replace(self.b,event_id=y)),
                       orders=(TimelineOrderClaim(x,y),))
        self.assertEqual(r.findings[0].code, 'ORDER_CONFLICT')

    def test_overlapping_day_order_is_inconclusive(self):
        x = self.store.create_event(self.project, title='같은 날', when='2026-10-01').event_id
        r = self.check(mentions=(self.a, replace(self.b, event_id=x)),
                       orders=(TimelineOrderClaim(self.first,x),))
        self.assertEqual(r.findings[0].code, 'ORDER_UNVERIFIABLE')

    def test_unknown_order_is_inconclusive(self):
        x = self.store.create_event(self.project, title='미정1').event_id
        y = self.store.create_event(self.project, title='미정2').event_id
        r = self.check(mentions=(replace(self.a,event_id=x),replace(self.b,event_id=y)),
                       orders=(TimelineOrderClaim(x,y),))
        self.assertEqual(r.findings[0].code, 'ORDER_UNVERIFIABLE')

    def test_relative_root_order_without_absolute_date(self):
        root = self.store.create_event(self.project, title='기준').event_id
        after = self.store.create_event(self.project, title='후속', anchor_event_id=root,
                                        offset_minutes=90).event_id
        marks = (replace(self.a,event_id=root), replace(self.b,event_id=after))
        self.assertEqual(self.check(mentions=marks, orders=(TimelineOrderClaim(root,after),)).findings, ())
        self.assertEqual(self.check(mentions=marks, orders=(TimelineOrderClaim(after,root),))
                         .findings[0].code, 'ORDER_CONFLICT')

    def test_relative_same_offset_is_simultaneous(self):
        root = self.store.create_event(self.project, title='기준').event_id
        twin = self.store.create_event(self.project, title='동시', anchor_event_id=root,
                                       offset_minutes=0).event_id
        r = self.check(mentions=(replace(self.a,event_id=root),replace(self.b,event_id=twin)),
                       orders=(TimelineOrderClaim(root,twin),))
        self.assertEqual(r.findings[0].code, 'ORDER_CONFLICT')

    def test_transitive_explicit_order(self):
        middle = self.store.create_event(self.project, title='중간').event_id
        # Unset known dates so chronology proof depends on explicitly saved edges.
        p = self.store.create_event(self.project, title='처음').event_id
        q = self.store.create_event(self.project, title='끝').event_id
        self.store.add_order(self.project,p,middle)
        self.store.add_order(self.project,middle,q)
        marks=(replace(self.a,event_id=p),replace(self.b,event_id=q))
        self.assertFalse(self.check(mentions=marks, orders=(TimelineOrderClaim(p,q),)).findings)
        self.assertEqual(self.check(mentions=marks, orders=(TimelineOrderClaim(q,p),))
                         .findings[0].code, 'ORDER_CONFLICT')

    def test_flashback_text_order_never_automatically_checked(self):
        r = self.check(mentions=(self.b, self.a))
        self.assertEqual(r.findings, ())
        self.assertEqual(r.examined_order_claims, 0)

    def test_cross_project_event_rejected(self):
        foreign = self.store.create_event(self.other, title='외부').event_id
        with self.assertRaises(TimelineCheckerError):
            self.check(mentions=(replace(self.a, event_id=foreign),))

    def test_missing_event_rejected(self):
        with self.assertRaises(TimelineCheckerError):
            self.check(mentions=(replace(self.a, event_id='b'*32),))

    def test_invalid_mention_span_and_evidence(self):
        for kwargs in ({'start':True},{'start':-1},{'end':999},{'end':0},
                       {'evidence':'다른 문장'},{'evidence':''}, {'event_id':'oops'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TimelineCheckerError):
                self.check(mentions=(replace(self.a, **kwargs),))

    def test_duplicate_mentions_rejected(self):
        with self.assertRaises(TimelineCheckerError):
            self.check(mentions=(self.a,self.a))

    def test_same_event_different_spans_allowed(self):
        mention=replace(self.a,start=3,end=5,evidence=self.text[3:5])
        self.assertEqual(self.check(mentions=(self.a,mention)).examined_mentions,2)

    def test_duplicate_order_claims_rejected(self):
        order = TimelineOrderClaim(self.first,self.second)
        with self.assertRaises(TimelineCheckerError):
            self.check(orders=(order,order))

    def test_order_requires_both_cited_mentions(self):
        with self.assertRaises(TimelineCheckerError):
            self.check(mentions=(self.a,), orders=(TimelineOrderClaim(self.first,self.second),))

    def test_bad_claim_types_rejected(self):
        for mentions, orders in (([self.a],()), ((None,),()), ((self.a,),[None]),
                                 ((self.a,),('bad',)), ((),(None,))):
            with self.subTest(mentions=mentions,orders=orders), self.assertRaises(TimelineCheckerError):
                self.check(mentions=mentions,orders=orders)

    def test_date_claim_rejects_naive_and_invalid_values(self):
        for when in ('2026-02-30','2026-10-01T08:00:00','not-a-date','',True):
            with self.subTest(when=when), self.assertRaises(TimelineCheckerError):
                self.check(mentions=(replace(self.a,claimed_when=when),))

    def test_expected_revision_stale_rejected(self):
        old=self.store.get_project(self.project).revision
        self.store.create_event(self.project,title='추가')
        with self.assertRaisesRegex(TimelineCheckerError,'stale'):
            self.check(expected_project_revision=old)

    def test_current_revision_ok(self):
        current=self.store.get_project(self.project).revision
        self.assertEqual(self.check(expected_project_revision=current).project_revision,current)

    def test_revision_changing_during_check_rejected(self):
        original=self.store.list_events
        def mutate(*args):
            result=original(*args)
            self.store.create_event(self.project,title='검사 중 변경')
            return result
        with patch.object(self.store,'list_events',side_effect=mutate):
            with self.assertRaisesRegex(TimelineCheckerError,'changed'):
                self.check()

    def test_out_of_range_episode_and_revision_rejected(self):
        for episode in (0,-1,True,1_000_001,'3'):
            with self.subTest(episode=episode), self.assertRaises(TimelineCheckerError):
                check_timeline(self.store,self.project,episode,self.text,(self.a,))
        for revision in (-1,True,'2',2**31):
            with self.subTest(revision=revision), self.assertRaises(TimelineCheckerError):
                self.check(expected_project_revision=revision)

    def test_invalid_manuscript(self):
        for manuscript in ('','  ','x'*1_000_001,True):
            with self.subTest(manuscript=type(manuscript).__name__), self.assertRaises(TimelineCheckerError):
                self.check(manuscript=manuscript, mentions=())

    def test_limits_reject_large_input(self):
        with self.assertRaises(TimelineCheckerError):
            self.check(mentions=(self.a,)*501)
        with self.assertRaises(TimelineCheckerError):
            self.check(mentions=(self.a,),orders=(TimelineOrderClaim(self.first,self.first),)*501)

    def test_report_does_not_include_prose(self):
        r=self.check(mentions=(replace(self.a,claimed_when='2026-10-03'),))
        self.assertNotIn('첫 사건',repr(r))
        self.assertEqual(r.manuscript_sha256,sha256(self.text.encode()).hexdigest())
        self.assertEqual(r.findings[0].evidence_sha256,sha256('첫 사건'.encode()).hexdigest())
        self.assertFalse(r.persisted)
        self.assertFalse(r.publication_approved)

    def test_does_not_modify_database(self):
        before=self.store.get_project(self.project).revision
        r=self.check(orders=(TimelineOrderClaim(self.first,self.second),))
        self.assertEqual(r.project_revision,before)
        self.assertEqual(self.store.get_project(self.project).revision,before)

    def test_episode_adapter_valid_and_modified_rejected(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.project, 7, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        report = check_episode_timeline(self.store, preview, (self.a,self.b),
                                        (TimelineOrderClaim(self.first,self.second),))
        self.assertEqual(report.examined_mentions, 2)
        for bad in (replace(preview, draft='changed'),
                    replace(preview, persisted=True),
                    replace(preview, publication_approved=True),
                    replace(preview, status='FINAL'),
                    replace(preview, draft_sha256='0'*64)):
            with self.subTest(bad=bad.status), self.assertRaises(TimelineCheckerError):
                check_episode_timeline(self.store, bad, (self.a,))

    def test_episode_adapter_foreign_canon_rejected(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.other, 7, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        with self.assertRaises(TimelineCheckerError):
            check_episode_timeline(self.store, preview, (self.a,))

    def test_episode_adapter_rejects_non_preview(self):
        with self.assertRaises(TimelineCheckerError):
            check_episode_timeline(self.store,object(),())

    def test_helper_instant_overlap_rules(self):
        now=datetime(2026,10,1,tzinfo=timezone.utc)
        then=datetime(2026,10,2,tzinfo=timezone.utc)
        self.assertTrue(_intervals_overlap((now,then),(now,now)))
        self.assertFalse(_intervals_overlap((now,then),(then,then)))
        self.assertEqual(_definite_order((now,now),(now,now)),'NOT_BEFORE')


if __name__=='__main__':
    unittest.main()
