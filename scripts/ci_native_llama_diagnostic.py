"""Real Windows llama-cli transport probe with a fixed, synthetic Korean prompt.

No app/user manuscript, prompt content or raw model output is ever emitted.
The actual EXE GUI literary-quality test remains the only acceptance gate.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess

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
