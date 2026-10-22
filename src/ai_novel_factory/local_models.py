"""Stage 61: offline-only scene draft provider contract and opt-in local IPC.

No HTTP clients, cloud endpoints, remote API keys, publishing, or DB writes.
Actual provider binaries must be separately vetted by the user before execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import re
from typing import Protocol


PROTOCOL_VERSION = 'anf-local-scene-v1'
MAX_CONTEXT_CHARS = 30_000
MAX_DRAFT_CHARS = 100_000


class LocalModelError(ValueError):
    """Invalid input or rejected local model result; no secret data in messages."""


@dataclass(frozen=True)
class SceneDraftRequest:
    """Author-owned facts only; reference novel source text is never a field."""
    project_id: str
    episode_number: int
    scene_number: int
    novel_bible: str
    scene_goal: str
    scene_conflict: str
    scene_location: str
    characters: tuple[str, ...]
    style_bible: str = ''
    # User's per-scene share of the saved episode-length target.
    # Optional to preserve existing provider and fixture compatibility.
    target_chars: int | None = None


@dataclass(frozen=True)
class SceneDraftResult:
    project_id: str
    episode_number: int
    scene_number: int
    draft: str
    provider: str
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    persisted: bool = False


class SceneDraftProvider(Protocol):
    provider_id: str

    def generate(self, request: SceneDraftRequest) -> str: ...


def _clean(value: object, *, label: str, required: bool = True, maximum: int = MAX_CONTEXT_CHARS) -> str:
    if type(value) is not str or len(value) > maximum or '\x00' in value or (required and not value.strip()):
        raise LocalModelError(f'{label}: invalid text')
    return value


def effective_scene_target(goal: str, allocated_chars: int | None) -> int | None:
    """Mirror the native Windows bridge's explicit per-scene character override.

    Display the actual requested target, not just the default chapter split.
    This never changes author settings or quality thresholds.
    """
    if type(goal) is not str or (allocated_chars is not None and (
            type(allocated_chars) is not int
            or not 1 <= allocated_chars <= 1_000_000)):
        raise LocalModelError('invalid scene target length')
    # Short (50..999) batch scene allocations must win over numbers
    # quoted later in a model-written episode outline.
    match = re.match(r'\s*목표 분량\s*(\d{2,5})\s*자', goal)
    if match is None:
        match = re.search(r'(?<!\d)(\d{4,5})\s*자', goal)
    return int(match.group(1)) if match else allocated_chars


def validate_request(request: SceneDraftRequest) -> None:
    if not isinstance(request, SceneDraftRequest):
        raise LocalModelError('invalid scene request')
    _clean(request.project_id, label='project_id', maximum=128)
    if type(request.episode_number) is not int or request.episode_number < 1:
        raise LocalModelError('invalid episode number')
    if type(request.scene_number) is not int or request.scene_number < 1:
        raise LocalModelError('invalid scene number')
    for key in ('novel_bible', 'scene_goal', 'scene_conflict', 'scene_location'):
        _clean(getattr(request, key), label=key)
    _clean(request.style_bible, label='style_bible', required=False)
    if type(request.characters) is not tuple or not request.characters or len(request.characters) > 100:
        raise LocalModelError('invalid characters')
    for name in request.characters:
        _clean(name, label='character', maximum=200)
    if request.target_chars is not None and (
            type(request.target_chars) is not int
            or not 1 <= request.target_chars <= 1_000_000):
        raise LocalModelError('invalid scene target length')
    if sum(len(getattr(request, f)) for f in
           ('novel_bible', 'scene_goal', 'scene_conflict', 'scene_location', 'style_bible')) + sum(map(len, request.characters)) > MAX_CONTEXT_CHARS:
        raise LocalModelError('context exceeds limit')


def _message(request: SceneDraftRequest) -> dict:
    # Author-owned canon is first in the wire payload. No reference work content.
    return {'protocol': PROTOCOL_VERSION, 'task': 'scene_draft',
            'request': {'novel_bible': request.novel_bible,
                        'project_id': request.project_id,
                        'episode_number': request.episode_number,
                        'scene_number': request.scene_number,
                        'scene_goal': request.scene_goal,
                        'scene_conflict': request.scene_conflict,
                        'scene_location': request.scene_location,
                        'characters': list(request.characters),
                        'style_bible': request.style_bible,
                        **({'target_chars': request.target_chars}
                           if request.target_chars is not None else {})}}


class MockSceneProvider:
    """Deterministic contract fixture, NOT a language model."""
    provider_id = 'offline-mock-v1'

    def generate(self, request: SceneDraftRequest) -> str:
        validate_request(request)
        return (f'[모의 초고 — 실제 AI 생성 아님] {request.episode_number}화 '
                f'{request.scene_number}장면: {request.scene_goal.strip()}')


class LocalExecutableProvider:
    """Opt-in JSON-over-stdin process adapter, never HTTP or a shell command.

    A trusted local executable implements the documented protocol. The Python
    adapter cannot guarantee that an arbitrary executable won't use the network.
    """
    provider_id = 'local-executable-v1'

    def __init__(self, executable: str | Path, *, arguments: tuple[str, ...] = (),
                 timeout_seconds: float = 15.0, explicitly_allowed: bool = False):
        if explicitly_allowed is not True:
            raise LocalModelError('explicit local executable approval required')
        # pathlib.Path is a factory: actual instances are WindowsPath or
        # PosixPath. Accept these declared Path types, not only type(Path).
        if not isinstance(executable, (str, Path)):
            raise LocalModelError('invalid local executable path')
        path = Path(executable)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise LocalModelError('an existing executable absolute path is required')
        if type(arguments) is not tuple or any(type(v) is not str or '\x00' in v for v in arguments):
            raise LocalModelError('invalid executable arguments')
        # The existing short timeout still protects arbitrary approved
        # executables. Only the bundled portable bridge with an explicitly
        # selected GGUF may run the longer CPU Qwen inference needed for a
        # genuine 5000-character scene; this is NOT an acceptance relaxation.
        long_cpu_gguf = (path.name.casefold() == 'anf_local_model.exe'
                         and arguments[:1] == ('--gguf',))
        ceiling = 1550 if long_cpu_gguf else 480
        if (type(timeout_seconds) not in (float, int)
                or isinstance(timeout_seconds, bool)
                or not 0 < timeout_seconds <= ceiling):
            raise LocalModelError('invalid local process timeout')
        self._command = (str(path), *arguments)
        self._timeout = float(timeout_seconds)

    def generate(self, request: SceneDraftRequest) -> str:
        validate_request(request)
        payload = json.dumps(_message(request), ensure_ascii=False)
        # Do not inherit potentially sensitive token/API-key environment entries.
        environment = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TMP', 'TEMP', 'TMPDIR') if k in os.environ}
        environment['PYTHONIOENCODING'] = 'utf-8'
        try:
            completed = subprocess.run(self._command, input=payload, capture_output=True,
                                       text=True, encoding='utf-8', errors='replace',
                                       timeout=self._timeout, check=False, env=environment,
                                       shell=False)
        except subprocess.TimeoutExpired:
            raise LocalModelError('native_timeout') from None
        except OSError:
            raise LocalModelError('local provider execution failed') from None
        if completed.returncode != 0:
            # Public compiled bridge emits a machine-readable failure category;
            # never expose stderr or user prompts from arbitrary executables.
            match = re.search(
                r'LOCAL_MODEL_GENERATION_FAILED;STAGE=([a-z_]+);TYPE=([A-Za-z]+)',
                completed.stderr[:300])
            if match:
                if match.group(1) == 'native_inference':
                    if match.group(2) == 'TimeoutExpired':
                        raise LocalModelError('native_timeout')
                    # Observed Windows 0xC0000374 (heap corruption).
                    # The same Windows NTSTATUS may be rendered as signed or
                    # unsigned by Python/PowerShell subprocess reporting.
                    # Classify both heap corruption and access violations
                    # without leaking private native stderr/model text.
                    if re.search(
                        r'LLAMA_NATIVE_EXIT=(?:3221226356|-1073740940'
                        r'|3221225477|-1073741819)(?![0-9])',
                        completed.stderr[:500]):
                        raise LocalModelError('native_process_crash')
                    raise LocalModelError('native_inference_failure')
                if match.group(1) == 'text_validation':
                    # The compiled bridge emits fixed, non-author-derived
                    # categories; distinguish a missing Hangul draft from
                    # Chinese script or echoed instructions without printing
                    # stdout, stderr, paths, prompts or manuscript contents.
                    reason = re.search(r';REASON=([A-Z_]+)', completed.stderr[:300])
                    safe_reason = reason.group(1) if reason else ''
                    if safe_reason == 'NO_HANGUL':
                        raise LocalModelError('native_no_hangul')
                    if safe_reason == 'NON_KOREAN_SCRIPT':
                        raise LocalModelError('native_non_korean_script')
                    if safe_reason == 'CONSOLE_OR_PROMPT_ECHO':
                        raise LocalModelError('native_prompt_echo')
                    if safe_reason == 'SHORT_DRAFT':
                        raise LocalModelError('native_short_draft')
                    if safe_reason == 'UNSUPPORTED_TARGET':
                        raise LocalModelError('native_unsupported_target')
                    raise LocalModelError('native_output_rejected')
            raise LocalModelError('local provider rejected')
        if len(completed.stdout) > MAX_DRAFT_CHARS + 5000:
            raise LocalModelError('local provider oversized response')
        try:
            response = json.loads(completed.stdout)
        except (ValueError, TypeError):
            raise LocalModelError('invalid local provider JSON') from None
        if type(response) is not dict or response.get('protocol') != PROTOCOL_VERSION:
            raise LocalModelError('incompatible local provider protocol')
        # The native Windows bridge binds draft transport to its source scene.
        # Older v1 providers may omit this optional metadata, but incomplete
        # or mismatching metadata must never be accepted as the wrong scene.
        identity_keys = ('project_id', 'episode_number', 'scene_number')
        if any(key in response for key in identity_keys):
            if (type(response.get('project_id')) is not str
                    or type(response.get('episode_number')) is not int
                    or type(response.get('scene_number')) is not int
                    or response['project_id'] != request.project_id
                    or response['episode_number'] != request.episode_number
                    or response['scene_number'] != request.scene_number):
                raise LocalModelError('local provider scene identity mismatch')
        return _clean(response.get('draft'), label='draft', maximum=MAX_DRAFT_CHARS)


def draft_scene(request: SceneDraftRequest, provider: SceneDraftProvider) -> SceneDraftResult:
    """Explicit, non-persisting call; provider errors fail closed."""
    validate_request(request)
    if provider is None or not isinstance(getattr(provider, 'provider_id', None), str):
        raise LocalModelError('invalid provider')
    if provider.provider_id not in ('offline-mock-v1', 'local-executable-v1'):
        raise LocalModelError('provider not on offline-only allowlist')
    try:
        raw = provider.generate(request)
    except LocalModelError:
        raise
    except Exception:
        raise LocalModelError('provider generation failed') from None
    draft = _clean(raw, label='draft', maximum=MAX_DRAFT_CHARS)
    return SceneDraftResult(request.project_id, request.episode_number,
                            request.scene_number, draft, provider.provider_id)
