"""Real Windows llama-cli transport probe with a fixed, synthetic Korean prompt.

No app/user manuscript, prompt content or raw model output is ever emitted.
The actual EXE GUI literary-quality test remains the only acceptance gate.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import time

FLAGS = ('--single-turn', '--system-prompt', '--no-display-prompt',
         '--log-disable', '--no-show-timings', '--repeat-penalty')


def probe(cli: Path, model: Path) -> dict:
    report = dict(kind='diagnostic_not_literary_acceptance', native_exit=None,
                  flag_support=False, hangul_detected=False, banner_detected=False,
                  prompt_echo=False, output_chars=0, timed_out=False)
    try:
        cli, model = cli.resolve(strict=True), model.resolve(strict=True)
        if cli.name.lower() != 'llama-cli.exe' or model.suffix.lower() != '.gguf':
            report['reason'] = 'invalid_ci_fixture'
            return report
        h = subprocess.run([str(cli), '--help'], cwd=cli.parent,
                           capture_output=True, timeout=30, check=False)
        options = (h.stdout + h.stderr).decode('utf-8', 'replace')
        report['flag_support'] = all(flag in options for flag in FLAGS)
        report['help_exit'] = h.returncode
        if not report['flag_support']:
            report['reason'] = 'unsupported_native_flags'
            return report
        synthetic = '한국어 소설을 한 단락만 새로 써라. 가상의 도서관에서 사서가 빈 기록을 발견한다.'
        cmd = [str(cli), '--model', str(model), '--system-prompt', '한국어 원문만 쓰세요.',
               '--prompt', synthetic, '--predict', '48', '--ctx-size', '2048',
               '--threads', '1', '--threads-batch', '1', '--single-turn',
               '--no-display-prompt', '--log-disable', '--no-show-timings']
        p = subprocess.run(cmd, cwd=cli.parent, capture_output=True,
                           timeout=150, check=False)
        prose = p.stdout.decode('utf-8', 'replace')
        report['native_exit'] = p.returncode
        report['hangul_detected'] = any('가' <= c <= '힣' for c in prose)
        report['banner_detected'] = any(x in prose.lower() for x in
            ('loading model...', 'available commands:', 'exiting...', '[ prompt:'))
        report['prompt_echo'] = synthetic in prose
        report['output_chars'] = len(prose)

        # A Qwen-only alternative: disable the interactive chat shell and
        # supply exact GGUF ChatML framing directly. This should expose whether
        # the console banner/prompt echo is solely an interactive-mode artifact.
        # Nothing here changes product model settings or prints generated text.
        alternate = dict(supported=('--no-conversation' in options),
                         exit=None, hangul=False, banner=False, echo=False,
                         chars=0, timeout=False)
        if alternate['supported']:
            raw = (
                '<|im_start|>system\n한국어 원문 소설만 쓰세요.<|im_end|>\n'
                '<|im_start|>user\n' + synthetic +
                '<|im_end|>\n<|im_start|>assistant\n')
            command = [str(cli), '--model', str(model),
                       '--no-conversation', '--prompt', raw,
                       '--predict', '48', '--ctx-size', '2048',
                       '--threads', '1', '--threads-batch', '1',
                       '--no-display-prompt', '--log-disable',
                       '--no-show-timings']
            try:
                p2 = subprocess.run(command, cwd=cli.parent, capture_output=True,
                                    timeout=150, check=False)
                output = p2.stdout.decode('utf-8', 'replace')
                alternate['exit'] = p2.returncode
                alternate['hangul'] = any('가' <= c <= '힣' for c in output)
                alternate['banner'] = any(x in output.lower() for x in
                    ('loading model...', 'available commands:',
                     'exiting...', '[ prompt:'))
                alternate['echo'] = synthetic in output
                alternate['chars'] = len(output)
            except subprocess.TimeoutExpired:
                alternate['timeout'] = True
            except (OSError, ValueError):
                alternate['error'] = 'native_alternate_probe_error'
        report['no_conversation_raw_completion'] = alternate
        # Exercise the same non-interactive Qwen transport used by the GUI
        # bridge. This reports only structural facts, never synthetic prose.
        completion_exe = cli.with_name('llama-completion.exe')
        completion = dict(supported=completion_exe.is_file(), exit=None,
                          hangul=False, banner=False, echo=False, chars=0,
                          timeout=False)
        if completion['supported']:
            try:
                help_process = subprocess.run([str(completion_exe), '--help'],
                                              cwd=cli.parent, capture_output=True,
                                              timeout=30, check=False)
                help_text = (help_process.stdout + help_process.stderr).decode(
                    'utf-8', 'replace')
                completion['help_exit'] = help_process.returncode
                completion['flag_support'] = {flag: flag in help_text for flag in
                    ('--prompt', '--predict', '--ctx-size', '--threads',
                     '--threads-batch', '--repeat-penalty', '--repeat-last-n',
                     '--no-display-prompt', '--log-verbosity', '--no-show-timings')}
            except (OSError, subprocess.TimeoutExpired):
                completion['help_error'] = 'noninteractive_help_unavailable'
        if completion['supported']:
            command = [str(completion_exe), '--model', str(model),
                       '--system-prompt', '한국어 원문 소설만 쓰세요.',
                       '--prompt', synthetic, '--predict', '48',
                       '--ctx-size', '2048', '--threads', '1',
                       '--threads-batch', '1', '--single-turn',
                       '--no-display-prompt', '--log-verbosity', '0']
            try:
                completion_started = time.monotonic()
                cp = subprocess.run(command, cwd=cli.parent, capture_output=True,
                                    timeout=150, check=False)
                output = cp.stdout.decode('utf-8', 'replace')
                completion['elapsed_s'] = round(time.monotonic() - completion_started, 2)
                completion['exit'] = cp.returncode
                completion['hangul'] = any('가' <= c <= '힣' for c in output)
                completion['banner'] = any(x in output.lower() for x in
                    ('loading model...', 'available commands:',
                     'exiting...', '[ prompt:'))
                completion['echo'] = synthetic in output
                completion['chars'] = len(output)
                # Never emit stderr itself: some native tools echo the prompt.
                # Diagnose only fixed, non-sensitive categories.
                native_error = cp.stderr.decode('utf-8', 'replace').lower()
                completion['stderr_bytes'] = len(cp.stderr)
                completion['stderr_categories'] = [pattern for pattern in (
                    'unknown argument', 'invalid argument', 'unknown option',
                    'unrecognized option', 'failed to load model',
                    'error loading model', 'could not load', 'failed to open',
                    'context size', 'out of memory', 'error:'
                ) if pattern in native_error]
                if cp.returncode != 0:
                    minimal = [str(completion_exe), '--model', str(model),
                               '--system-prompt', '한국어 원문 소설만 쓰세요.',
                               '--prompt', synthetic, '--predict', '8',
                               '--threads', '1', '--single-turn',
                               '--no-display-prompt', '--log-verbosity', '0']
                    try:
                        fallback = subprocess.run(minimal, cwd=cli.parent,
                                                  capture_output=True, timeout=90,
                                                  check=False)
                        completion['minimal_exit'] = fallback.returncode
                        completion['minimal_stdout_chars'] = len(
                            fallback.stdout.decode('utf-8', 'replace'))
                        error = fallback.stderr.decode('utf-8', 'replace').lower()
                        completion['minimal_error_categories'] = [
                            word for word in ('unknown argument', 'invalid argument',
                                'unknown option', 'unrecognized option',
                                'failed to load model', 'error loading model',
                                'failed to open', 'error:') if word in error]
                    except subprocess.TimeoutExpired:
                        completion['minimal_timeout'] = True
                    except (OSError, ValueError):
                        completion['minimal_error'] = 'native_minimal_probe_error'
            except subprocess.TimeoutExpired:
                completion['timeout'] = True
            except (OSError, ValueError):
                completion['error'] = 'native_completion_probe_error'
        # Compare the existing single-thread native runtime to a four-thread
        # invocation before changing the product. Report only timings, exit
        # status and output shape, never generated text or author material.
        parallel = dict(kind='ci_only_speed_diagnostic', threads=4,
                        exit=None, elapsed_s=None, chars=0, hangul=False,
                        timeout=False, banner=False)
        if completion['supported'] and completion.get('exit') == 0:
            four_thread_cmd = [str(completion_exe), '--model', str(model),
                               '--system-prompt', '한국어 원문 소설만 쓰세요.',
                               '--prompt', synthetic, '--predict', '48',
                               '--ctx-size', '2048', '--threads', '4',
                               '--threads-batch', '4', '--single-turn',
                               '--no-display-prompt', '--log-verbosity', '0']
            started = time.monotonic()
            try:
                p4 = subprocess.run(four_thread_cmd, cwd=cli.parent,
                                    capture_output=True, timeout=150,
                                    check=False)
                output4 = p4.stdout.decode('utf-8', 'replace')
                parallel['exit'] = p4.returncode
                parallel['chars'] = len(output4)
                parallel['hangul'] = any('가' <= c <= '힣' for c in output4)
                parallel['banner'] = any(x in output4.lower() for x in
                    ('loading model...', 'available commands:',
                     'exiting...', '[ prompt:'))
            except subprocess.TimeoutExpired:
                parallel['timeout'] = True
            except (OSError, ValueError):
                parallel['error'] = 'four_thread_native_probe_error'
            finally:
                parallel['elapsed_s'] = round(time.monotonic() - started, 2)
        report['four_thread_noninteractive_diagnostic'] = parallel
        report['noninteractive_completion'] = completion
        report['reason'] = 'native_short_probe_completed'
    except subprocess.TimeoutExpired:
        report['timed_out'] = True
        report['reason'] = 'native_short_probe_timeout'
    except (OSError, ValueError):
        report['reason'] = 'native_probe_error'
    return report


if __name__ == '__main__':
    result = probe(Path(os.environ.get('ANF_QA_CLI', '')),
                   Path(os.environ.get('ANF_QA_GGUF', '')))
    print('ANF_NATIVE_CLI_PROBE=' + json.dumps(result, sort_keys=True))
