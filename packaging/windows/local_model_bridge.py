"""Offline console-mode JSON stdin/stdout bridge to bundled llama.cpp CPU runner.

Built separately from the GUI executable so Windows stdout/stderr pipes work.
Uses ONLY sibling portable files; no API key, network, shell or user document
reads. All public weights and runtime are obtained during CI packaging, never
downloaded when the user launches the app.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


MODEL_NAME = 'SmolLM2-135M-Instruct-Q4_K_M.gguf'
MODEL_PROTO = 'anf-local-scene-v1'


def root_path() -> Path:
    return Path(sys.executable if getattr(sys, 'frozen', False)
                else __file__).resolve().parent


def bundled_files() -> tuple[Path, Path]:
    folder = root_path()
    return folder / 'runtime' / 'llama-cli.exe', folder / 'models' / MODEL_NAME


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    llama, model = bundled_files()
    if args == ['--self-test']:
        if not llama.is_file() or not model.is_file():
            print('MODEL_BUNDLE_MISSING', file=sys.stderr)
            return 2
        try:
            proc = subprocess.run([str(llama), '--version'], cwd=llama.parent,
                                  capture_output=True, timeout=30, check=False)
            return 0 if proc.returncode == 0 else 2
        except (OSError, subprocess.TimeoutExpired):
            return 2
    if args:
        print('INVALID_ARGUMENTS', file=sys.stderr)
        return 2
    if not llama.is_file() or not model.is_file():
        print('MODEL_BUNDLE_MISSING', file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.buffer.read(200001)
        if len(raw) > 200000:
            raise ValueError('oversized')
        payload = json.loads(raw.decode('utf-8'))
        if payload.get('protocol') != MODEL_PROTO or payload.get('task') != 'scene_draft':
            raise ValueError('invalid protocol')
        req = payload.get('request')
        if type(req) is not dict:
            raise ValueError('invalid request')
        for key in ('novel_bible', 'scene_goal', 'scene_conflict',
                    'scene_location', 'characters'):
            if key not in req:
                raise ValueError('missing field')
        characters = req['characters']
        if (type(characters) is not list
                or not all(type(x) is str and len(x) < 200 for x in characters)):
            raise ValueError('invalid characters')
        def field(name, length):
            value = req[name]
            if type(value) is not str or not value.strip() or len(value) > length:
                raise ValueError('invalid field')
            return value
        canon = field('novel_bible', 30000)
        goal = field('scene_goal', 30000)
        conflict = field('scene_conflict', 30000)
        place = field('scene_location', 30000)
        prompt = (
            '<|im_start|>system\n'
            'You write original fiction from author-owned story rules. '
            'No copying reference novel passages. Do not publish. '
            'Generate the scene text only. Follow the language of the user input.'
            '<|im_end|>\n<|im_start|>user\n'
            'Novel Bible:\n' + canon[:12000] + '\n'
            'Scene goal:\n' + goal[:2000] + '\n'
            'Conflict:\n' + conflict[:1000] + '\n'
            'Location:\n' + place[:1000] + '\n'
            'Characters:\n' + ', '.join(characters[:20]) + '\n'
            'Write an original scene.\n'
            '<|im_end|>\n<|im_start|>assistant\n')
        command = [
            str(llama), '--model', str(model), '--prompt', prompt,
            '--no-conversation', '--no-display-prompt',
            '--no-show-timings', '--simple-io', '--ctx-size', '4096',
            '--predict', '384', '--threads', '4', '--temp', '0.75'
        ]
        env = {k: os.environ[k] for k in
               ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        env['PATH'] = str(llama.parent) + os.pathsep + env.get('PATH', '')
        proc = subprocess.run(command, cwd=llama.parent, env=env,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=110, check=False)
        if proc.returncode != 0:
            raise ValueError('model process failed')
        draft = proc.stdout.strip()
        # Some llama.cpp builds emit terminal control codes; fail instead of
        # quietly storing an incomplete or malformed model result.
        if (not draft or len(draft) > 100000 or '\x00' in draft
                or draft.startswith('error:')):
            raise ValueError('invalid local model output')
        response = {'protocol': MODEL_PROTO, 'draft': draft}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
        sys.stdout.flush()
        return 0
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        print('LOCAL_MODEL_GENERATION_FAILED', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
