"""Stage 98 offline, no platform/installation/network claims."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'scripts'/'stage98_offline_setup.py'
spec = importlib.util.spec_from_file_location('stage98_local_setup', SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class LocalSetupTests(unittest.TestCase):
    def test_windows_required_for_build(self):
        self.assertFalse(setup.assess('Linux', (3, 12), dict(PySide6=True,PyInstaller=True))['windows_build_preflight_possible'])

    def test_python_312_required_for_build(self):
        self.assertFalse(setup.assess('Windows', (3, 13), dict(PySide6=True,PyInstaller=True))['windows_build_preflight_possible'])

    def test_desktop_dependency_required_for_build(self):
        self.assertFalse(setup.assess('Windows', (3, 12), dict(PyInstaller=True))['windows_build_preflight_possible'])

    def test_pyinstaller_dependency_required_for_build(self):
        self.assertFalse(setup.assess('Windows', (3, 12), dict(PySide6=True))['windows_build_preflight_possible'])

    def test_preflight_possible_is_not_build_pass(self):
        r=setup.assess('Windows',(3,12), dict(PySide6=True,PyInstaller=True,PIL=True))
        self.assertTrue(r['windows_build_preflight_possible'])
        self.assertFalse(r['stage97_windows_exe_acceptance_met'])
        self.assertFalse(r['installed_windows_exe_verified'])
        self.assertFalse(r['gui_runtime_verified'])

    def test_user_approval_assertion_cannot_unlock_upload(self):
        r=setup.assess('Windows',(3,12), dict(PySide6=True,PyInstaller=True),claimed_user_approval=True)
        self.assertFalse(r['user_approval_authenticated'])
        self.assertFalse(r['platform_publishing_executed'])

    def test_foreign_unknown_module_key_ignored(self):
        self.assertFalse(setup.assess('Windows',(3,12),{'requests':True})['windows_build_preflight_possible'])

    def test_optional_pillow_not_required_for_build(self):
        r=setup.assess('Windows',(3,12),{'PySide6':True,'PyInstaller':True,'PIL':False})
        self.assertTrue(r['windows_build_preflight_possible'])
        self.assertFalse(r['optional_graphics_module_available'])

    def test_no_remotes_every_platform(self):
        for p in ('Windows','Linux','Darwin'):
            r=setup.assess(p,(3,12),{'PySide6':True,'PyInstaller':True})
            self.assertEqual(r['external_service_connection'],'DISABLED')
            self.assertEqual(r['cloud_ai_connection'],'DISABLED')
            self.assertFalse(r['network_used'])
            self.assertFalse(r['installer_executed'])
            self.assertFalse(r['stage95_official_api_acceptance_met'])
            self.assertFalse(r['stage96_official_upload_compatibility_verified'])

    def test_default_config_offline(self):
        r=setup.check_config()
        self.assertTrue(r['valid'])
        self.assertTrue(r['api_loopback_only'])

    def test_loopback_ipv6(self):
        self.assertTrue(setup.check_config({'ANF_API_HOST':'::1'})['valid'])

    def test_invalid_cloud_provider(self):
        self.assertFalse(setup.check_config({'ANF_AI_PROVIDER':'openai'})['valid'])

    def test_invalid_remote_database(self):
        self.assertFalse(setup.check_config({'ANF_DATABASE_URL':'postgres://supersecret@remote'})['valid'])

    def test_invalid_redis(self):
        self.assertFalse(setup.check_config({'ANF_REDIS_URL':'redis://secret@remote'})['valid'])

    def test_invalid_public_api_host(self):
        self.assertFalse(setup.check_config({'ANF_API_HOST':'0.0.0.0'})['valid'])

    def test_private_key_not_echoed(self):
        sensitive='VERY_SECRET_PRIVATE_TOKEN_123'
        self.assertNotIn(sensitive,json.dumps(setup.check_config({'ANF_AI_API_KEY':sensitive})))

    def test_setting_valid_local_model(self):
        self.assertTrue(setup.check_config({'ANF_AI_PROVIDER':'local'})['valid'])

    def test_setting_wrong_port(self):
        self.assertFalse(setup.check_config({'ANF_API_PORT':'65536'})['valid'])

    def test_mock_without_key_rejected(self):
        self.assertFalse(setup.check_config({'ANF_AI_PROVIDER':'mock'})['valid'])

    def test_current_report_does_not_touch_user_pc(self):
        r=setup.current_report()
        self.assertFalse(r['user_pc_inspected'])
        self.assertFalse(r['installed_windows_exe_verified'])
        self.assertIn('default_configuration',r)

    def test_cli_stdout_valid_json(self):
        p=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['stage'],98)

    def test_cli_output_does_not_include_environment_secrets(self):
        import os
        secret='SECRET_DO_NOT_LEAK_A98'
        with patch.dict(os.environ,{'ANF_AI_API_KEY':secret,'ANF_DATABASE_URL':secret}):
            p=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0)
        self.assertNotIn(secret,p.stdout+p.stderr)

    def test_cli_report_writes_sanitized_json(self):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/'setup-report.json'
            p=subprocess.run([sys.executable,str(SCRIPT),'--report',str(dst)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertTrue(dst.exists())
            self.assertFalse(json.loads(dst.read_text())['installed_windows_exe_verified'])

    def test_cli_report_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/'report.json';dst.write_text('KEEP ME')
            p=subprocess.run([sys.executable,str(SCRIPT),'--report',str(dst)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,2)
            self.assertEqual(dst.read_text(),'KEEP ME')

    def test_cli_report_no_parent_create(self):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/'absent'/'report.json'
            p=subprocess.run([sys.executable,str(SCRIPT),'--report',str(dst)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,2)
            self.assertFalse(dst.parent.exists())

    def test_cli_report_reject_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'target';target.write_text('KEEP')
            link=Path(td)/'link'; link.symlink_to(target)
            p=subprocess.run([sys.executable,str(SCRIPT),'--report',str(link)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,2)
            self.assertEqual(target.read_text(),'KEEP')

    def test_no_network_in_source(self):
        content=SCRIPT.read_text()
        for dangerous in ('requests.get(', 'urllib.request', 'socket.connect(', 'subprocess.run(["pip"', 'pip install', 'git clone'):
            self.assertNotIn(dangerous,content)

    def test_offline_document_exists(self):
        text=(ROOT/'docs/stage98_installation_and_connection_guide.md').read_text('utf-8')
        for required in ('ANF-REQ-070','Python 3.12','PySide6','PyInstaller','Redis','pgvector','승인','미검증'):
            self.assertIn(required,text)

    def test_exact_requirement_not_invented(self):
        requirements=(ROOT/'docs/requirements.md').read_text('utf-8')
        self.assertIn('ANF-REQ-070',requirements)
        self.assertIn(' | 98 | ',requirements)

    def test_spec_and_dependencies_unchanged(self):
        self.assertTrue((ROOT/'packaging/windows/AI_Novel_Factory.spec').is_file())
        self.assertTrue((ROOT/'pyproject.toml').is_file())

if __name__ == '__main__':
    unittest.main()
