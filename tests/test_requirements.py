import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "docs" / "requirements.json").read_text(encoding="utf-8"))

class RequirementTests(unittest.TestCase):
    def test_stage_and_product(self):
        self.assertEqual(DATA["stage"], 1)
        self.assertEqual(DATA["target"], "Windows EXE")

    def test_ids_unique_and_sequential(self):
        ids = [r["id"] for r in DATA["requirements"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [f"ANF-REQ-{i:03}" for i in range(1, len(ids)+1)])

    def test_traceability_and_acceptance(self):
        self.assertGreaterEqual(len(DATA["requirements"]), 50)
        for r in DATA["requirements"]:
            self.assertTrue(r["source_section"])
            self.assertTrue(r["acceptance"])
            self.assertTrue(r["requirement"])
            self.assertIn(r["priority"], {"MUST", "SHOULD", "COULD"})
            self.assertGreaterEqual(r["stage"], 1)
            self.assertLessEqual(r["stage"], 100)

    def test_critical_controls(self):
        body = " ".join(r["requirement"] for r in DATA["requirements"])
        for term in ("Novel Bible", "유사성", "복제", "승인", "Windows"):
            self.assertIn(term, body)

if __name__ == "__main__":
    unittest.main()