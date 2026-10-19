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
import time
import re


MODEL_NAME = 'SmolLM2-135M-Instruct-Q4_K_M.gguf'
MODEL_PROTO = 'anf-local-scene-v1'


def root_path() -> Path:
    return Path(sys.executable if getattr(sys, 'frozen', False)
                else __file__).resolve().parent


def bundled_files() -> tuple[Path, Path]:
    folder = root_path()
    return folder / 'runtime' / 'llama-cli.exe', folder / 'models' / MODEL_NAME


def validate_clean_manuscript(raw: str) -> str:
    """Fail closed on native llama-cli banners, echoed author settings or timings.

    Never mistake a command-line program's stdout for the model's novel.
    This is a transport-integrity check, not literary quality approval.
    """
    if not isinstance(raw, str):
        raise ValueError('invalid native output type')
    text = raw.strip()
    # llama.cpp b11624 tools/completion/completion.cpp prints this exact
    # transport terminator after EOG. Remove ONLY the fixed trailing marker;
    # do not rewrite model-authored prose or strip lookalikes in the middle.
    terminator = ' [end of text]'
    if text.endswith(terminator):
        text = text[:-len(terminator)].strip()
    if not text or len(text) > 100_000 or '\x00' in text or '\x1b' in text:
        raise ValueError('invalid native output')
    lower = text.lower()
    forbidden = (
        'loading model...', 'available commands:', 'using custom system prompt',
        'build      :', 'model      :', 'ftype      :', 'modalities :',
        'exiting...', '[ prompt:', 'generation:', 't/s ]', '[end of text]',
        '작품의 최우선 설정 (novel bible):',
        '회차/장면의 작가 소유 플롯:',
    )
    if any(fragment in lower for fragment in forbidden):
        raise ValueError('native console output mixed with draft')
    if not any('가' <= ch <= '힣' for ch in text):
        raise ValueError('native output lacks Korean novel prose')
    return text



def build_native_command(llama: Path, model: Path, system_prompt: str,
                         prompt: str, prediction_budget: str) -> list[str]:
    """Use the bundled completion executable for the existing Qwen QA model.

    The separate completion executable avoids llama-cli's chat shell. It
    applies the model's own chat template to ordinary --system-prompt and
    --prompt arguments; never embed raw ChatML into author-controlled text.
    Its argument set excludes CLI-only --no-show-timings. Only verbosity 0
    keeps response tokens while hiding informational messages.
    """
    qwen = model.name.lower().startswith('qwen2.5-') and model.suffix.lower() == '.gguf'
    # The Windows 2022/11 native 48-token diagnostic verified four Qwen CPU
    # threads are faster than one. Preserve the bundled 135M smoke path.
    threads = '4' if qwen else '1'
    common = [
        '--model', str(model), '--predict', prediction_budget,
        '--ctx-size', '4096', '--threads', threads, '--threads-batch', threads,
        '--repeat-penalty', '1.16', '--repeat-last-n', '256',
        '--temp', '0.8', '--top-p', '0.92', '--no-display-prompt',
    ]
    if qwen or model.name == MODEL_NAME:
        # The pinned bundle includes llama-completion.exe. Avoid llama-cli's
        # interactive shell, which emitted banners/prompt echoes into stdout.
        completion = llama.with_name('llama-completion.exe')
        if not completion.is_file():
            raise ValueError('non-interactive completion runtime missing')
        if qwen and any(token in part for part in (system_prompt, prompt) for token in
                        ('<|im_start|>', '<|im_end|>', '<|im_sep|>')):
            raise ValueError('unsafe chat template delimiter')
        return [str(completion), *common, '--log-verbosity', '0',
                '--system-prompt', system_prompt, '--prompt', prompt,
                '--single-turn']
    # Any other explicitly selected local model retains the original CLI
    # pathway, with fail-closed native output validation.
    return [str(llama), *common, '--log-disable', '--no-show-timings',
            '--system-prompt', system_prompt, '--prompt', prompt,
            '--single-turn']


