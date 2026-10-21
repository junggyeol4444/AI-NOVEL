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
        # Actual Windows2022 Qwen draft artifact 12230304211 closed with
        # an explanation of its instruction instead of the story's events.
        '그런 의미에서는 바로 그것이 이번 회차의 목표였습니다:',
        # Real compiled Windows 2022/11 Qwen artifact 12243880394 and
        # 12242784973 was SCENE METADATA, not a finished prose narrative.
        # Never save the screenplay outline as an author-written novel.
        '다음은 첫 회차의 장면입니다.',
        '이어서 쓰는 장면에서 인물의 선택과 행동이 변화하고 주변 환경이 변합니다.',
        # Verbatim model imitation of bridge continuation prompts occurred
        # in the actual Windows2022 Qwen 5000-char failure manuscript.
        '이어서 쓰는 장면에서 인물이 새로운 행동을 취하고 주변이 반응합니다.',
        '이어서 쓰는 장면에서 인물의 선택이 실제 결과를 낳습니다.',
        '앞에서 했던 질문이나 대답을 다시 쓰지 않고 다음 사건으로 나아갑니다.',
        '이어서 쓰는 장면에서 새로 드러난 장애물에 대응하는 행동과',
    )
    if any(fragment in lower for fragment in forbidden):
        raise ValueError('native console output mixed with draft')
    # Actual Windows2022 Qwen generated multiline role/script metadata:
    # "**시작**", "<날씨: 비가 시작했다>", "**장소:**", "**결과:**".
    # Only reject these when they appear as standalone headings/labels;
    # in-world dialogue can still mention a place, result or explanation.
    if re.search(
        r'(?m)^\s*(?:\*\*(?:시작|사건|장소|인물|시간|설명|내용|'
        r'결과|결론)\*\*\s*:?' 
        r'|\*\*(?:장소|인물|시간|설명|내용|결과|결론):\*\*'
        r'|<날씨\s*:[^\r\n>]{1,80}>\s*$'
        r'|---+\s*$)', text):
        raise ValueError('native console output mixed with draft')
    # Actual Windows11 ARM Qwen 5000-char run 39379614192 wrote a screenplay,
    # beginning with "### 장면 1", "**(날짜: ...)**", "**조사자:**"
    # and "**(사서)**". These are production role/shot notes, not prose.
    # Reject even when followed by otherwise well-formed Korean sentences.
    if re.search(
        r'(?m)^[ \t]*(?:#{1,6}[ \t]*(?:장면[ \t]*[0-9]+'
        r'|첫[ \t]*장|제[ \t]*[0-9]+화|Scene[ \t]*[0-9]+)[^\r\n]{0,80}'
        r'|\*\*[ \t]*\([^()\r\n]{1,80}\)[ \t]*\*\*'
        r'|\*\*[ \t]*[가-힣][가-힣 ]{0,24}:[ \t]*\*\*)[ \t]*$',
        text):
        raise ValueError('native console output mixed with draft')
    # The real Windows 11 ARM Qwen output included an instruction-like
    # "next scene ... assume" sentence, not a fictional character's action.
    # Fail closed rather than persisting this observed meta narration.
    if re.search(r'다음 장면은.{0,120}가정하겠습니다\s*:', text):
        raise ValueError('native console output mixed with draft')
    # Actual ARM Qwen artifact 12232291994 included a non-literary
    # English chapter outline ("# Chapter 1", "Chapter 2"). Reject the
    # model's scaffolding rather than counting it as Korean novel prose.
    if re.search(r'(?im)^\s*(?:#{1,6}\s*)?chapter\s+[0-9]+\s*$', text):
        raise ValueError('native console output mixed with draft')
    if not any('가' <= ch <= '힣' for ch in text):
        raise ValueError('native output lacks Korean novel prose')
    # Actual Windows 2022 output leaked CJK; Windows 11 ARM output also
    # contained Cyrillic letters and a U+FFFD decoding replacement.
    # Reject those observed corruptions, never rewrite model-authored prose.
    if re.search(r'[\u3400-\u9fff\u3040-\u30ff\u0400-\u052f\ufffd]', text):
        raise ValueError('native non-Korean script in draft')
    # A later real Windows2022 Qwen sample (artifact 12243535386) leaked
    # the uppercase mixed-script word "침Inlining". Both lowercase and
    # uppercase Latin must be rejected by the SAME existing script gate.
    # Do not alter or translate model-authored prose.
    # Real Windows 11 ARM artifact 12230384722 contained malformed single
    # Korean tokens such as 묘mer, 드ừng, 난ık. Do not reject legitimate
    # separately spaced foreign names, but reject corruption fused into
    # Hangul words without changing the text or translating it.
    if re.search(r'[가-힣](?:[A-Za-z]{2,}|[\u0100-\u024f\u1e00-\u1eff])', text):
        raise ValueError('native non-Korean script in draft')
    # The same actual novel draft contained actor-style line labels instead
    # of prose dialogue. No script/transcript should become approved prose.
    if re.search(r'(?m)^[가-힣][가-힣 ]{0,14}:\s*["“]', text):
        raise ValueError('native console output mixed with draft')
    # Windows bundled 135M repeatedly produced one Korean word among long
    # English paragraphs (real repeat-GGUF run 39526952842).  The existing
    # GUI quality screen ALREADY requires >=78% Hangul and <=5% Latin.
    # Reject its clearly non-Korean candidate early, allowing an independent
    # SAME-GGUF retry rather than "successful" but unusable preview.
    # Tiny snippets (<80 nonspace chars) retain the previous basic transport
    # check; the GUI still applies the full exact format gate.
    compact = ''.join(text.split())
    if len(compact) >= 80:
        hangul = sum('가' <= ch <= '힣' for ch in compact)
        latin = sum(('A' <= ch <= 'Z') or ('a' <= ch <= 'z') for ch in compact)
        if (hangul * 100 < 78 * len(compact)
                or latin > max(5, (len(compact) + 19) // 20)):
            raise ValueError('native non-Korean script in draft')
    return text


def native_script_failure_category(raw: str) -> str:
    """Finite, no-content script labels for the rejected native sample.

    Does not store, print or send author text, prompts or model prose. Strict
    validation and the real 5000-character quality gate remain unchanged.
    """
    if type(raw) is not str:
        return 'UNKNOWN'
    if '\ufffd' in raw:
        return 'DECODING_REPLACEMENT'
    if re.search(r'[\u0400-\u052f]', raw):
        return 'CYRILLIC'
    if re.search(r'[\u3040-\u30ff]', raw):
        return 'KANA'
    if re.search(r'[\u3400-\u9fff]', raw):
        return 'HAN'
    if re.search(r'[가-힣](?:[A-Za-z]{2,}|[\u0100-\u024f\u1e00-\u1eff])', raw):
        return 'MIXED_KOREAN_TOKEN'
    return 'OTHER'


def build_native_command(llama: Path, model: Path, system_prompt: str,
                         prompt: str, prediction_budget: str, *,
                         qwen_crash_recovery: bool = False,
                         bundled_fixture: bool | None = None) -> list[str]:
    """Use noninteractive GGUF completion for all explicitly selected local models.

    The separate completion executable avoids llama-cli's chat shell. It
    applies the model's own chat template to ordinary --system-prompt and
    --prompt arguments; never embed raw ChatML into author-controlled text.
    Its argument set excludes CLI-only --no-show-timings. Only verbosity 0
    keeps response tokens while hiding informational messages.
    """
    bundled_qa = (model.name == MODEL_NAME
                  if bundled_fixture is None else bundled_fixture)
    # A user's approved GGUF must not be treated as the tiny bundled
    # 135M smoke model merely because its filename is not "qwen2.5-*".
    # Model weights and author data are never changed by this selection.
    qwen = not bundled_qa
    # Four native CPU threads for any selected longform GGUF, one for the
    # bundled smoke fixture; a heap-corruption retry always uses one.
    threads = '1' if qwen_crash_recovery else ('4' if qwen else '1')
    common = [
        '--model', str(model), '--predict', prediction_budget,
        '--ctx-size', '4096', '--threads', threads, '--threads-batch', threads,
        # Only user-selected Qwen gets a less punitive sampling profile.
        # The observed long Windows drafts drifted from Korean into other
        # scripts; this is a hypothesis to test with REAL weights/CI, never
        # a declaration of literary quality. Bundled 135M remains unchanged.
        '--repeat-penalty', ('1.08' if qwen else '1.16'),
        '--repeat-last-n', ('128' if qwen else '256'),
        '--temp', ('0.62' if qwen else '0.8'),
        '--top-p', ('0.90' if qwen else '0.92'),
        '--no-display-prompt',
    ]
    if qwen_crash_recovery and model.suffix.lower() == '.gguf':
        # The original pinned b11624 completion executable supports this
        # memory-mapping switch. Use it only after observed 0xC0000374,
        # keeping the same GGUF, binary, author text and quality validation.
        common.append('--no-mmap')
    # Every user-approved GGUF now uses exactly the same noninteractive
    # completion executable. The prior non-Qwen fallback launched llama-cli
    # (chat shell), the source of banners and prompt echo in manuscripts.
    # Never guess a GGUF's chat template from its filename: the native
    # executable reads metadata, with strict output screening afterward.
    completion = llama.with_name('llama-completion.exe')
    if not completion.is_file():
        raise ValueError('non-interactive completion runtime missing')
    if any(token in part for part in (system_prompt, prompt) for token in
           ('<|im_start|>', '<|im_end|>', '<|im_sep|>')):
        raise ValueError('unsafe chat template delimiter')
    return [str(completion), *common, '--log-verbosity', '0',
            '--system-prompt', system_prompt, '--prompt', prompt,
            '--single-turn']



def run_native_with_heap_crash_recovery(
        llama: Path, model: Path, system_prompt: str, scene_prompt: str,
        budget: str, deadline: float, env: dict[str, str], *,
        runner=None, clock=None, bundled_fixture: bool | None = None) -> str:
    """One bounded same-model retry after Windows heap/access violation.

    No fallback model, alternate executable, weaker validation, console echo,
    or artificial manuscript. A retry is not a PASS and the caller still
    applies the original strict Korean prose validator.
    """
    runner = subprocess.run if runner is None else runner
    clock = time.monotonic if clock is None else clock
    def call(command):
        remaining = deadline - clock()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 0)
        return runner(
            command, cwd=llama.parent, env=env, capture_output=True,
            text=True, encoding='utf-8', errors='replace',
            timeout=max(1, remaining), check=False)
    command = build_native_command(
        llama, model, system_prompt, scene_prompt, budget,
        bundled_fixture=bundled_fixture)
    proc = call(command)
    bundled = (model.name == MODEL_NAME
               if bundled_fixture is None else bundled_fixture)
    qwen = (model.suffix.lower() == '.gguf' and not bundled)
    # Real Windows 2022 repeat-GGUF test 39526404872 found the very same
    # pinned runtime heap exit even with the bundled 135M model. Both
    # approved models may retry ONCE with no mmap, never swap weights.
    # Windows native GGUF runtimes can also raise STATUS_ACCESS_VIOLATION
    # (0xC0000005), independent of model brand. On exactly these two
    # observed native-crash classes, run ONE last attempt using the same
    # executable/weights and --no-mmap / one CPU thread. Never retry
    # arbitrary nonzero exits or weaken Korean/literary validation.
    # Windows may report these NTSTATUS values as signed or unsigned.
    retryable_crash = proc.returncode in (
        3221226356, -1073740940,  # STATUS_HEAP_CORRUPTION
        3221225477, -1073741819,  # STATUS_ACCESS_VIOLATION
    )
    if ((qwen or bundled) and retryable_crash
            and deadline - clock() >= 30):
        safe_command = build_native_command(
            llama, model, system_prompt, scene_prompt, budget,
            qwen_crash_recovery=True, bundled_fixture=bundled_fixture)
        proc = call(safe_command)
    if proc.returncode != 0:
        # Numeric exit only; never log model output, private prompt or stderr.
        print('LLAMA_NATIVE_EXIT=' + str(proc.returncode), file=sys.stderr)
        raise ValueError('model process failed')
    return proc.stdout



def windows_native_arm64() -> bool:
    """Detect an ARM64 Windows host even from an emulated x64 frozen EXE.

    Used only to give the SAME bundled GGUF enough CPU time. Never changes
    author data, model weights, acceptance criteria or output.
    """
    if os.name != 'nt':
        return False
    try:
        import ctypes
        api = ctypes.windll.kernel32
        get_process = api.GetCurrentProcess
        get_process.restype = ctypes.c_void_p
        query = api.IsWow64Process2
        query.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort),
                          ctypes.POINTER(ctypes.c_ushort))
        query.restype = ctypes.c_int
        process_machine = ctypes.c_ushort()
        native_machine = ctypes.c_ushort()
        if query(get_process(), ctypes.byref(process_machine),
                 ctypes.byref(native_machine)):
            return native_machine.value == 0xAA64
    except (OSError, AttributeError, ValueError):
        pass
    return os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() == 'ARM64'


