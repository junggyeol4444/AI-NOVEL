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
        # The observed Windows Qwen GUI manuscript reproduced these
        # bridge-authored continuation instructions verbatim. Never store
        # instruction echo as author-written prose.
        '이미 집필된 소설의 마지막 부분(반복하여 다시 쓰지 마세요):',
        '이어서 새로운 사건·인물 행동·대사를 한국어 소설 본문으로만 직접 집필하세요.',
        '지금까지 쓴 문장은 다시 쓰지 마세요.',
        '머리말·해설·작성 예정 보고·요약을 쓰지 마세요.',
        # Exact labels exposed by compiled Windows Qwen GUI prose evidence.
        # This rejects leaked scaffolding; it does not certify literature.
        '마크다운 제목:', '역할별 대사 목록:',
        # These lines appeared inside the actual Windows2022 Qwen draft,
        # including copies of the formerly supplied continuation command.
        '지금까지 이어진 이야기의 마지막 문단:',
        '이어서 등장인물이 선택하고 행동하는 다음 사건을 한국어 소설 문단으로 서술하세요.',
        '장소와 인물의 대화를 자연스럽게 연결하고, 사건으로 생긴 변화를 보여주세요.',
        '이어서 등장인물이 선택하고 행동하는 다음 사건으로 장면이 이어집니다.',
    )
    if any(fragment in lower for fragment in forbidden):
        raise ValueError('native console output mixed with draft')
    # The real Windows 11 ARM Qwen output included an instruction-like
    # "next scene ... assume" sentence, not a fictional character's action.
    # Fail closed rather than persisting this observed meta narration.
    if re.search(r'다음 장면은.{0,120}가정하겠습니다\s*:', text):
        raise ValueError('native console output mixed with draft')
    if not any('가' <= ch <= '힣' for ch in text):
        raise ValueError('native output lacks Korean novel prose')
    # Actual Windows 2022 output leaked CJK; Windows 11 ARM output also
    # contained Cyrillic letters and a U+FFFD decoding replacement.
    # Reject those observed corruptions, never rewrite model-authored prose.
    if re.search(r'[\u3400-\u9fff\u3040-\u30ff\u0400-\u052f\ufffd]', text):
        raise ValueError('native non-Korean script in draft')
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


def repeats_existing_passage(addition: str, manuscript: str) -> bool:
    """Reject a long copied prefix even if later words or digits differ.

    Only compares the model's actual content; no synthetic passage is added.
    This is a conservative cross-generation repetition guard, not a literary
    acceptance test, and leaves the author-owned manuscript unchanged.
    """
    current = re.sub(r'[^가-힣A-Za-z0-9]', '', addition).casefold()
    earlier = re.sub(r'[^가-힣A-Za-z0-9]', '', manuscript).casefold()
    return len(current) >= 90 and current[:90] in earlier


def retry_bundled_korean_text(prompt: str, *, first_error: ValueError,
                              invoke, remaining: float) -> str:
    """One bounded real GGUF retry; never fabricate or translate a draft.

    The tiny bundled 135M model sometimes exits or produces only non-Korean
    text. A single shorter native inference is allowed when time remains.
    Failure still propagates to the original GUI with no saved draft.
    """
    if (type(first_error) is not ValueError
            or str(first_error) not in (
                'native output lacks Korean novel prose',
                'native non-Korean script in draft', 'model process failed')
            or remaining < 20):
        raise first_error
    retry_prompt = (
        prompt + '\n'
        '인물은 주변에 있는 사물을 보고 한국어로 말한다. '
        '그 말을 들은 다른 인물이 실제로 움직인다.')
    return invoke(retry_prompt, remaining, '160')


def retry_qwen_korean_text(prompt: str, *, first_error: ValueError,
                           invoke, remaining: float) -> str:
    """Retry only an invalid first Qwen script once with the SAME local GGUF.

    Never change model weights, acceptance rules, user prose or output text.
    A second rejected draft must not be saved as a successful manuscript.
    """
    if (type(first_error) is not ValueError
            or str(first_error) not in (
                'native output lacks Korean novel prose',
                'native non-Korean script in draft')
            or remaining < 25):
        raise first_error
    retry_prompt = (
        prompt + '\n'
        '첫 문장부터 한국어 소설 본문을 이어 씁니다. '
        '등장인물이 목표를 향해 행동하고 그 결과가 주변에 나타납니다.')
    return invoke(retry_prompt, remaining, '160')


def continue_korean_scene(draft: str, *, original_prompt: str, target_chars: int,
                          invoke, deadline: float, clock=time.monotonic,
                          retry_invalid=None) -> str:
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
    for _ in range(24):
        if nonspace_count(draft) >= minimum or clock() >= deadline:
            break
        previous = draft[-320:]
        # The former long continuation instructions appeared verbatim inside
        # real Windows 2022 prose, creating repetitious meta narration.
        # Preserve original author-owned facts, but minimize prompt scaffolding.
        continuation_prompt = (
            original_prompt[:1800] + '\n'
            '이어지는 문단의 앞부분:\n' + previous.strip() + '\n'
            '이어서 쓰는 장면에서 인물이 새로운 행동을 취하고 주변이 반응합니다.'
        )
        remaining = deadline - clock()
        if remaining <= 5:
            break
        try:
            next_raw = invoke(continuation_prompt, remaining)
        except (subprocess.TimeoutExpired, ValueError) as exc:
            # A later native exit/timeout must not discard a validated
            # partial Korean draft. All literary and length gates remain
            # responsible for rejecting an incomplete manuscript.
            # Other programming errors are not hidden.
            if isinstance(exc, ValueError) and str(exc) != 'model process failed':
                raise
            break
        try:
            new = validate_clean_manuscript(next_raw).strip()
        except ValueError as invalid_continuation:
            # Real Windows Qwen occasionally mixes scripts in a continuation.
            # Make at most one fresh inference with the SAME GGUF when there
            # is time. Never sanitize, translate or append rejected text.
            if retry_invalid is None or deadline - clock() < 25:
                break
            try:
                retry_raw = retry_invalid(
                    continuation_prompt, invalid_continuation,
                    deadline - clock())
                new = validate_clean_manuscript(retry_raw).strip()
            except (ValueError, subprocess.TimeoutExpired):
                # Preserve only previously validated, unapproved prose.
                break
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
        # Real Qwen continuations sometimes recite the same first paragraph
        # with a changed final phrase. Do not count it toward manuscript length.
        if repeats_existing_passage(addition, draft):
            break
        draft += '\n\n' + addition
        if len(draft) > 100_000:
            raise ValueError('invalid native output')
    return draft


