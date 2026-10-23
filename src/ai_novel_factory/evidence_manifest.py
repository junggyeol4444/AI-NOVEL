"""Explicit author-labelled evidence manifest for the four longform checkers.

The author chooses a LOCAL JSON file; this reader never saves a manuscript,
infers claims, contacts a server, or marks the manuscript as QC-passed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from .episode_evidence_bundle import EvidenceAnnotations
from .continuity_checker import ManuscriptClaim
from .knowledge_checker import KnowledgeUseClaim
from .foreshadow_checker import ForeshadowClaim
from .timeline_checker import TimelineMention, TimelineOrderClaim


class EvidenceManifestError(ValueError):
    """Safe failure messages contain no private claim text or file path."""


@dataclass(frozen=True)
class LoadedEvidenceManifest:
    project_id: str
    episode: int
    manuscript_sha256: str
    annotations: EvidenceAnnotations
    publication_approved: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceManifestError('중복된 근거 항목이 있습니다.')
        result[key] = value
    return result


def _dict(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise EvidenceManifestError('근거 파일 구조가 올바르지 않습니다.')
    return value


def _items(value, limit=500):
    if type(value) is not list or len(value) > limit:
        raise EvidenceManifestError('근거 목록 길이가 올바르지 않습니다.')
    return value


def _span(item, manuscript):
    a, b = item['start'], item['end']
    if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(manuscript):
        raise EvidenceManifestError('원고의 근거 위치가 올바르지 않습니다.')
    return a, b


def _text(value, maximum=4000):
    if type(value) is not str or not value or len(value) > maximum:
        raise EvidenceManifestError('근거 텍스트가 올바르지 않습니다.')
    return value


def load_evidence_manifest(file: str | Path, *, manuscript: str,
                           project_id: str, episode: int) -> LoadedEvidenceManifest:
    if type(manuscript) is not str or not manuscript.strip() or len(manuscript) > 1_000_000:
        raise EvidenceManifestError('원고가 비어 있거나 범위를 벗어났습니다.')
    path = Path(file)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128_000:
        raise EvidenceManifestError('로컬 근거 파일이 올바르지 않습니다.')
    try:
        payload = json.loads(path.read_text(encoding='utf-8'),
                             object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise EvidenceManifestError('근거 JSON 파일을 읽지 못했습니다.') from None
    _dict(payload, ('version', 'project_id', 'episode', 'manuscript_sha256',
                    'canon', 'knowledge', 'foreshadow', 'timeline_mentions',
                    'timeline_orders'))
    digest = sha256(manuscript.encode('utf-8')).hexdigest()
    if (type(payload['version']) is not int or payload['version'] != 1
            or type(project_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', project_id)
            or type(episode) is not int or not 1 <= episode <= 1_000_000
            or payload['project_id'] != project_id or payload['episode'] != episode
            or payload['manuscript_sha256'] != digest):
        raise EvidenceManifestError('근거 파일이 현재 원고·회차와 일치하지 않습니다.')
    canon = []
    for item in _items(payload['canon']):
        _dict(item, ('source', 'entity_id', 'field', 'start', 'end', 'asserted_value'))
        a, b = _span(item, manuscript)
        if _text(item['asserted_value']) != manuscript[a:b]:
            raise EvidenceManifestError('설정 근거가 원고의 해당 부분과 다릅니다.')
        canon.append(ManuscriptClaim(_text(item['source'], 50),
                                     _text(item['entity_id'], 100),
                                     _text(item['field'], 60), a, b,
                                     item['asserted_value']))
    knowledge = []
    for item in _items(payload['knowledge']):
        _dict(item, ('character_id', 'fact_id', 'start', 'end', 'evidence'))
        a, b = _span(item, manuscript)
        if _text(item['evidence']) != manuscript[a:b]:
            raise EvidenceManifestError('인물 지식 근거가 원고와 다릅니다.')
        knowledge.append(KnowledgeUseClaim(
            _text(item['character_id'], 100), _text(item['fact_id'], 100),
            a, b, item['evidence']))
    foreshadow = []
    for item in _items(payload['foreshadow']):
        _dict(item, ('thread_id', 'start', 'end', 'evidence',
                     'claimed_action', 'claimed_status'))
        a, b = _span(item, manuscript)
        if _text(item['evidence']) != manuscript[a:b]:
            raise EvidenceManifestError('복선 근거가 원고와 다릅니다.')
        if (item['claimed_action'] is None) == (item['claimed_status'] is None):
            raise EvidenceManifestError('복선 행동 또는 상태를 하나만 지정해야 합니다.')
        foreshadow.append(ForeshadowClaim(
            _text(item['thread_id'], 100), a, b, item['evidence'],
            item['claimed_action'], item['claimed_status']))
    mentions = []
    for item in _items(payload['timeline_mentions']):
        _dict(item, ('event_id', 'start', 'end', 'evidence', 'claimed_when'))
        a, b = _span(item, manuscript)
        if _text(item['evidence']) != manuscript[a:b]:
            raise EvidenceManifestError('시간선 근거가 원고와 다릅니다.')
        if item['claimed_when'] is not None:
            _text(item['claimed_when'], 100)
        mentions.append(TimelineMention(
            _text(item['event_id'], 100), a, b,
            item['evidence'], item['claimed_when']))
    orders = []
    for item in _items(payload['timeline_orders']):
        _dict(item, ('before_event_id', 'after_event_id'))
        orders.append(TimelineOrderClaim(
            _text(item['before_event_id'], 100),
            _text(item['after_event_id'], 100)))
    return LoadedEvidenceManifest(project_id, episode, digest,
        EvidenceAnnotations(tuple(canon), tuple(knowledge), tuple(foreshadow),
                            tuple(mentions), tuple(orders)))
