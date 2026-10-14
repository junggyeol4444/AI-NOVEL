"""Stage 8 UI navigation tests, runnable without PySide6."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_novel_factory.desktop.navigation import SECTIONS, section_for_key

class NavigationTests(unittest.TestCase):
    def test_has_twelve_sections_from_project_plan(self):
        self.assertEqual(len(SECTIONS), 12)
        self.assertEqual(SECTIONS[0].key, 'novels')
        self.assertEqual(SECTIONS[-1].key, 'publication')

    def test_unique_keys_and_labels(self):
        self.assertEqual(len({s.key for s in SECTIONS}), len(SECTIONS))
        self.assertEqual(len({s.label for s in SECTIONS}), len(SECTIONS))
        self.assertTrue(all(s.description for s in SECTIONS))

    def test_reference_and_similarity_pages_present(self):
        self.assertEqual(section_for_key('references').label, 'Reference Novels')
        self.assertEqual(section_for_key('similarity').label, 'Similarity Reports')
        with self.assertRaises(KeyError):
            section_for_key('not-a-section')

    def test_offline_cli_contract_check(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'src')
        result = subprocess.run(
            [sys.executable, '-m', 'ai_novel_factory.desktop', '--check'],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('12 sections', result.stdout)

if __name__ == '__main__':
    unittest.main()
