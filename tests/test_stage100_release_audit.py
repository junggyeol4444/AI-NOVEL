"""Stage 100: local release docs, evidence gates and fail-closed release audit."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'stage100_release_audit.py'
SPEC = importlib.util.spec_from_file_location('stage100_release_audit', SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in (*mod.REQUIRED_DOCUMENTS, *mod.RELEASE_COMPONENTS):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text('placeholder', encoding='utf-8')
        self.clean = {
            '95_official_api': dict(official_api_spec_verified=True, official_sandbox_upload_verified=True),
            '96_platform_rules': dict(official_platform_specification_verified=True, official_platform_upload_tested=True),
            '97_windows_exe': dict(windows_exe_built=True, windows_exe_executed=True),
            '98_install_guide': dict(acceptance_documentation_and_diagnostic='IMPLEMENTED_LOCAL_ONLY'),
            '99_windows_acceptance': dict(windows_acceptance_met=True, windows_exe_actual_runtime='PASS',
                                          windows_real_comprehensive_regression='PASS', physical_gui='PASS'),
        }
        for name, (relative, _) in mod.EVIDENCE.items():
            self.save(relative, self.clean[name])

    def save(self, relative, value):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value), encoding='utf-8')

    def test_actual_prior_source_evidence_blocks_release(self):
        audit = mod.audit(SCRIPT.parents[1])
        self.assertEqual(audit['release_status'], 'BLOCKED')
        self.assertFalse(audit['ready_for_public_release'])
        self.assertIn('95_official_api', audit['blocking_items'])
        self.assertIn('99_windows_acceptance', audit['blocking_items'])

    def test_stage_and_real_requirement_id(self):
        self.assertEqual(mod.audit(self.root)['stage'], 100)
        self.assertEqual(mod.audit(self.root)['requirement'], 'ANF-REQ-072')

    def test_linux_never_auto_certifies_windows_evidence(self):
        checks = mod.assess_evidence(self.clean, os_name='posix')
        self.assertEqual(checks['97_windows_exe']['status'], 'UNVERIFIED')
        self.assertEqual(checks['99_windows_acceptance']['status'], 'UNVERIFIED')

    def test_optimistic_reports_only_pending_manual_signoff(self):
        result = mod.audit(self.root, os_name='nt')
        self.assertEqual(result['release_status'], 'PENDING_MANUAL_SIGNOFF')
        self.assertFalse(result['ready_for_public_release'])
        self.assertFalse(result['user_acceptance_automatically_granted'])

    def test_never_contact_network(self):
        result = mod.audit(self.root)
        self.assertFalse(result['network_or_installation_performed'])
        self.assertFalse(result['official_platform_upload_performed'])
        self.assertFalse(result['actual_windows_build_performed_by_audit'])

    def test_missing_report_blocks(self):
        (self.root / mod.EVIDENCE['95_official_api'][0]).unlink()
        result = mod.audit(self.root, os_name='nt')
        self.assertIn('95_official_api', result['blocking_items'])

    def test_corrupted_report_blocks(self):
        p = self.root / mod.EVIDENCE['96_platform_rules'][0]
        p.write_text('{BAD', encoding='utf8')
        self.assertEqual(mod.audit(self.root, os_name='nt')['evidence_checks']['96_platform_rules']['status'], 'UNVERIFIED')

    def test_array_report_blocks(self):
        self.save(mod.EVIDENCE['95_official_api'][0], [])
        self.assertIn('95_official_api', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_empty_object_blocks(self):
        self.save(mod.EVIDENCE['97_windows_exe'][0], {})
        self.assertIn('97_windows_exe', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_truthy_strings_not_accepted(self):
        fake = dict(self.clean['95_official_api'], official_api_spec_verified='true')
        self.save(mod.EVIDENCE['95_official_api'][0], fake)
        self.assertIn('95_official_api', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_one_missing_api_evidence_blocks(self):
        bad = dict(self.clean['95_official_api'], official_sandbox_upload_verified=False)
        self.save(mod.EVIDENCE['95_official_api'][0], bad)
        self.assertIn('95_official_api', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_one_missing_platform_evidence_blocks(self):
        bad = dict(self.clean['96_platform_rules'], official_platform_upload_tested=False)
        self.save(mod.EVIDENCE['96_platform_rules'][0], bad)
        self.assertIn('96_platform_rules', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_windows_exe_not_built_blocks(self):
        self.save(mod.EVIDENCE['97_windows_exe'][0], dict(windows_exe_built=False, windows_exe_executed=True))
        self.assertIn('97_windows_exe', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_windows_exe_not_executed_blocks(self):
        self.save(mod.EVIDENCE['97_windows_exe'][0], dict(windows_exe_built=True, windows_exe_executed=False))
        self.assertIn('97_windows_exe', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_installation_guide_claim_must_be_exact(self):
        self.save(mod.EVIDENCE['98_install_guide'][0], dict(acceptance_documentation_and_diagnostic='PASS'))
        self.assertIn('98_install_guide', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_gui_missing_stays_unverified(self):
        x = dict(self.clean['99_windows_acceptance'], physical_gui='UNVERIFIED')
        self.save(mod.EVIDENCE['99_windows_acceptance'][0], x)
        self.assertIn('99_windows_acceptance', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_gui_boolean_not_pass(self):
        x = dict(self.clean['99_windows_acceptance'], physical_gui=True)
        self.save(mod.EVIDENCE['99_windows_acceptance'][0], x)
        self.assertIn('99_windows_acceptance', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_regression_unverified_blocks(self):
        x = dict(self.clean['99_windows_acceptance'], windows_real_comprehensive_regression='UNVERIFIED')
        self.save(mod.EVIDENCE['99_windows_acceptance'][0], x)
        self.assertIn('99_windows_acceptance', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_missing_user_manual_blocks(self):
        (self.root / 'docs/stage100_user_manual.md').unlink()
        result = mod.audit(self.root, os_name='nt')
        self.assertIn('missing_document:docs/stage100_user_manual.md', result['blocking_items'])

    def test_source_inventory_missing_blocks(self):
        (self.root / 'pyproject.toml').unlink()
        result = mod.audit(self.root, os_name='nt')
        self.assertIn('missing_release_component', result['blocking_items'])

    def test_source_inventory_has_expected_hash(self):
        result = mod.inventory(self.root)
        x = result['files']['pyproject.toml']
        self.assertTrue(x['present'])
        self.assertEqual(len(x['sha256']), 64)
        self.assertEqual(x['bytes'], len(b'placeholder'))

    def test_file_edit_changes_hash(self):
        old = mod.inventory(self.root)['files']['README.md']['sha256']
        (self.root / 'README.md').write_text('updated', encoding='utf8')
        self.assertNotEqual(old, mod.inventory(self.root)['files']['README.md']['sha256'])

    def test_symlink_document_rejected(self):
        p = self.root / 'docs/stage100_user_manual.md'
        p.unlink()
        p.symlink_to(self.root / 'README.md')
        self.assertIn('missing_document:docs/stage100_user_manual.md', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_symlink_report_rejected(self):
        p = self.root / mod.EVIDENCE['95_official_api'][0]
        p.unlink()
        p.symlink_to(self.root / mod.EVIDENCE['96_platform_rules'][0])
        self.assertIn('95_official_api', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_large_report_rejected(self):
        p = self.root / mod.EVIDENCE['95_official_api'][0]
        p.write_bytes(b'A' * 2000001)
        self.assertIn('95_official_api', mod.audit(self.root, os_name='nt')['blocking_items'])

    def test_output_refuses_overwrite(self):
        p = self.root / 'evidence.json'
        mod.write_report(p, {'x': 1})
        with self.assertRaises(FileExistsError):
            mod.write_report(p, {'x': 2})
        self.assertEqual(json.loads(p.read_text('utf8')), {'x': 1})

    def test_output_utf8_and_newline(self):
        p = self.root / 'report.json'
        mod.write_report(p, {'상태': '보류'})
        self.assertTrue(p.read_bytes().endswith(b'\n'))
        self.assertEqual(json.loads(p.read_text('utf8'))['상태'], '보류')

    def test_missing_local_docs_and_sensitive_value_not_in_report(self):
        r = mod.audit(self.root)
        self.assertNotIn('fiction_private_password_ABC', json.dumps(r))
        self.assertFalse(r['ready_for_public_release'])

    def test_requirements_present_in_source(self):
        root = SCRIPT.parents[1]
        data = (root / 'docs/requirements.md').read_text('utf8')
        self.assertIn('ANF-REQ-072', data)
        self.assertIn('ANF-REQ-001', data)
        self.assertIn('ANF-REQ-066', data)

    def test_local_manuscript_is_not_used_in_inventory(self):
        (self.root / 'my_secret_novel.txt').write_text('private manuscript', encoding='utf8')
        self.assertNotIn('my_secret_novel.txt', mod.inventory(self.root)['files'])

    def test_checked_documents_exist_in_real_project(self):
        root = SCRIPT.parents[1]
        for n in mod.REQUIRED_DOCUMENTS:
            with self.subTest(n=n):
                self.assertTrue((root / n).is_file())


if __name__ == '__main__':
    unittest.main()
