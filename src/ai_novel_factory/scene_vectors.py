"""Stage 56: project-isolated historical scene vector retrieval.

Vectors must come from a locally supplied embedder. No network or AI calls.
PostgreSQL pgvector is an optional backend; this module never opens connections.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, sqrt
from .planning import PlanningError

@dataclass(frozen=True)
class SceneVector:
    project_id: str
    episode_number: int
    scene_number: int
    vector: tuple[float, ...]
    summary: str

@dataclass(frozen=True)
class SceneHit:
    episode_number: int
    scene_number: int
    summary: str
    similarity: float

def _vector(value, dimension):
    if not isinstance(value, (tuple, list)) or len(value) != dimension or any(type(x) not in (float, int) or not isfinite(x) for x in value):
        raise PlanningError('벡터 차원 또는 숫자 형식이 올바르지 않습니다.')
    norm = sqrt(sum(x*x for x in value))
    if not isfinite(norm) or norm == 0:
        raise PlanningError('영벡터 또는 비정상 벡터는 검색할 수 없습니다.')
    return tuple(float(x)/norm for x in value)

def search_scenes(project_id: str, current_episode: int, query: tuple[float, ...], scenes: tuple[SceneVector, ...], *, limit: int = 5, dimension: int = 3) -> tuple[SceneHit, ...]:
    """Offline exact cosine baseline; excludes current/future episodes and other projects."""
    _check(project_id, current_episode, limit, dimension)
    q = _vector(query, dimension)
    if not isinstance(scenes, tuple):
        raise PlanningError('장면 자료는 튜플이어야 합니다.')
    hits = []
    seen = set()
    for s in scenes:
        if not isinstance(s, SceneVector) or not isinstance(s.project_id, str) or not s.project_id.strip() or type(s.episode_number) is not int or s.episode_number < 1 or type(s.scene_number) is not int or s.scene_number < 1 or not isinstance(s.summary, str) or not s.summary.strip() or len(s.summary) > 4000:
            raise PlanningError('장면 기록 형식이 올바르지 않습니다.')
        v = _vector(s.vector, dimension)
        key = (s.project_id, s.episode_number, s.scene_number)
        if key in seen:
            raise PlanningError('중복 장면이 있습니다.')
        seen.add(key)
        if s.project_id == project_id and s.episode_number < current_episode:
            hits.append(SceneHit(s.episode_number, s.scene_number, s.summary, max(-1.0, min(1.0, sum(a*b for a,b in zip(q,v))))))
    hits.sort(key=lambda h: (-h.similarity, h.episode_number, h.scene_number))
    return tuple(hits[:limit])

def _check(project_id, current_episode, limit, dimension):
    if not isinstance(project_id, str) or not project_id.strip() or type(current_episode) is not int or current_episode < 1 or type(limit) is not int or not 1 <= limit <= 100 or type(dimension) is not int or not 1 <= dimension <= 4096:
        raise PlanningError('검색 매개변수가 올바르지 않습니다.')

PGVECTOR_SCHEMA = """CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS anf_scene_vectors (
 project_id TEXT NOT NULL,
 episode_number INTEGER NOT NULL CHECK (episode_number > 0),
 scene_number INTEGER NOT NULL CHECK (scene_number > 0),
 summary TEXT NOT NULL,
 embedding vector(3) NOT NULL,
 PRIMARY KEY (project_id, episode_number, scene_number)
);"""

def pgvector_search(connection, project_id: str, current_episode: int, query: tuple[float, ...], *, limit: int = 5) -> tuple[SceneHit, ...]:
    """Parameterized pgvector cosine query; caller owns local PostgreSQL connection.

    Schema example is fixed to 3 dimensions. Production requires an explicitly
    migrated schema matching the chosen local embedding model's dimensions.
    """
    _check(project_id, current_episode, limit, 3)
    q = _vector(query, 3)
    literal = '[' + ','.join(format(x, '.17g') for x in q) + ']'
    sql = """SELECT episode_number, scene_number, summary,
 1 - (embedding <=> %s::vector) AS similarity
 FROM anf_scene_vectors
 WHERE project_id = %s AND episode_number < %s
 ORDER BY embedding <=> %s::vector, episode_number, scene_number
 LIMIT %s"""
    with connection.cursor() as cursor:
        cursor.execute(sql, (literal, project_id, current_episode, literal, limit))
        rows = cursor.fetchall()
    results = []
    for ep, scene, summary, score in rows:
        if type(ep) is not int or type(scene) is not int or ep < 1 or ep >= current_episode or scene < 1 or not isinstance(summary, str) or type(score) not in (int,float) or not isfinite(score):
            raise PlanningError('검색 결과 무결성 오류')
        results.append(SceneHit(ep, scene, summary, float(score)))
    return tuple(results)
