import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_novel_factory.architecture import load_contract, validate_contract

class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract(ROOT / "docs/architecture_decisions.json")

    def test_contract_is_valid(self):
        self.assertEqual(validate_contract(self.contract), [])

    def test_ui_must_not_access_database_directly(self):
        changed = json.loads(json.dumps(self.contract))
        changed["connections"].append({"from": "desktop", "to": "memory", "via": "direct SQL"})
        self.assertTrue(validate_contract(changed))

    def test_no_raw_reference_to_writer(self):
        changed = json.loads(json.dumps(self.contract))
        changed["connections"].append({"from": "reference_analyzer", "to": "writer", "via": "raw text"})
        self.assertTrue(validate_contract(changed))

    def test_approval_guard_cannot_be_removed(self):
        changed = json.loads(json.dumps(self.contract))
        changed["nonnegotiable_controls"].remove("NO_PUBLICATION_WITHOUT_EXPLICIT_USER_APPROVAL")
        self.assertTrue(validate_contract(changed))

    def test_undecided_deployment_not_assumed(self):
        changed = json.loads(json.dumps(self.contract))
        changed["deployment"]["worker_host"] = "CLOUD_ALREADY_CONNECTED"
        self.assertTrue(validate_contract(changed))

if __name__ == "__main__":
    unittest.main()