def requested_scene_target(goal: str, request: dict) -> int | None:
    """Respect an explicit author scene target, else the saved episode share.

    This determines how much real model continuation to *attempt*; it never
    pads a manuscript or changes the GUI's original quality acceptance gate.
    """
    stored = request.get('target_chars')
    if stored is not None and (type(stored) is not int or not 1 <= stored <= 1_000_000):
        raise ValueError('invalid scene target length')
    match = re.search(r'(?<!\d)(\d{4,5})\s*자', goal)
    return int(match.group(1)) if match else stored


def build_story_prompts(canon: str, goal: str, conflict: str, place: str,
                        style_bible: str, characters: list[str]) -> tuple[str, str]:
    """Use concise, story-first Korean instructions for the same author facts.

    English planning labels and repeated prohibitions leaked literally into
    the actual Windows Qwen GUI drafts. This changes prompts, not the model,
    author canon, acceptance thresholds, or any persisted manuscript.
    """
    system = (
        '당신은 한국어 소설 작가입니다. 주어진 작품 설정을 유지하며 바로 소설 본문을 씁니다. '
        '인물의 선택, 행동, 대화, 주변 변화가 시간 순서대로 이어집니다. '
        '각 문단에는 이전 문단에서 일어난 사건의 결과와 새로운 진전이 있습니다. '
        '한국어 서술과 자연스러운 대화로 하나의 장면을 전개합니다.')
    scene = (
        '작품 설정:\n' + canon[:12000] + '\n'
        '회차와 장면의 사건:\n' + style_bible[:5000] + '\n'
        '이번 장면의 목표:\n' + goal[:2000] + '\n'
        '충돌과 장애물:\n' + conflict[:1000] + '\n'
        '배경 장소:\n' + place[:1000] + '\n'
        '등장인물:\n' + ', '.join(characters[:20]) + '\n'
        '첫 문장부터 인물의 행동을 한국어 소설 문단으로 이어 쓰세요.')
    return system, scene


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
        # Keep the author's original facts, but do not teach Qwen English
        # prompt/format labels that appeared in actual malformed GUI drafts.
        system_prompt, prompt = build_story_prompts(
            canon, goal, conflict, place, style_bible, characters)
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
        def invoke_native(scene_prompt: str, timeout: float,
                          budget_override: str | None = None) -> str:
            live_command = build_native_command(
                llama, model, system_prompt, scene_prompt,
                budget_override if budget_override is not None else prediction_budget)
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
        try:
            raw_draft = invoke_native(prompt, deadline - time.monotonic())
            stage = 'text_validation'
            draft = validate_clean_manuscript(raw_draft)
        except ValueError as initial_error:
            remaining = deadline - time.monotonic()
            if is_bundled_qa_model:
                # Preserve the existing bundled public GGUF retry path.
                stage = 'native_inference'
                raw_draft = retry_bundled_korean_text(
                    prompt, first_error=initial_error,
                    invoke=invoke_native, remaining=remaining)
                stage = 'text_validation'
                draft = validate_clean_manuscript(raw_draft)
            elif (model.name.lower().startswith('qwen2.5-')
                  and str(initial_error) in (
                      'native output lacks Korean novel prose',
                      'native non-Korean script in draft')
                  and remaining >= 25):
                # The actual Windows Qwen GUI failed this exact script gate.
                # Retry the SAME local model once; never translate, pad or
                # substitute a model, and keep the original rejection reason.
                stage = 'native_inference'
                raw_draft = retry_qwen_korean_text(
                    prompt, first_error=initial_error,
                    invoke=invoke_native, remaining=remaining)
                stage = 'text_validation'
                try:
                    draft = validate_clean_manuscript(raw_draft)
                except ValueError:
                    raise initial_error from None
            else:
                raise
        # A Korean-capable user-selected Qwen model sometimes returns an early
        # EOS after ~775 characters even when asked for ~5000. Continue only
        # actual model prose under the existing single 400-second deadline.
        # Never pretend that a short/incoherent scene meets the quality gate.
        target = requested_scene_target(goal, req)
        if (not is_bundled_qa_model and model.name.lower().startswith('qwen2.5-')
                and target is not None):
            draft = continue_korean_scene(
                draft, original_prompt=prompt, target_chars=target,
                invoke=invoke_native, deadline=deadline,
                retry_invalid=lambda continuation_prompt, first_error, seconds:
                    retry_qwen_korean_text(
                        continuation_prompt, first_error=first_error,
                        invoke=invoke_native, remaining=seconds))
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
                'native non-Korean script in draft': 'NON_KOREAN_SCRIPT',
            }.get(str(exc), 'OTHER')
            reason = ';REASON=' + category
        print('LOCAL_MODEL_GENERATION_FAILED;STAGE=' + stage
              + ';TYPE=' + type(exc).__name__ + reason, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
