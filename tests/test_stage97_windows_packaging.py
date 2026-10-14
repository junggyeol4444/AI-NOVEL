"""Stage 97 source-contract tests: do not claim an actual Windows build."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
spec = importlib.util.spec_from_file_location('stage97_builder', SCRIPTS / 'build_windows_exe.py')
import sys as _sys
builder = importlib.util.module_from_spec(spec)
_sys.modules[spec.name] = builder
spec.loader.exec_module(builder)


class Stage97BuildTests(unittest.TestCase):
    def test_linux_not_permitted(self):
        self.assertIn('not_windows', builder.evaluate_preflight('posix',(3,12), builder.REQUIRED_MODULES).blockers)

    def test_wrong_python_not_permitted(self):
        self.assertIn('python_not_3_12', builder.evaluate_preflight('nt',(3,13),builder.REQUIRED_MODULES).blockers)

    def test_pyinstaller_missing_blocks(self):
        state = builder.evaluate_preflight('nt',(3,12),frozenset({'PySide6'}))
        self.assertIn('missing_pyinstaller',state.blockers)
        self.assertFalse(state.permitted)

    def test_pyside_missing_blocks(self):
        state = builder.evaluate_preflight('nt',(3,12),frozenset({'PyInstaller'}))
        self.assertIn('missing_pyside6',state.blockers)
        self.assertFalse(state.permitted)

    def test_both_missing_sorted(self):
        state = builder.evaluate_preflight('nt',(3,12),frozenset())
        self.assertEqual(state.blockers,('missing_pyinstaller','missing_pyside6'))

    def test_all_required_contract_permitted(self):
        state = builder.evaluate_preflight('nt',(3,12),builder.REQUIRED_MODULES)
        self.assertTrue(state.permitted)
        self.assertEqual(state.blockers,())

    def test_report_never_claims_build_for_preflight(self):
        state = builder.evaluate_preflight('posix',(3,13),frozenset())
        r=builder.make_report(state)
        self.assertFalse(r['windows_exe_built'])
        self.assertFalse(r['windows_runtime_verified'])
        self.assertFalse(r['network_required'])
        self.assertFalse(r['publish_executed'])
        self.assertIsNone(r['exe_sha256'])

    def test_built_without_all_smoke_checks_not_verified(self):
        st=builder.evaluate_preflight('nt',(3,12),builder.REQUIRED_MODULES)
        self.assertFalse(builder.make_report(st,built=True, checks={'--check':True,'--gui-smoke':False})['windows_runtime_verified'])

    def test_built_with_all_smoke_checks_contract(self):
        st=builder.evaluate_preflight('nt',(3,12),builder.REQUIRED_MODULES)
        self.assertTrue(builder.make_report(st,built=True,checks={'--check':True,'--gui-smoke':True})['windows_runtime_verified'])

    def test_empty_pe_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(builder.is_pe_executable(Path(td)/'missing.exe'))

    def test_random_pe_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake.exe';p.write_bytes(b'MZ'+b'0'*100)
            self.assertFalse(builder.is_pe_executable(p))

    def test_pe_header_structure_only(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'header.exe'
            data=bytearray(140);data[:2]=b'MZ';data[60:64]=(100).to_bytes(4,'little');data[100:104]=b'PE\0\0';p.write_bytes(data)
            self.assertTrue(builder.is_pe_executable(p))

    def test_pe_bad_offset_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake.exe';data=bytearray(140);data[:2]=b'MZ';data[60:64]=(1).to_bytes(4,'little');p.write_bytes(data)
            self.assertFalse(builder.is_pe_executable(p))

    def test_local_launcher_check_works_without_pyside(self):
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
        result=subprocess.run([sys.executable,str(ROOT/'packaging/windows/launcher.py'),'--check'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('UI section contract OK: 12 sections',result.stdout)

    def test_launcher_no_implicit_network_import(self):
        t=(ROOT/'packaging/windows/launcher.py').read_text(encoding='utf8')
        self.assertNotIn('requests.',t)
        self.assertNotIn('urllib.',t)
        self.assertNotIn('upload_',t)

    def test_spec_is_single_file_gui(self):
        s=(ROOT/'packaging/windows/AI_Novel_Factory.spec').read_text(encoding='utf8')
        self.assertIn('console=False',s)
        self.assertIn('Analysis(',s)
        self.assertIn('ai_novel_factory.desktop.app',s)
        self.assertIn("name='AI_Novel_Factory'",s)
        self.assertNotIn('COLLECT(',s)

    def test_spec_includes_no_foreign_binaries(self):
        s=(ROOT/'packaging/windows/AI_Novel_Factory.spec').read_text(encoding='utf8')
        self.assertIn('datas=[]',s)
        self.assertIn('binaries=[]',s)

    def test_installer_not_invoked_in_source(self):
        b=(ROOT/'scripts/build_windows_exe.py').read_text(encoding='utf8')
        self.assertNotIn('pip install',b)
        self.assertNotIn('git clone',b)
        self.assertNotIn('shell=True',b)

    def test_builder_preflight_only_no_build(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'preflight.json'
            cmd=[sys.executable,str(SCRIPTS/'build_windows_exe.py'),'--preflight-only','--report',str(report)]
            completed=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=12)
            # An actual Windows build runner has a passing preflight.
            expected = 0 if builder.current_preflight().permitted else 2
            self.assertEqual(completed.returncode,expected,completed.stderr)
            data=json.loads(report.read_text(encoding='utf8'))
            self.assertFalse(data['windows_exe_built'])
            self.assertFalse(data['windows_runtime_verified'])

    def test_preflight_no_network_and_no_publish(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'evidence.json'
            with patch.object(builder,'current_preflight',return_value=builder.BuildPreflight(('not_windows',),False)):
                with patch.object(builder.subprocess,'run',side_effect=AssertionError('subprocess should not be called')):
                    status, report=builder.build(report_path=p)
            self.assertEqual(status,2)
            self.assertFalse(report['publish_executed'])
            self.assertEqual(json.loads(p.read_text(encoding='utf8')),report)

    def test_env_excludes_project_secrets(self):
        with patch.dict(os.environ,{'ANF_AI_API_KEY':'SECRET_UNIT_VALUE','PYTHONPATH':'PRIVATE_PATH'}):
            env=builder._sanitized_environment()
        self.assertNotIn('SECRET_UNIT_VALUE',repr(env))
        self.assertNotIn('PRIVATE_PATH',repr(env))
        self.assertEqual(env['ANF_AI_PROVIDER'],'disabled')

    def test_known_source_spec_allowed_by_release_guard(self):
        from zipfile import ZipFile
        sp=importlib.util.spec_from_file_location('stage97_verifier',SCRIPTS/'verify_release_bundle.py')
        guard=importlib.util.module_from_spec(sp);sp.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'zip.zip'
            with ZipFile(p,'w') as z:
                for n in sorted(guard.REQUIRED):z.writestr(n,b'x')
                z.writestr('packaging/windows/AI_Novel_Factory.spec',b'file')
            self.assertFalse(guard.verify_archive(p))

    def test_arbitrary_spec_rejected_by_release_guard(self):
        sp=importlib.util.spec_from_file_location('stage97_verifier2',SCRIPTS/'verify_release_bundle.py')
        guard=importlib.util.module_from_spec(sp);sp.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'zip.zip'
            with zipfile.ZipFile(p,'w') as z:
                for n in sorted(guard.REQUIRED):z.writestr(n,b'x')
                z.writestr('packaging/windows/unauthorized.spec',b'file')
            self.assertIn('private_or_build_artifact',guard.verify_archive(p))

    def test_ignored_build_artifacts(self):
        ignore=(ROOT/'.gitignore').read_text(encoding='utf8')
        self.assertIn('build/',ignore)
        self.assertIn('dist/',ignore)
        self.assertIn('!packaging/windows/AI_Novel_Factory.spec',ignore)

    def test_correct_build_dependency(self):
        import tomllib
        data=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf8'))
        self.assertTrue(any('pyinstaller' in spec.lower() for spec in data['project']['optional-dependencies']['build']))


if __name__=='__main__':
    unittest.main()
