"""Stage 99: honest Windows-only acceptance evidence and offline safeguards."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'scripts'/'stage99_windows_acceptance.py'
spec = importlib.util.spec_from_file_location('stage99_acceptance', SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
OK_SMOKE = {'--check': True, '--gui-smoke': True}
OK_REGRESSION = dict(module_count=113,group_count=8,module_coverage_exact=True,
                     all_exit_codes_zero=True,total=200,passed=199,skipped=1,
                     failures=0,errors=0)

class Stage99AcceptanceTests(unittest.TestCase):
    def assess(self, **kw):
        vals = dict(os_name='nt',python_version=(3,12),exe_exists=True,pe_valid=True,
                    smoke=OK_SMOKE,regression=OK_REGRESSION)
        vals.update(kw)
        return a.assess(**vals)

    def test_full_automated_windows_only(self):
        r=self.assess()
        self.assertTrue(r['windows_acceptance_met'])
        self.assertEqual(r['windows_exe_runtime'],'PASS')
        self.assertEqual(r['windows_comprehensive_regression'],'PASS')
        self.assertEqual(r['physical_display_user_review'],'UNVERIFIED')

    def test_linux_never_passes_even_with_forged_data(self):
        r=self.assess(os_name='posix')
        self.assertFalse(r['windows_acceptance_met'])
        self.assertEqual(r['windows_exe_runtime'],'UNVERIFIED')
        self.assertEqual(r['windows_comprehensive_regression'],'UNVERIFIED')

    def test_no_windows_when_python_313(self):
        self.assertFalse(self.assess(python_version=(3,13))['windows_acceptance_met'])

    def test_exe_absent_blocks(self):
        self.assertFalse(self.assess(exe_exists=False)['windows_acceptance_met'])

    def test_pe_invalid_blocks(self):
        self.assertFalse(self.assess(pe_valid=False)['windows_acceptance_met'])

    def test_empty_checks_unknown(self):
        r=self.assess(smoke={})
        self.assertFalse(r['windows_acceptance_met'])
        self.assertEqual(r['windows_exe_runtime'],'UNVERIFIED')

    def test_missing_second_smoke(self):
        self.assertFalse(self.assess(smoke={'--check':True})['windows_acceptance_met'])

    def test_failed_smoke(self):
        r=self.assess(smoke={'--check': True, '--gui-smoke': False})
        self.assertEqual(r['windows_exe_runtime'],'FAIL')
        self.assertFalse(r['windows_acceptance_met'])

    def test_missing_regression(self):
        self.assertFalse(self.assess(regression=None)['windows_acceptance_met'])

    def test_regression_no_coverage(self):
        self.assertEqual(self.assess(regression={**OK_REGRESSION, 'module_coverage_exact':False})['windows_comprehensive_regression'],'FAIL')

    def test_regression_nonzero_exit(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'all_exit_codes_zero':False})['windows_acceptance_met'])

    def test_regression_failed_count(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'failures':1})['windows_acceptance_met'])

    def test_regression_error_count(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'errors':1})['windows_acceptance_met'])

    def test_regression_missing_groups(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'group_count':7})['windows_acceptance_met'])

    def test_regression_missing_total(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'total':0})['windows_acceptance_met'])

    def test_regression_inconsistent_counts(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'passed':200})['windows_acceptance_met'])

    def test_regression_float_counts_rejected(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'total':200.0})['windows_acceptance_met'])

    def test_regression_bool_counts_rejected(self):
        self.assertFalse(self.assess(regression={**OK_REGRESSION,'total':True})['windows_acceptance_met'])

    def test_physical_gui_not_marked_pass(self):
        self.assertEqual(self.assess()['physical_display_user_review'],'UNVERIFIED')

    def test_no_claim_actual_platform_inference(self):
        r=self.assess()
        self.assertEqual(r['official_platform_api_upload'],'UNVERIFIED')
        self.assertEqual(r['local_llm_inference'],'UNVERIFIED')
        self.assertFalse(r['publication_executed'])
        self.assertFalse(r['network_used'])

    def test_no_fake_mz_executable(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'fake.exe';f.write_bytes(b'MZ'+b'\0'*100)
            self.assertFalse(a.is_pe_file(f))

    def test_nonexistent_exe(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(a.is_pe_file(Path(td)/'none.exe'))

    def test_pe_header_structure_sanity_not_execution(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'sample.exe'
            content=bytearray(132);content[:2]=b'MZ';content[60:64]=(128).to_bytes(4,'little');content[128:]=b'PE\x00\x00'
            f.write_bytes(content)
            self.assertTrue(a.is_pe_file(f))
            # Sanity alone cannot count as actual Windows execution.
            self.assertFalse(self.assess(os_name='posix',pe_valid=a.is_pe_file(f))['windows_acceptance_met'])

    def test_file_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'report.json';p.write_text('KEEP')
            with self.assertRaises(ValueError):a.safe_write_report(p, self.assess())
            self.assertEqual(p.read_text(),'KEEP')

    def test_report_symlink_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'existing';target.write_text('KEEP')
            link=Path(td)/'ref.json'
            try:link.symlink_to(target)
            except OSError:self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError):a.safe_write_report(link,self.assess())
            self.assertEqual(target.read_text(),'KEEP')

    def test_missing_report_parent_not_created(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'absent'/'report.json'
            with self.assertRaises(ValueError):a.safe_write_report(p,self.assess())
            self.assertFalse(p.parent.exists())

    def test_report_suffix_restricted(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):a.safe_write_report(Path(td)/'report.txt',self.assess())

    def test_report_written_once(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'result.json';a.safe_write_report(p,self.assess(os_name='posix'))
            self.assertFalse(json.loads(p.read_text())['windows_acceptance_met'])
            with self.assertRaises(ValueError):a.safe_write_report(p,self.assess())

    def test_no_windows_execution_on_current_linux(self):
        if os.name == 'nt':self.skipTest('Linux-only test')
        with patch.object(a, 'execute_check', side_effect=AssertionError('executed')):
            code, report=a.run(preflight_only=False)
        self.assertEqual(code,2)
        self.assertFalse(report['windows_acceptance_met'])
        self.assertEqual(report['windows_exe_runtime'],'UNVERIFIED')

    def test_cli_explicit_preflight_reports_unverified_here(self):
        if os.name == 'nt':self.skipTest('non-Windows-specific')
        p=subprocess.run([sys.executable,str(SCRIPT),'--preflight-only'],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,2,p.stderr)
        self.assertEqual(json.loads(p.stdout)['windows_comprehensive_regression'],'UNVERIFIED')

    def test_cli_refuse_report_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'report.json';f.write_text('KEEP')
            p=subprocess.run([sys.executable,str(SCRIPT),'--preflight-only','--report',str(f)],capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,2)
            self.assertEqual(f.read_text(),'KEEP')

    def test_sanitized_environment_discards_token(self):
        with patch.dict(os.environ, {'ANF_AI_API_KEY':'SECRET_99','PYTHONHOME':'bogus'}):
            env=a.safe_environment()
        self.assertNotIn('ANF_AI_API_KEY',env)
        self.assertNotIn('PYTHONHOME',env)
        self.assertEqual(env['ANF_AI_PROVIDER'],'disabled')

    def test_exact_official_requirement(self):
        s=(ROOT/'docs'/'requirements.md').read_text('utf-8')
        self.assertIn('| ANF-REQ-071 |',s)
        self.assertIn(' | 99 | ',s)

    def test_manual_checklist_exists(self):
        s=(ROOT/'docs'/'stage99_windows_integrated_regression.md').read_text('utf-8')
        for word in ('ANF-REQ-071','Windows','UNVERIFIED','PyInstaller','96','99'):
            self.assertIn(word,s)

    def test_no_network_install_publish_in_script(self):
        s=SCRIPT.read_text('utf-8')
        for token in ('requests.post(', 'urllib.request','socket.connect(', 'pip install','git clone', 'upload_to_real_platform('):
            self.assertNotIn(token,s)

if __name__=='__main__':unittest.main()
