"""Offline acceptance: compiled JSON bridge -> bundled llama.cpp -> real GGUF.

Runs ONLY against disposable synthetic content. Saves hashes/counters, never
prints or uploads the model output or a user's manuscript.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main(argv):
    if len(argv) != 1:
        return 2
    folder = Path(argv[0]).resolve()
    bridge = folder / 'ANF_Local_Model.exe'
    model = folder / 'models' / 'SmolLM2-135M-Instruct-Q4_K_M.gguf'
    if not bridge.is_file() or not model.is_file():
        raise AssertionError('complete offline bundle required')
    payload = {
        'protocol': 'anf-local-scene-v1', 'task': 'scene_draft',
        'request': {
            'project_id': 'synthetic-qa-project',
            'episode_number': 1, 'scene_number': 1,
            'novel_bible': '허구의 등불 마을과 독창적인 주인공만 등장하며 참고작을 복제하지 않는 가상 소설이다.',
            'scene_goal': '허구의 등불 마을에서 주인공이 여관을 찾아가는 독창적인 한국어 소설 장면을 작성한다.',
            'scene_conflict': '갑작스러운 폭풍으로 여관으로 가는 길이 막힌다.',
            'scene_location': '허구의 등불 마을',
            'characters': ['가상의 여행자']}}
    env = {k: os.environ[k] for k in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP')
           if k in os.environ}
    env['HF_HUB_OFFLINE'] = '1'
    env['TRANSFORMERS_OFFLINE'] = '1'
    process = subprocess.run([str(bridge)], input=json.dumps(payload),
                             capture_output=True, text=True, encoding='utf-8',
                             errors='replace', cwd=folder, env=env, timeout=145)
    if process.returncode:
        # The sidecar emits only sanitized codes. Never show model prompts.
        print('Bridge exit:', process.returncode,
              'Native status:', process.stderr.strip()[-300:],
              'Output bytes:', len(process.stdout))
        # Diagnose only public synthetic inputs with native executable.
        # Never print its stdout/stderr because they may include model prose.
        native = folder / 'runtime' / 'llama-cli.exe'
        known_model = str(model)
        # Unlike llama-cli, the bundled bridge actually calls
        # llama-completion.exe. Probe that same executable and flag family
        # with original, disposable Korean text; do not print model prose.
        completion = native.with_name('llama-completion.exe')
        candidates = [
            ('minimal_cli_baseline', [str(native), '--model', known_model,
                                      '--prompt', 'Once upon a time', '--predict', '8']),
            ('completion_korean_native_path', [
                str(completion), '--model', known_model, '--predict', '128',
                '--ctx-size', '4096', '--threads', '1', '--threads-batch', '1',
                '--repeat-penalty', '1.16', '--repeat-last-n', '256',
                '--temp', '0.8', '--top-p', '0.92', '--no-display-prompt',
                '--log-verbosity', '0',
                '--system-prompt', '한국어로만 허구의 소설 첫 문장을 집필하세요.',
                '--prompt', '허구의 등불 마을에서 여행자가 폭풍을 만났다. 첫 문장부터 소설 본문만 작성하세요.',
                '--single-turn']),
        ]
        for label, cmd in candidates:
            try:
                probe = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace',
                                       cwd=native.parent, timeout=35)
                err = probe.stderr.lower()
                classes = [tag for tag in ('unknown argument', 'invalid argument',
                            'not recognized', 'failed to load model',
                            'error loading model', 'could not load',
                            'model load', 'failed to initialize', 'failed to open',
                            'gguf', 'error:', 'unknown option') if tag in err]
                # Counts only; neither prompts nor generated prose in logs.
                print('Synthetic native diagnostic:', label,
                      'exit', probe.returncode,
                      'stderr_categories', sorted(set(classes)),
                      'stdout_bytes', len(probe.stdout.encode('utf-8')),
                      'stdout_hangul', sum('가' <= ch <= '힣' for ch in probe.stdout),
                      'stdout_latin', sum(('A' <= ch <= 'Z') or ('a' <= ch <= 'z')
                                          for ch in probe.stdout),
                      'stdout_replacement', probe.stdout.count('\ufffd'),
                      'stderr_bytes', len(probe.stderr))
            except subprocess.TimeoutExpired:
                print('Synthetic native diagnostic:', label, 'TIMEOUT')
        raise AssertionError('bundle model binary did not complete')
    try:
        result = json.loads(process.stdout)
    except (ValueError, TypeError):
        raise AssertionError('bundle response is not JSON') from None
    if result.get('protocol') != 'anf-local-scene-v1':
        raise AssertionError('invalid local model protocol')
    draft = result.get('draft')
    if not isinstance(draft, str) or not draft.strip() or len(draft) > 100000:
        raise AssertionError('missing generated text')
    # A user-selected GGUF file must be accepted from an explicit absolute
    # path. Use the already bundled *synthetic QA* weight for a deterministic
    # command-line compatibility regression; never fetch user files.
    alternate = subprocess.run(
        [str(bridge), '--gguf', str(model)],
        input=json.dumps(payload), capture_output=True,
        text=True, encoding='utf-8', errors='replace',
        cwd=folder, env=env, timeout=145)
    if alternate.returncode:
        # The bridge emits only fixed, sanitized error categories (no prose).
        # Record this exact failure separately from the earlier default call.
        print('Explicit local GGUF bridge exit:', alternate.returncode,
              'Native status:', alternate.stderr.strip()[-300:],
              'Output bytes:', len(alternate.stdout))
        raise AssertionError('explicit local GGUF model selection failed')
    selected_output = json.loads(alternate.stdout)
    if (selected_output.get('protocol') != 'anf-local-scene-v1'
            or not selected_output.get('draft', '').strip()):
        raise AssertionError('selected GGUF model produced no scene')
    rejected = subprocess.run(
        [str(bridge), '--gguf', 'https://example.invalid/nonlocal.gguf'],
        capture_output=True, cwd=folder, env=env, timeout=30)
    if rejected.returncode == 0:
        raise AssertionError('bridge accepted a remote model URL')

    report = {'run':'WIN_X64_OFFLINE_NATIVE_BUNDLE',
              'model_weights_present':True,
              'model_weight_bytes':model.stat().st_size,
              'actual_gguf_local_inference':True,
              'user_selected_gguf_offline_inference':'PASS',
              'remote_model_url_rejected':True,
              'no_python_runtime_required_by_user':True,
              'no_remote_api_called':True,
              'draft_sha256':hashlib.sha256(draft.encode('utf-8')).hexdigest(),
              'draft_char_count':len(draft),
              'quality_or_250_episode_approval':False,
              'status':'PASS'}
    out = Path('build/ci/portable_model_e2e.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',
                   encoding='utf-8')
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
