"""Stage 51: deterministic offline draft contract tests."""
import unittest
from ai_novel_factory.planning import PlanningInput, PlanningError, draft_premise


class PlanningTests(unittest.TestCase):
    def test_acceptance_fields(self):
        result = draft_premise(PlanningInput('현대판타지', '회귀와 기업경영', 250, '긴장감'))
        self.assertIn('회귀와 기업경영', result.title)
        self.assertIn('250회', result.logline)
        self.assertIn('세계관', result.world_outline)
        self.assertEqual(result.status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def test_reference_text_never_used(self):
        a = draft_premise(PlanningInput('판타지', '새 소재', 12, '밝음', ('참고작 비밀 문구',)))
        b = draft_premise(PlanningInput('판타지', '새 소재', 12, '밝음'))
        self.assertEqual(a, b)
        self.assertNotIn('비밀 문구', str(a))

    def test_deterministic(self):
        spec = PlanningInput('추리', '실종', 5, '어두움')
        self.assertEqual(draft_premise(spec), draft_premise(spec))

    def test_invalid_episodes(self):
        for n in (0, -1, 10001, True, 1.5):
            with self.subTest(n=n), self.assertRaises(PlanningError):
                draft_premise(PlanningInput('추리', '실종', n, '어두움'))

    def test_invalid_content(self):
        for text in ('', '  ', 'a\nsecret', 'x'*121):
            with self.subTest(text=text), self.assertRaises(PlanningError):
                draft_premise(PlanningInput('추리', text, 10, '어두움'))

    def test_invalid_references(self):
        for refs in (['A'], tuple(['A']*31), ('',)):
            with self.subTest(refs=type(refs)), self.assertRaises(PlanningError):
                draft_premise(PlanningInput('추리', '실종', 10, '어두움', refs))

    def test_no_external_dependency(self):
        result = draft_premise(PlanningInput('SF', '우주 항해', 3, '희망'))
        self.assertEqual(result.origin, 'USER_INPUT_TEMPLATE_NOT_AI')
