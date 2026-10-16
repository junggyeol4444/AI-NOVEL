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
    # User may explicitly choose a different local GGUF without replacing or
    # rewriting the public QA model. No shell or network paths are permitted.
    if len(args) == 2 and args[0] == '--gguf':
        chosen = args[1]
        try:
            selected = Path(chosen)
            if (not selected.is_absolute() or chosen.startswith('\\\\')
                    or selected.is_symlink() or selected.suffix.lower() != '.gguf'
                    or not selected.is_file()
                    or not 8_000_000 <= selected.stat().st_size <= 32_000_000_000):
                raise ValueError('model path rejected')
            model = selected.resolve(strict=True)
        except (OSError, ValueError):
            print('INVALID_LOCAL_GGUF_SELECTION', file=sys.stderr)
            return 2
    elif args:
        print('INVALID_ARGUMENTS', file=sys.stderr)
        return 2
    if not llama.is_file() or not model.is_file():
        print('MODEL_BUNDLE_MISSING', file=sys.stderr)
        return 2
    stage = 'reading_request'
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
            '당신은 한국어로 처음부터 창작하는 장편소설 작가입니다. '
            'Novel Bible에 기재된 작가 소유 설정을 최우선으로 지키세요. '
            '영어로 먼저 작성하여 번역하거나 영어 해설을 섞지 마세요. '
            '실제 소설 본문만 자연스러운 현대 한국어로 작성하세요. '
            '같은 문장을 반복해 분량을 채우거나 참고작 문장·고유 설정을 복제하지 마세요. '
            '인물의 행동·감정·대사·사건의 인과를 구체적으로 이어 쓰세요. '
            '게시·출판하지 마세요.'
            '<|im_end|>\n<|im_start|>user\n'
            '작품의 최우선 설정 (Novel Bible):\n' + canon[:12000] + '\n'
            '이번 장면 목표:\n' + goal[:2000] + '\n'
            '충돌과 장애물:\n' + conflict[:1000] + '\n'
            '배경 장소:\n' + place[:1000] + '\n'
            '등장인물:\n' + ', '.join(characters[:20]) + '\n'
            '위 설정을 유지하면서 한국어 원문 소설의 다음 장면을 직접 집필하세요. '
            '목차, 설명, 번역문, 영어 문장, 메타 코멘트는 쓰지 마세요.\n'
            '<|im_end|>\n<|im_start|>assistant\n')
        # Restrict native Windows CPU runner to single-thread inference as a
        # conservative diagnostic for intermittent native heap corruption.
        # This is a hypothesis until repeated compiled-GGUF CI verifies it.
        # Verified against b11624 Windows CPU runtime: the minimal
        # --single-turn --no-display-prompt invocation exits successfully.
        # The previous combination with --no-conversation / --simple-io
        # returned native exit 1 although loading the GGUF succeeds.
        # Keep the small bundled 135M smoke route responsive. Larger, explicitly
        # selected multilingual GGUF weights need a separate bounded CPU budget.
        is_bundled_qa_model = model.name == MODEL_NAME
        prediction_budget = '384' if is_bundled_qa_model else '1536'
        native_timeout = 110 if is_bundled_qa_model else 400
        command = [
            str(llama), '--model', str(model), '--prompt', prompt,
            '--predict', prediction_budget, '--ctx-size', '4096',
            '--threads', '1', '--threads-batch', '1',
            '--single-turn', '--no-display-prompt'
        ]
        env = {k: os.environ[k] for k in
               ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        env['PATH'] = str(llama.parent) + os.pathsep + env.get('PATH', '')
        stage = 'native_inference'
        proc = subprocess.run(command, cwd=llama.parent, env=env,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=native_timeout, check=False)
        if proc.returncode != 0:
            # Only the numeric native process exit status is emitted. stderr
            # can include user inputs or command-line prompts, so discard it.
            print('LLAMA_NATIVE_EXIT=' + str(proc.returncode), file=sys.stderr)
            raise ValueError('model process failed')
        stage = 'text_validation'
        draft = proc.stdout.strip()
        # Some llama.cpp builds emit terminal control codes; fail instead of
        # quietly storing an incomplete or malformed model result.
        if (not draft or len(draft) > 100000 or '\x00' in draft
                or draft.startswith('error:')):
            raise ValueError('invalid local model output')
        response = {'protocol': MODEL_PROTO, 'draft': draft}
        stage = 'json_output'
        # Windows frozen console executables may use a legacy code page even
        # though the local model returns UTF-8 Korean text. IPC is UTF-8 bytes.
        sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + '\n').encode('utf-8'))
        sys.stdout.buffer.flush()
        return 0
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        # Do not print the exception, stderr, prompts, filenames, or output.
        print('LOCAL_MODEL_GENERATION_FAILED;STAGE=' + stage
              + ';TYPE=' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