def bundled_timeout_seconds(*, arm64_host: bool) -> int:
    """Separate runtime deadline from manuscript quality: never auto-approve."""
    return 300 if arm64_host else 110


def repeats_existing_passage(addition: str, manuscript: str) -> bool:
    """Reject a long copied prefix even if later words or digits differ.

    Only compares the model's actual content; no synthetic passage is added.
    This is a conservative cross-generation repetition guard, not a literary
    acceptance test, and leaves the author-owned manuscript unchanged.
    """
    current = re.sub(r'[^가-힣A-Za-z0-9]', '', addition).casefold()
    earlier = re.sub(r'[^가-힣A-Za-z0-9]', '', manuscript).casefold()
    if len(current) >= 90 and current[:90] in earlier:
        return True

    # The actual Windows2022 Qwen QA generated 55 sentence units with
    # repeated_sentence_share=16.36%. A copied sentence later in a newly
    # generated paragraph escaped the old prefix-only repetition check.
    # Detect exact meaningful sentences, never edit or auto-fill the prose.
    def substantial_sentences(value: str) -> list[str]:
        segments = re.split(r'(?<=[.!?。！？])\s+|[\r\n]+', value)
        cleaned = [re.sub(r'[^가-힣A-Za-z0-9]', '', part).casefold()
                   for part in segments]
        return [part for part in cleaned if len(part) >= 36]

    earlier_units = set(substantial_sentences(manuscript))
    seen = set()
    for unit in substantial_sentences(addition):
        if unit in earlier_units or unit in seen:
            return True
        seen.add(unit)

    # Windows2022 artifact 12230304211 repeated the same quoted question
    # and reply three times, separated by slightly different narration.
    # A repeated meaningful dialogue line should not escape the prose
    # guard solely because it is shorter than a 90-character paragraph.
    def dialogue_lines(value: str) -> list[str]:
        quotes = re.findall(r'["“]([^"”\r\n]{10,240})["”]', value)
        return [re.sub(r'[^가-힣A-Za-z0-9]', '', part).casefold()
                for part in quotes]

    old_quotes = set(dialogue_lines(manuscript))
    seen_quotes = set()
    for quote in dialogue_lines(addition):
        if len(quote) < 10:
            continue
        if quote in old_quotes or quote in seen_quotes:
            return True
        seen_quotes.add(quote)
    return False


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
    # The actual Windows bundled 135M GGUF returned an English-only scene.
    # Keep the SAME public weight and exactly one bounded genuine inference,
    # but place the Korean writing instruction BEFORE long author context.
    # Neither the user's facts nor any invalid output are altered or saved.
    retry_prompt = (
        '한국어 소설 본문을 쓰는 장면입니다. 실제 행동과 사건을 한국어 문장으로 시작합니다.\n'
        '앞선 문장의 결과가 다음 사건으로 이어지는 소설 문단을 작성합니다.\n'
        + prompt + '\n'
        + '인물은 주변에 있는 사물을 보고 한국어로 말한다. '
        '그 말을 들은 다른 인물이 실제로 움직인다.')
    return invoke(retry_prompt, remaining, '160')



