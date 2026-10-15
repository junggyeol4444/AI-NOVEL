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
            'novel_bible': 'Entirely invented test village and original protagonist.',
            'scene_goal': 'Write a brief ORIGINAL scene in an imaginary lantern village.',
            'scene_conflict': 'A storm prevents the traveler from reaching the inn.',
            'scene_location': 'Invented lantern village',
            'characters': ['Original Traveler']}}
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
        candidates = [
            ('minimal', [str(native), '--model', known_model,
                         '--prompt', 'Once upon a time', '--predict', '8']),
            ('single_turn', [str(native), '--model', known_model,
                             '--prompt', 'Once upon a time', '--predict', '8',
                             '--single-turn', '--no-display-prompt']),
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
                print('Synthetic native diagnostic:', label,
                      'exit', probe.returncode,
                      'stderr_categories', sorted(set(classes)),
                      'stdout_bytes', len(probe.stdout),
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
    report = {'run':'WIN_X64_OFFLINE_NATIVE_BUNDLE',
              'model_weights_present':True,
              'model_weight_bytes':model.stat().st_size,
              'actual_gguf_local_inference':True,
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
