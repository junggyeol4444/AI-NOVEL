"""Append-only, author-owned local spelling and character-voice rules.

This is author-written planning material, never a quality certificate, copyright
clearance, AI execution approval or publishing consent. The existing SQLite,
reference texts, drafts and final manuscripts are never modified here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import os
import time
from uuid import uuid4

from .database.episodes import EpisodeStore
from .author_arc_ledger import canon_fingerprint


class AuthorLanguageError(ValueError):
    """No exception includes the private manuscript or local file path."""


@dataclass(frozen=True)
class AuthorLanguageRule:
    rule_id: str
    project_id: str
    kind: str  # TERM, VOICE
    first_episode: int
    last_episode: int
    subject: str
    preferred: str
    discouraged: tuple[str, ...]
    guidance: str
    canon_sha256: str
    withdrawn: bool = False


FORMAT = 'anf_author_language_v1'
MAX_FILES = 3000
MAX_EVENT_BYTES = 8192
MAX_ACTIVE_RULES = 500


def _folder(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise AuthorLanguageError('작가가 직접 선택한 기존 로컬 규칙 폴더가 필요합니다.')
    return path


def _episode(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 1000:
        raise AuthorLanguageError('언어 규칙의 회차 범위는 1~1000화입니다.')
    return value


def _line(value: str, max_chars: int, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise AuthorLanguageError('작가 표기·말투 입력 형식이 올바르지 않습니다.')
    clean = value.strip()
    if (not clean and not allow_empty) or len(clean) > max_chars or len(clean.encode('utf-8')) > max_chars * 4:
        raise AuthorLanguageError('작가 표기·말투 입력 길이를 확인하세요.')
    if any(ord(c) < 32 or ord(c) == 127 for c in clean):
        raise AuthorLanguageError('규칙에는 줄바꿈·제어 문자를 입력할 수 없습니다.')
    return clean


def _alternatives(values: object, preferred: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > 12:
        raise AuthorLanguageError('비권장 표기는 최대 12개만 지정할 수 있습니다.')
    answer = tuple(_line(x, 80) for x in values)
    variants = [s.casefold() for s in answer]
    if len(set(variants)) != len(variants) or preferred.casefold() in variants:
        raise AuthorLanguageError('권장 표기와 중복되는 비권장 표기가 있습니다.')
    return answer


def _entries(directory: Path) -> tuple[Path, ...]:
    result = []
    for item in directory.iterdir():
        if item.name.startswith('anf-language-') and item.name.endswith('.json'):
            if item.is_symlink() or not item.is_file():
                raise AuthorLanguageError('언어 기록 폴더에 허용되지 않는 항목이 있습니다.')
            result.append(item)
            if len(result) > MAX_FILES:
                raise AuthorLanguageError('언어 규칙 사건 파일이 너무 많습니다.')
    return tuple(sorted(result, key=lambda path: path.name))


def language_ledger_fingerprint(folder: str | Path) -> str:
    digest = sha256()
    for file in _entries(_folder(folder)):
        try:
            body = file.read_bytes()
        except OSError:
            raise AuthorLanguageError('언어 기록의 지문을 읽지 못했습니다.') from None
        if len(body) > MAX_EVENT_BYTES:
            raise AuthorLanguageError('언어 기록 파일의 크기가 초과됐습니다.')
        digest.update(file.name.encode('utf-8') + b'\x00')
        digest.update(len(body).to_bytes(8, 'big') + body)
    return digest.hexdigest()


def _events(folder: str | Path) -> tuple[dict, ...]:
    events = []
    for file in _entries(_folder(folder)):
        try:
            if file.stat().st_size > MAX_EVENT_BYTES:
                raise AuthorLanguageError('언어 규칙 사건 파일이 너무 큽니다.')
            record = json.loads(file.read_bytes().decode('utf-8'))
        except (OSError, UnicodeError, ValueError):
            raise AuthorLanguageError('언어 규칙 사건을 읽지 못했습니다.') from None
        if (type(record) is not dict or record.get('format') != FORMAT
                or record.get('action') not in ('ADD', 'WITHDRAW')
                or type(record.get('project_id')) is not str
                or not 1 <= len(record['project_id']) <= 100
                or type(record.get('rule_id')) is not str
                or len(record['rule_id']) != 32
                or any(c not in '0123456789abcdef' for c in record['rule_id'])):
            raise AuthorLanguageError('언어 규칙 사건 형식이 잘못됐습니다.')
        events.append(record)
    return tuple(events)


def read_author_language_rules(folder: str | Path, project_id: str) -> tuple[AuthorLanguageRule, ...]:
    if type(project_id) is not str or not project_id:
        raise AuthorLanguageError('기존 작품을 먼저 선택하세요.')
    active: dict[str, AuthorLanguageRule] = {}
    withdrawn: set[str] = set()
    for record in _events(folder):
        if record['project_id'] != project_id:
            continue
        ident = record['rule_id']
        if record['action'] == 'WITHDRAW':
            if ident not in active or ident in withdrawn:
                raise AuthorLanguageError('언어 규칙 철회 이력이 올바르지 않습니다.')
            withdrawn.add(ident)
            continue
        if ident in active:
            raise AuthorLanguageError('중복된 언어 규칙 기록입니다.')
        try:
            kind = record['kind']
            first, last = _episode(record['first_episode']), _episode(record['last_episode'])
            if kind not in ('TERM', 'VOICE') or first > last:
                raise ValueError
            subject = _line(record['subject'], 100)
            preferred = _line(record['preferred'], 180)
            discouraged = _alternatives(record['discouraged'], preferred)
            guidance = _line(record['guidance'], 500, allow_empty=True)
            canon = record['canon_sha256']
            if type(canon) is not str or len(canon) != 64 or any(c not in '0123456789abcdef' for c in canon):
                raise ValueError
        except (KeyError, TypeError, ValueError, AuthorLanguageError):
            raise AuthorLanguageError('저장된 언어 규칙 내용이 올바르지 않습니다.') from None
        active[ident] = AuthorLanguageRule(ident, project_id, kind, first, last,
                                           subject, preferred, discouraged, guidance, canon)
    rules = tuple(sorted((AuthorLanguageRule(**{**rule.__dict__, 'withdrawn': rule.rule_id in withdrawn})
                          for rule in active.values()), key=lambda r: (r.first_episode, r.kind, r.subject, r.rule_id)))
    live = [rule for rule in rules if not rule.withdrawn]
    if len(live) > MAX_ACTIVE_RULES:
        raise AuthorLanguageError('현재 작품의 활성 언어 규칙 개수가 초과됐습니다.')
    for i, first in enumerate(live):
        for second in live[i + 1:]:
            if (first.kind == second.kind and first.subject.casefold() == second.subject.casefold()
                    and first.first_episode <= second.last_episode
                    and second.first_episode <= first.last_episode):
                raise AuthorLanguageError('같은 대상을 위한 언어 규칙의 유효 회차가 겹칩니다.')
    return rules


def _append(folder: Path, event: dict) -> None:
    raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_EVENT_BYTES or len(_entries(folder)) >= MAX_FILES:
        raise AuthorLanguageError('언어 규칙 사건 저장 한도를 초과했습니다.')
    filename = 'anf-language-' + f'{time.time_ns():020d}' + '-' + uuid4().hex + '.json'
    try:
        options = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(folder / filename, options, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        raise AuthorLanguageError('작가 언어 규칙을 신규 파일로 기록하지 못했습니다.') from None


def add_author_language_rule(store: EpisodeStore, project_id: str, *, folder: str | Path,
                             kind: str, first_episode: int, last_episode: int,
                             subject: str, preferred: str, discouraged: tuple[str, ...],
                             guidance: str, explicit_author_save: bool) -> str:
    if explicit_author_save is not True:
        raise AuthorLanguageError('이번 작가 언어 규칙 저장을 직접 승인해야 합니다.')
    if kind not in ('TERM', 'VOICE'):
        raise AuthorLanguageError('언어 규칙 종류가 올바르지 않습니다.')
    first, last = _episode(first_episode), _episode(last_episode)
    if first > last:
        raise AuthorLanguageError('언어 규칙 회차 범위가 올바르지 않습니다.')
    subject = _line(subject, 100)
    preferred = _line(preferred, 180)
    guidance = _line(guidance, 500, allow_empty=True)
    discouraged = _alternatives(discouraged, preferred)
    directory = _folder(folder)
    old = read_author_language_rules(directory, project_id)
    for rule in old:
        if (not rule.withdrawn and rule.kind == kind and rule.subject.casefold() == subject.casefold()
                and first <= rule.last_episode and rule.first_episode <= last):
            raise AuthorLanguageError('동일 대상의 기존 활성 언어 규칙과 범위가 겹칩니다.')
    if sum(not r.withdrawn for r in old) >= MAX_ACTIVE_RULES:
        raise AuthorLanguageError('작품의 활성 언어 규칙 한도를 초과했습니다.')
    canon = canon_fingerprint(store, project_id)
    ident = uuid4().hex
    _append(directory, {'format': FORMAT, 'action': 'ADD', 'project_id': project_id,
                        'rule_id': ident, 'kind': kind, 'first_episode': first,
                        'last_episode': last, 'subject': subject, 'preferred': preferred,
                        'discouraged': list(discouraged), 'guidance': guidance,
                        'canon_sha256': canon, 'qc_pass': False,
                        'publication_approved': False})
    return ident


def withdraw_author_language_rule(folder: str | Path, project_id: str, rule_id: str,
                                  *, explicit_author_withdraw: bool) -> None:
    if explicit_author_withdraw is not True:
        raise AuthorLanguageError('이번 작가 언어 규칙 철회를 직접 승인해야 합니다.')
    directory = _folder(folder)
    current = [r for r in read_author_language_rules(directory, project_id)
               if r.rule_id == rule_id and not r.withdrawn]
    if len(current) != 1:
        raise AuthorLanguageError('철회할 활성 언어 규칙을 찾지 못했습니다.')
    _append(directory, {'format': FORMAT, 'action': 'WITHDRAW',
                        'rule_id': rule_id, 'project_id': project_id,
                        'qc_pass': False, 'publication_approved': False})