def retry_bundled_korean_text_once_more(prompt: str, *,
                                        first_error: ValueError,
                                        invoke, remaining: float) -> str:
    """One independent same-GGUF sample after a strictly rejected retry.

    The Windows 2022 bundled 135M GGUF intermittently returned NO_HANGUL
    even after the existing retry. This uses unchanged public weights and
    unchanged acceptance rules, under the original bounded deadline.
    Invalid samples must never be translated, padded, logged or persisted.
    """
    if (type(first_error) is not ValueError
            or str(first_error) not in (
                'native output lacks Korean novel prose',
                'native non-Korean script in draft')
            or remaining < 25):
        raise first_error
    retry_prompt = (
        '한국어로만 창작 소설의 실제 장면을 씁니다. '
        '서술은 한국어 문장으로 시작하고 인물의 행동 뒤에 결과를 보여 줍니다.\n'
        + prompt + '\n'
        '장면의 소설 본문을 새로운 한국어 문단으로 직접 써 주세요.')
    return invoke(retry_prompt, remaining, '192')


def retry_qwen_korean_text(prompt: str, *, first_error: ValueError,
                           invoke, remaining: float, attempt: int = 0) -> str:
    """Retry only an invalid first Qwen script once with the SAME local GGUF.

    Never change model weights, acceptance rules, user prose or output text.
    A second rejected draft must not be saved as a successful manuscript.
    """
    if (type(first_error) is not ValueError
            or str(first_error) not in (
                'native output lacks Korean novel prose',
                'native non-Korean script in draft',
                'native console output mixed with draft')
            or remaining < 25):
        raise first_error
    # Observed Windows2022 and Windows11 ARM run 39383226885:
    # BOTH attempts repeated the same bridge-authored meta instruction.
    # Do not spend two expensive Qwen startups on identical input prompts.
    # Independent candidate #2 uses a different narrative-only framing of
    # the SAME author facts supplied by build_story_prompts(prose_retry=True).
    # No changing GGUF weights, original prompt in SQLite, or quality gate.
    if type(attempt) is not int or not 0 <= attempt <= 1:
        raise first_error
    # The real Windows2022/ARM error is prompt-echo, so appending another
    # command to the end of a rejected scene recreates the very failure.
    # Retry with the SAME Qwen GGUF and a separately framed prompt from
    # build_story_prompts(prose_retry=...). Leave author facts as the
    # last content. The two token budgets and strict rejection remain.
    retry_prompt = prompt.rstrip() + '\n\n'
    # Only real model tokens: no translation, synthetic padding, fallback
    # model, source rewriting or literary approval on either attempt.
    return invoke(retry_prompt, remaining,
                  '320' if attempt == 0 else '512')


