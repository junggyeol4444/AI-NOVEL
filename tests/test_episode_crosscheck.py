"""Cross-episode safety and bounded repeat checks, not Qwen authoring QA."""
import unittest

from ai_novel_factory.episode_crosscheck import screen_cross_episode_reuse


class CrossEpisodeBoundedTests(unittest.TestCase):
    def test_detects_same_long_original_sentence_across_three_chapters(self):
        repeated = '조사자는 망가진 기록을 찾아 사서에게 그날 벌어진 일을 물었다.'
        before = (
            '사서는 창문을 닫았다. ' + repeated,
            '조사자는 창밖을 보며 새로운 정보가 필요한 이유를 생각했다.',
            '사서는 그 기록이 거짓임을 알게 됐다. ' + repeated)
        new = repeated + ' 사서는 다시 오래된 지도에 표시를 남겼다.'
        report = screen_cross_episode_reuse(new, before)
        self.assertEqual(report.prior_episodes_examined, 3)
        self.assertEqual(report.exact_sentence_reuses, 1)
        self.assertEqual(report.affected_prior_episodes, 2)
        self.assertFalse(report.literary_approved)
        self.assertTrue(report.checked_scope_only)
        self.assertFalse(hasattr(report, 'raw_matched_sentences'))

    def test_distinct_episode_does_not_invent_cross_check_certificate(self):
        earlier = '사서는 부두의 창고를 살펴보며 항구 명세서를 정리했다.'
        current = '조사자는 눈 덮인 산길을 따라 낯선 숙소에 도착했다.'
        report = screen_cross_episode_reuse(current, (earlier,))
        self.assertEqual(report.exact_sentence_reuses, 0)
        self.assertFalse(report.literary_approved)

    def test_no_prior_means_unexamined_not_automatic_release_pass(self):
        report = screen_cross_episode_reuse(
            '사서는 책을 들고 원고의 빈 칸을 확인하기 시작했다.', ())
        self.assertEqual(report.prior_episodes_examined, 0)
        self.assertFalse(report.literary_approved)

    def test_detects_old_chapter_match_outside_previous_three(self):
        repeated = '조사자는 사서와 함께 사라진 장부를 찾아 지하 보관실로 내려갔다.'
        earlier = tuple(
            repeated if index == 0 else
            f'사서는 {index}번째 기록의 사건 날짜를 다시 확인했다.'
            for index in range(250))
        result = screen_cross_episode_reuse(repeated, earlier)
        self.assertEqual(result.prior_episodes_examined, 250)
        self.assertEqual(result.affected_prior_episodes, 1)
        self.assertEqual(result.exact_sentence_reuses, 1)
        self.assertFalse(result.literary_approved)
        with self.assertRaises(ValueError):
            screen_cross_episode_reuse(repeated, earlier + (repeated,))

    def test_overlong_or_invalid_inputs_rejected_without_processing(self):
        current = '사서는 오래된 기록을 확인한 뒤 동료를 찾았다.'
        for previous in (('a' * 100001,), tuple('a' for _ in range(4)), (None,)):
            with self.subTest(previous=type(previous)):
                with self.assertRaises(ValueError):
                    screen_cross_episode_reuse(current, previous)
        with self.assertRaises(ValueError):
            screen_cross_episode_reuse('', ())


if __name__ == '__main__':
    unittest.main()
