"""Disposable live PostgreSQL/pgvector + Redis/Celery integration contract.

Executed only by explicitly invoked CI against loopback service containers.
This is actual SQL, vector index retrieval and broker-to-worker delivery, NOT
mock/stub tests, and NOT an assertion that a Windows user's PC has services.
Only synthetic IDs and task metadata cross the broker; manuscripts never do.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from urllib.parse import urlsplit

from .celery_local_adapter import configure_local_celery, validate_loopback_redis
from .scene_vectors import pgvector_search

BROKER = 'redis://127.0.0.1:6379/0'
BACKEND = 'redis://127.0.0.1:6379/1'
app = configure_local_celery(broker_url=BROKER, explicitly_approved=True)
app.conf.result_backend = BACKEND
app.conf.task_default_queue = 'anf_ci'


@app.task(name='anf.test_metadata_roundtrip')
def metadata_roundtrip(project_id: str, episode: int):
    if (not isinstance(project_id, str) or len(project_id) != 32
            or type(episode) is not int or not 1 <= episode <= 1000):
        raise ValueError('invalid synthetic task metadata')
    return {'project_id': project_id, 'episode': episode, 'source': 'real_redis_celery'}


def require_local_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if (parts.scheme not in ('postgresql', 'postgres')
            or parts.hostname not in ('127.0.0.1', '::1')
            or parts.port != 5432
            or not parts.username or not parts.password
            or parts.path != '/anfci' or parts.query or parts.fragment):
        raise ValueError('disposable CI postgres loopback DSN required')
    return dsn


def main() -> int:
    if os.environ.get('ANF_DISPOSABLE_SERVICE_CI') != '1':
        raise RuntimeError('This live service test is allowed only in disposable CI')
    dsn = require_local_dsn(os.environ['ANF_CI_POSTGRES_DSN'])
    validate_loopback_redis(BROKER)
    import psycopg
    import redis
    with psycopg.connect(dsn, connect_timeout=12) as connection:
        with connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')
            cursor.execute("""CREATE TABLE IF NOT EXISTS anf_scene_vectors (
                project_id TEXT NOT NULL,
                episode_number INTEGER NOT NULL CHECK (episode_number > 0),
                scene_number INTEGER NOT NULL CHECK (scene_number > 0),
                summary TEXT NOT NULL,
                embedding vector(3) NOT NULL,
                PRIMARY KEY(project_id,episode_number,scene_number)
            )""")
            pid = uuid4().hex
            other = uuid4().hex
            cursor.execute("""INSERT INTO anf_scene_vectors
                (project_id, episode_number, scene_number, summary, embedding)
                VALUES (%s,%s,%s,%s,%s::vector)""",
                (pid, 1, 1, 'Synthetic previous chapter', '[1,0,0]'))
            cursor.execute("""INSERT INTO anf_scene_vectors
                (project_id, episode_number, scene_number, summary, embedding)
                VALUES (%s,%s,%s,%s,%s::vector)""",
                (other, 1, 1, 'Synthetic other novel', '[1,0,0]'))
        hits = pgvector_search(connection, pid, 2, (1.0, 0.0, 0.0), limit=3)
        if (len(hits) != 1 or hits[0].episode_number != 1
                or hits[0].summary != 'Synthetic previous chapter'
                or hits[0].similarity < 0.95):
            raise AssertionError('actual pgvector project-isolated retrieval failed')

    redis_client = redis.Redis.from_url(BROKER, socket_timeout=8)
    if not redis_client.ping():
        raise AssertionError('real Redis ping failed')
    worker = subprocess.Popen(
        [sys.executable, '-m', 'celery',
         '-A', 'ai_novel_factory.service_integration_ci:app',
         'worker', '--pool=solo', '--concurrency=1', '--loglevel=WARNING',
         '--queues=anf_ci', '--without-gossip', '--without-mingle',
         '--without-heartbeat'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, 'PYTHONUNBUFFERED':'1'})
    try:
        request = app.send_task(
            'anf.test_metadata_roundtrip', args=[pid, 1], queue='anf_ci')
        result = request.get(timeout=90, propagate=True)
        if result != {'project_id': pid, 'episode': 1,
                      'source': 'real_redis_celery'}:
            raise AssertionError('real Redis/Celery worker result mismatch')
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=12)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=8)

    report = {
        'mode': 'REAL_DISPOSABLE_CONTAINERS_NO_MANUSCRIPTS',
        'postgreSQL_connect': 'PASS',
        'pgvector_extension_and_insert': 'PASS',
        'pgvector_project_filtered_cosine_query': 'PASS',
        'redis_ping': 'PASS',
        'celery_worker_consumed_real_broker_message': 'PASS',
        'celery_result_backend_roundtrip': 'PASS',
        'project_id_redacted': True, 'user_credentials_used': False,
        'Windows_local_installation_or_service_autostart_verified': False,
        'quality_or_release_approved': False,
    }
    output = Path('build/ci/services_live.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