def continue_korean_scene(draft: str, *, original_prompt: str, target_chars: int,
                          invoke, deadline: float, clock=time.monotonic,
                          retry_invalid=None,
                          short_retry_limit=0) -> str:
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
    # Actual Windows Qwen output repeatedly copied trailing generation
    # instructions instead of writing the scene. Keep system-level Korean
    # novelist guidance and existing author facts, but do not append ANY
    # instruction after the last real prose fragment. A completion model
    # must see story text, not the next "please write" command, at its tail.
    # Stage short genuinely native fragments, never synthetic filler.
    staged_short = ''
    # The original fixed 24-iteration ceiling could never reach a genuine
    # 5000-10000-character scene when an approved local GGUF yields valid
    # 80-150-character continuations. Size the maximum number of actual
    # native attempts from the requested remaining prose, NOT from a model
    # brand or a constant number of scene fragments. Keep the original
    # absolute deadline, output-size, script, duplication, and no-padding
    # constraints; this formula does not claim the model can write well.
    missing = max(0, minimum - nonspace_count(draft))
    max_native_attempts = min(160, max(24, (missing + 79) // 80 + 4))
    for attempt in range(max_native_attempts):
        if nonspace_count(draft) >= minimum or clock() >= deadline:
            break
        candidate_context = draft + ('\n\n' + staged_short if staged_short else '')
        previous = candidate_context[-480:].strip()
        # Root cause from the real Windows Qwen failure metadata:
        # instructions at the END of the prompt were echoed as generated
        # prose. Put the actual existing manuscript at the very end instead.
        # The author's active goal/canon stays before it; never modify those
        # saved fields. The model gets only actual manuscript as the next
        # continuation prefix. No label/command/fabricated sentence follows.
        continuation_prompt = (
            original_prompt[:1800].rstrip() + '\n\n'
            + previous + '\n\n'
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
                # A fresh Qwen invocation may fail its strict script gate
                # twice while there is still time for useful actual prose.
                # Spend the existing bounded short-retry allowance on one
                # *new* native inference. Never append rejected content.
                if short_retry_limit > 0 and deadline - clock() >= 25:
                    short_retry_limit -= 1
                    continue
                # Preserve only previously validated, unapproved prose.
                break
        # The continuation may duplicate the prose already shown as context.
        # Compare against both the committed draft and pending model tokens.
        if not new or new in candidate_context:
            if short_retry_limit > 0:
                short_retry_limit -= 1
                continue
            break
        overlap = 0
        for n in range(min(180, len(new), len(candidate_context)), 24, -1):
            if candidate_context.endswith(new[:n]):
                overlap = n
                break
        addition = new[overlap:].strip()
        if not addition or addition in candidate_context or len(addition) < 24:
            if short_retry_limit > 0:
                short_retry_limit -= 1
                continue
            break
        # Keep only individually validated model prose; stage short,
        # nonduplicated fragments, then apply the original >=80 threshold
        # to the combined real text before it reaches the preview.
        candidate = staged_short + ('\n\n' if staged_short else '') + addition
        if repeats_existing_passage(candidate, draft):
            staged_short = ''
            if short_retry_limit > 0:
                short_retry_limit -= 1
                continue
            break
        if len(candidate) < 80:
            staged_short = candidate
            # Staged text is still uncommitted. If the deadline expires,
            # it is discarded, not passed off as an accepted continuation.
            continue
        draft += '\n\n' + candidate
        staged_short = ''
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
                        style_bible: str, characters: list[str], *,
                        prose_retry: bool = False) -> tuple[str, str]:
    """Use concise, story-first Korean instructions for the same author facts.

    English planning labels and repeated prohibitions leaked literally into
    the actual Windows Qwen GUI drafts. This changes prompts, not the model,
    author canon, acceptance thresholds, or any persisted manuscript.
    """
    system = (
        '당신은 한국어 소설 작가입니다. 주어진 작품 설정을 유지하며 바로 소설 본문을 씁니다. '
        '인물의 선택, 행동, 대화, 주변 변화가 시간 순서대로 이어집니다. '
        '각 문단에는 이전 문단에서 일어난 사건의 결과와 새로운 진전이 있습니다. '
        '한국어 서술과 자연스러운 대화로 하나의 장면을 전개합니다. '
        '장소·인물·결과를 목록이나 대본으로 나누지 않고 일반 소설의 문단으로 시작합니다. '
        '인물의 표정과 행동을 서술한 뒤, 대화는 따옴표로 표현합니다.')
    # Windows Qwen has a fixed 4096-token context. The former prompt put
    # up to 17,000 characters of canon/style BEFORE the scene goal, so a
    # long author bible could hide the current action and conflict from the
    # model. Keep the same source fields/limits and the author's actual facts,
    # but place the active scene constraints ahead of the longer background.
    if prose_retry:
        # A Qwen recovery prompt with the exact SAME bounded author facts,
        # but without script-shaped scene headings that actually echoed into
        # the failed Windows2022/ARM model prose. Prompt-only transformation:
        # no project, Novel Bible, user source or database modification.
        scene = (
            '작품 설정:\n' + canon[:12000] + '\n'
            + '회차와 장면의 사건:\n' + style_bible[:5000] + '\n'
            + place[:1000] + '\n'
            + ', '.join(characters[:20]) + '\n'
            + conflict[:1000] + '\n'
            # Different label-free framing of the SAME author goal.
            # No model-authored command or invented prose after the goal.
            + goal[:2000].strip() + '\n\n')
        return system, scene
    scene = (
        # Existing author goal/characters MUST remain early, even with a
        # very long Novel Bible. This is a real scene-continuity requirement
        # already guarded by test_long_author_bible_does_not_hide_scene_goal.
        '이번 장면의 목표:\n' + goal[:2000] + '\n'
        '충돌과 장애물:\n' + conflict[:1000] + '\n'
        '배경 장소:\n' + place[:1000] + '\n'
        '등장인물:\n' + ', '.join(characters[:20]) + '\n'
        '회차와 장면의 사건:\n' + style_bible[:5000] + '\n'
        '작품 설정:\n' + canon[:12000] + '\n'
        # Model completion sees ONLY the writer's actual goal at its tail.
        # Repeating this factual goal (not a model instruction) protects it
        # from 4096-token context clipping in the native Qwen runtime.
        + goal[:2000].strip() + '\n\n')
    return system, scene


def build_continuation_context(canon: str, goal: str, conflict: str,
                               place: str, style_bible: str,
                               characters: list[str]) -> str:
    """Use only author-provided facts, prioritizing the active scene.

    The previous continuation passed original_prompt[:1800], which frequently
    contained only the start of a long novel bible. The current goal, conflict
    and characters were lost before each subsequent inference. The complete
    author bible remains untouched in the saved project and initial request.
    """
    return (
        '이번 장면의 목표:\n' + goal[:550] + '\n'
        '충돌과 장애물:\n' + conflict[:350] + '\n'
        '배경 장소:\n' + place[:250] + '\n'
        '등장인물:\n' + ', '.join(characters[:20])[:260] + '\n'
        '회차와 장면의 사건:\n' + style_bible[:400] + '\n'
        '작품 설정:\n' + canon[:650])


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
            with selected.open('rb') as stream:
                header = stream.read(24)
            if (len(header) != 24 or header[:4] != b'GGUF'
                    or int.from_bytes(header[4:8], 'little') not in (2, 3)
                    or not 1 <= int.from_bytes(header[8:16], 'little') <= 1_000_000
                    or not 1 <= int.from_bytes(header[16:24], 'little') <= 1_000_000):
                raise ValueError('invalid GGUF header')
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
        # The bundled 135M GGUF is a packaging/transport fixture, not the
        # user's chosen novel-writing model. Every explicitly selected GGUF
        # gets the SAME longer real-writing CPU deadline and continuation
        # logic, independent of brand or filename. No new default GGUF.
        # Only the packaged DEFAULT is a smoke fixture. A model explicitly
        # chosen by the author remains their selected writing model even if
        # its filename happens to match the fixture basename.
        is_bundled_qa_model = (not args and model.name == MODEL_NAME)
        is_selected_longform_model = not is_bundled_qa_model
        prediction_budget = '384' if is_bundled_qa_model else '768'
        native_timeout = (
            bundled_timeout_seconds(arm64_host=windows_native_arm64())
            if is_bundled_qa_model else 1400)
        command = build_native_command(
            llama, model, system_prompt, prompt, prediction_budget)
        env = {k: os.environ[k] for k in
               ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        env['PATH'] = str(llama.parent) + os.pathsep + env.get('PATH', '')
        deadline = time.monotonic() + native_timeout
        def invoke_native(scene_prompt: str, timeout: float,
                          budget_override: str | None = None) -> str:
            # Every attempt shares the existing scene deadline. Qwen's
            # heap-corruption-only recovery reuses these EXACT model weights.
            bounded_deadline = min(deadline, time.monotonic() + max(1, timeout))
            return run_native_with_heap_crash_recovery(
                llama, model, system_prompt, scene_prompt,
                budget_override if budget_override is not None else prediction_budget,
                bounded_deadline, env,
                bundled_fixture=is_bundled_qa_model)
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
                try:
                    draft = validate_clean_manuscript(raw_draft)
                except ValueError as rejected_retry:
                    # One final independent SAME-GGUF attempt when the real
                    # 135M weight still returns a non-Korean sample. Strict
                    # validation follows and a failure remains a failure.
                    stage = 'native_inference'
                    raw_draft = retry_bundled_korean_text_once_more(
                        prompt, first_error=rejected_retry,
                        invoke=invoke_native,
                        remaining=deadline - time.monotonic())
                    stage = 'text_validation'
                    draft = validate_clean_manuscript(raw_draft)
            elif (is_selected_longform_model
                  and str(initial_error) in (
                      'native output lacks Korean novel prose',
                      'native non-Korean script in draft',
                      'native console output mixed with draft')
                  and remaining >= 25):
                # The actual Windows Qwen GUI failed this exact script gate.
                # Retry the SAME local model once; never translate, pad or
                # substitute a model, and keep the original rejection reason.
                # Windows2022 real QA artifact 12234147184 confirmed
                # non-Korean script on both the initial Qwen output and
                # the first strict retry. Allow at most one additional
                # independent native sample with the same approved GGUF.
                # Do not translate, rewrite, store or accept rejected text.
                for initial_retry in range(2):
                    remaining = deadline - time.monotonic()
                    if remaining < 25:
                        raise initial_error from None
                    stage = 'native_inference'
                    # First: normal bounded retry. Second: truly different
                    # prose-first prompt compiled from the same author facts.
                    # Both strict validation and 1400s deadline stay intact.
                    retry_prompt = prompt
                    if initial_retry == 1:
                        _, retry_prompt = build_story_prompts(
                            canon, goal, conflict, place, style_bible,
                            characters, prose_retry=True)
                    raw_draft = retry_qwen_korean_text(
                        retry_prompt, first_error=initial_error,
                        invoke=invoke_native, remaining=remaining,
                        attempt=initial_retry)
                    stage = 'text_validation'
                    try:
                        draft = validate_clean_manuscript(raw_draft)
                    except ValueError:
                        if initial_retry == 1:
                            raise initial_error from None
                    else:
                        break
            else:
                raise
        # A Korean-capable user-selected Qwen model sometimes returns an early
        # EOS after ~775 characters even when asked for ~5000. Continue only
        # actual model prose under the existing single 400-second deadline.
        # Never pretend that a short/incoherent scene meets the quality gate.
        target = requested_scene_target(goal, req)
        if is_selected_longform_model and target is not None:
            draft = continue_korean_scene(
                draft, original_prompt=build_continuation_context(
                    canon, goal, conflict, place, style_bible, characters),
                target_chars=target,
                invoke=invoke_native, deadline=deadline,
                retry_invalid=lambda continuation_prompt, first_error, seconds:
                    retry_qwen_korean_text(
                        continuation_prompt, first_error=first_error,
                        invoke=invoke_native, remaining=seconds),
                short_retry_limit=10)
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
            if str(exc) == 'native non-Korean script in draft':
                # Fixed category only: do not leak the failed author prose.
                print('NATIVE_SCRIPT_CATEGORY=' +
                      native_script_failure_category(
                          raw_draft if 'raw_draft' in locals() else ''),
                      file=sys.stderr)
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
