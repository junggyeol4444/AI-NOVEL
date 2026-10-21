"""Source-level regression for native asynchronous GUI; NOT a product acceptance."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUI = (ROOT / 'src/ai_novel_factory/desktop/authoring_workflow.py').read_text(encoding='utf-8')
WORKER = (ROOT / 'src/ai_novel_factory/desktop/draft_worker.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'src/ai_novel_factory/desktop/app.py').read_text(encoding='utf-8')


class AsyncNativeGuiSourceRegression(unittest.TestCase):
    def test_native_inference_only_in_background_worker(self):
        self.assertIn('class DraftWorker(QThread)', WORKER)
        self.assertIn('draft_scene(self._request, self._provider)', WORKER)
        self.assertNotIn('self.session.generate(', GUI)
        self.assertIn('worker.start()', GUI)

    def test_actual_windows_quality_failure_is_not_misreported_as_sqlite_failure(self):
        source = (ROOT / '.github/workflows/anf-real-windows-exe-korean-literary-gate.yml').read_text(encoding='utf-8')
        self.assertIn("$report.sqlite_readonly_reopened=$true", source)
        self.assertIn("$report.current_stage='validate_korean_5000_no_english_padding'\n", source)
        self.assertIn('native_non_korean_script', source)
        self.assertIn('native_no_hangul', source)

    def test_live_gui_does_not_close_during_inference(self):
        self.assertIn('authoring.is_generating()', MAIN)
        self.assertIn('accept_generation(', GUI)
        self.assertIn('한국어 형식 검사 미달', GUI)
        self.assertIn('한국어 형식 1차 검사 충족', GUI)
        self.assertIn('screen_korean_draft(', GUI)
        self.assertIn("setAccessibleName('한국어 형식 검사 미달')", GUI)


    def test_async_worker_keeps_safe_native_failure_categories(self):
        for reason in (
            'native_timeout', 'native_inference_failure', 'native_process_crash',
            'native_output_rejected', 'native_no_hangul',
            'native_non_korean_script', 'native_prompt_echo',
        ):
            with self.subTest(reason=reason):
                self.assertIn("'" + reason + "'", WORKER)
        self.assertIn("else 'LocalModelError'", WORKER)

    def test_windows_uia_finds_changed_model_failure_accessible_name(self):
        source = (ROOT / '.github/workflows/anf-real-windows-exe-korean-literary-gate.yml').read_text(encoding='utf-8')
        self.assertIn('function UiStatus', source)
        self.assertIn('[System.Windows.Automation.ControlType]::Text', source)
        self.assertIn('$liveStatus=UiStatus', source)
        self.assertIn('$statusView=UiStatus', source)



    def test_save_button_requires_real_pending_draft_after_async_worker(self):
        # Source contract only; real Windows GUI status remains a separate gate.
        self.assertIn("self.buttons['save_draft'].setEnabled(False)", GUI)
        self.assertIn("self.session.pending_draft is not None", GUI)
        self.assertNotIn("self.buttons['save_draft'].setEnabled(True)", GUI)
        self.assertIn('이전 미저장 초고는 그대로 유지됩니다.', GUI)

    def test_windows_foreground_retry_uses_real_gui_hwnd_and_still_fails_closed(self):
        # Source contract only; this is NOT a Windows desktop E2E pass.
        s = (ROOT / 'scripts/ci_windows11_desktop.ps1').read_text(encoding='utf-8')
        self.assertIn('AttachThreadInput', s)
        self.assertIn('GetCurrentThreadId', s)
        self.assertIn('$verifiedOwnerPid -eq $ownGuiPid', s)
        self.assertIn('$front = [ANFWin32]::GetForegroundWindow()', s)
        self.assertIn('if ($front -ne $hwnd)', s)
        self.assertIn('Desktop foreground is not our app', s)
        self.assertNotIn('Stop-Process -Name WWAHost', s)

    def test_windows_runner_oobe_is_diagnosed_and_never_auto_approved(self):
        script = (ROOT / 'scripts/ci_windows11_desktop.ps1').read_text(
            encoding='utf-8')
        self.assertIn('Choose privacy settings for your device', script)
        self.assertIn('HostSetupPrivacyOobe', script)
        self.assertIn('HOST_OOBE_PRIVACY_BLOCKED', script)
        self.assertIn('if ($front -ne $hwnd)', script)
        self.assertNotIn('Stop-Process -Name WWAHost', script)

    def test_portable_real_gui_reports_sanitized_native_failure_code(self):
        source = (ROOT / 'src/ai_novel_factory/desktop/ci_portable_gui.py').read_text(
            encoding='utf-8')
        self.assertIn("report['generation_failure_code']", source)
        self.assertIn('allowed_failure_codes', source)
        self.assertNotIn("report['failed_model_text']", source)
        self.assertIn("ui.status.accessibleName()", source)

if __name__ == '__main__':
    unittest.main()