def continue_korean_scene(draft: str, *, original_prompt: str, target_chars: int,
                          invoke, deadline: float, clock=time.monotonic) -> str:
    """Continue real native model prose if a requested scene ends prematurely.

    No synthetic padding, translation, invented facts, prompt leaks or approvals.
    Each returned continuation is actual model output and is checked separately.
    The caller supplies the existing trusted native runner and a bounded deadline.
    """
    if not 1000 <= target_chars <= 10000:
        return draft
    minimum = (target_chars * 9 + 9) // 10
    def nonspace_count(value):
        return sum(not ch.isspace() for ch in value)
    for _ in range(8):
        if nonspace_count(draft) >= minimum or clock() >= deadline:
            break
        previous = draft[-650:]
        continuation_prompt = (
            original_prompt[:2400] + '\n'
            '이미 집필된 소설의 마지막 부분(반복하여 다시 쓰지 마세요):\n'
            + previous + '\n'
            '이어서 새로운 사건·인물 행동·대사를 한국어 소설 본문으로만 '
            '직접 집필하세요. 지금까지 쓴 문장은 다시 쓰지 마세요. '
            '머리말·해설·작성 예정 보고·요약을 쓰지 마세요.'
        )
        remaining = deadline - clock()
        if remaining <= 5:
            break
        try:
            next_raw = invoke(continuation_prompt, remaining)
        except subprocess.TimeoutExpired:
            # Keep only native prose validated before the timeout; never
            # mark its length or literary quality as approved.
            break
        new = validate_clean_manuscript(next_raw).strip()
        # Do not silently fill short drafts by repeating previous generations.
        if not new or new in draft or len(new) < 80:
            break
        overlap = 0
        for n in range(min(180, len(new), len(draft)), 24, -1):
            if draft.endswith(new[:n]):
                overlap = n
                break
        addition = new[overlap:].strip()
        if len(addition) < 80 or addition in draft:
            break
        draft += '\n\n' + addition
        if len(draft) > 100_000:
            raise ValueError('invalid native output')
    return draft


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
        style_bible = req.get('style_bible', '')
        if type(style_bible) is not str or len(style_bible) > 30000:
            raise ValueError('invalid style_bible')
        # llama-cli --single-turn applies model GGUF chat templates.
        # Raw, nested ChatML tokens inside user prompts harm local model output.
        system_prompt = (
            '당신은 처음부터 자연스러운 한국어로 독창적인 소설을 집필하는 원어민 작가입니다. '
            '작가 소유 Novel Bible 설정과 이번 회차·장면 플롯을 최우선으로 지키세요. '
            '참고작 문장과 고유 설정을 복제하지 마세요. '
            '영어로 먼저 작성하여 번역하거나 영어 문장을 섞지 마세요. '
            '같은 문장을 반복해 분량을 채우지 마세요. '
            '행동과 감정과 대사, 인물 선택의 인과 관계를 구체적으로 보여주세요. '
            '소설 본문 외의 목차·설명·지시문 반복·메타 해설·출판은 하지 마세요. '
            '장면 계획을 설명하거나 작성할 것을 약속하지 마세요. '
            '글자 수가 충분하다고 주장하거나 집필을 완료했다는 보고문을 쓰지 마세요. '
            '인물의 행동·대사·감각과 그 결과를 실제 이야기로 바로 서술하세요.')
        prompt = (
            '작품의 최우선 설정 (Novel Bible):\n' + canon[:12000] + '\n'
            '회차/장면의 작가 소유 플롯:\n' + style_bible[:5000] + '\n'
            '이번 장면 목표:\n' + goal[:2000] + '\n'
            '충돌과 장애물:\n' + conflict[:1000] + '\n'
            '배경 장소:\n' + place[:1000] + '\n'
            '등장인물:\n' + ', '.join(characters[:20]) + '\n'
            '첫 문장부터 한국어 소설 본문만 작성하세요. '
            '영어와 중복 구절을 피하고 사건이 앞으로 진행되도록 집필하세요.')
        # Keep the previously verified non-interactive Windows runtime path.
        # A longer Qwen scene budget is still subject to the native timeout.
        # Verified against b11624 Windows CPU runtime: the minimal
        # --single-turn --no-display-prompt invocation exits successfully.
        # Earlier Windows CI found that --simple-io plus conversation flags
        # returned native exit 1. Use single-turn without simple-io while
        # keeping fail-closed console-output rejection.
        # Keep the small bundled 135M smoke route responsive. Larger, explicitly
        # selected multilingual GGUF weights need a separate bounded CPU budget.
        is_bundled_qa_model = model.name == MODEL_NAME
        prediction_budget = '384' if is_bundled_qa_model else '3072'
        # Windows native probe: Qwen 48 tokens took 3.88s on x64 and
        # >30s on ARM. A 3072-token single call can exhaust the entire
        # 400-second budget before continuation or a GUI status update.
        # Keep the requested 5000-character quality gate unchanged.
        if model.name.lower().startswith('qwen2.5-'):
            prediction_budget = '512'
        native_timeout = 110 if is_bundled_qa_model else 400
        command = build_native_command(
            llama, model, system_prompt, prompt, prediction_budget)
        env = {k: os.environ[k] for k in
               ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        env['PATH'] = str(llama.parent) + os.pathsep + env.get('PATH', '')
        deadline = time.monotonic() + native_timeout
        def invoke_native(scene_prompt: str, timeout: float) -> str:
            live_command = build_native_command(
                llama, model, system_prompt, scene_prompt, prediction_budget)
            proc = subprocess.run(live_command, cwd=llama.parent, env=env,
                                  capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=max(1, timeout),
                                  check=False)
            if proc.returncode != 0:
                # Numeric exit only; never reveal user text or native stderr.
                print('LLAMA_NATIVE_EXIT=' + str(proc.returncode), file=sys.stderr)
                raise ValueError('model process failed')
            return proc.stdout
        stage = 'native_inference'
        raw_draft = invoke_native(prompt, deadline - time.monotonic())
        stage = 'text_validation'
        draft = validate_clean_manuscript(raw_draft)
        # A Korean-capable user-selected Qwen model sometimes returns an early
        # EOS after ~775 characters even when asked for ~5000. Continue only
        # actual model prose under the existing single 400-second deadline.
        # Never pretend that a short/incoherent scene meets the quality gate.
        target_match = re.search(r'(?<!\d)(\d{4,5})\s*자', goal)
        if (not is_bundled_qa_model and model.name.lower().startswith('qwen2.5-')
                and target_match is not None):
            target = int(target_match.group(1))
            draft = continue_korean_scene(
                draft, original_prompt=prompt, target_chars=target,
                invoke=invoke_native, deadline=deadline)
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
        # Validation errors below have only fixed, source-authored messages.
        # Expose a finite category, not raw native text or author content.
        reason = ''
        if stage == 'text_validation' and type(exc) is ValueError:
            category = {
                'invalid native output type': 'INVALID_TYPE',
                'invalid native output': 'EMPTY_CONTROL_OR_LENGTH',
                'native console output mixed with draft': 'CONSOLE_OR_PROMPT_ECHO',
                'native output lacks Korean novel prose': 'NO_HANGUL',
            }.get(str(exc), 'OTHER')
            reason = ';REASON=' + category
        print('LOCAL_MODEL_GENERATION_FAILED;STAGE=' + stage
              + ';TYPE=' + type(exc).__name__ + reason, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
