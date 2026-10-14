"""CI-local Redis, Celery and pgvector integration tests with synthetic data."""
from __future__ import annotations
import json
import os
from pathlib import Path
from uuid import uuid4
from ai_novel_factory.celery_local_adapter import configure_local_celery, validate_loopback_redis
from ai_novel_factory.scene_vectors import PGVECTOR_SCHEMA, pgvector_search

def main():
    if os.environ.get("ANF_CI_SYNTHETIC_SERVICES") != "1":
        raise RuntimeError("synthetic CI integration must be explicitly enabled")
    import psycopg
    import redis
    from celery.contrib.testing.worker import start_worker
    results = {"scope": "isolated_ephemeral_github_runner", "manuscript_used": False,
               "platform_upload_executed": False, "checks": {}}
    broker = validate_loopback_redis("redis://127.0.0.1:6379/0")
    client = redis.Redis.from_url(broker, socket_timeout=3)
    assert client.ping() is True
    key = "anf:synthetic:" + uuid4().hex
    assert client.set(key, "ok", ex=15)
    assert client.get(key) == b"ok"
    assert client.delete(key) == 1
    results["checks"]["redis_real_roundtrip"] = "PASS"

    app = configure_local_celery(broker_url=broker, explicitly_approved=True)
    app.conf.update(result_backend="redis://127.0.0.1:6379/1",
                    task_ignore_result=False, worker_prefetch_multiplier=1,
                    broker_connection_retry_on_startup=False)

    @app.task(name="anf_synthetic_ci.reverse", ignore_result=False)
    def reverse(value: str):
        return value[::-1]

    with start_worker(app, perform_ping_check=False, pool="solo",
                      concurrency=1, loglevel="WARNING"):
        result = reverse.apply_async(args=["synthetic-only"])
        assert result.get(timeout=20) == "ylno-citehtnys"
        result.forget()
    results["checks"]["celery_real_worker_redis_broker"] = "PASS"

    dsn = os.environ["ANF_CI_POSTGRES_DSN"]
    with psycopg.connect(dsn, connect_timeout=5) as con:
        with con.cursor() as cur:
            cur.execute(PGVECTOR_SCHEMA)
            cur.execute("TRUNCATE TABLE anf_scene_vectors")
            for project, episode, scene, summary, vector in [
                ("novel-A",1,1,"synthetic-a","[1,0,0]"),
                ("novel-A",2,1,"synthetic-b","[0.9,0.1,0]"),
                ("novel-B",1,1,"synthetic-c","[1,0,0]"),
                ("novel-A",5,1,"synthetic-future","[1,0,0]")
            ]:
                cur.execute("INSERT INTO anf_scene_vectors "
                            "(project_id,episode_number,scene_number,summary,embedding) "
                            "VALUES (%s,%s,%s,%s,%s::vector)",
                            (project,episode,scene,summary,vector))
        hits = pgvector_search(con, "novel-A", 3, (1.,0.,0.))
        assert [(x.episode_number,x.scene_number) for x in hits] == [(1,1),(2,1)]
        assert all(x.summary in ("synthetic-a","synthetic-b") for x in hits)
        assert pgvector_search(con, "novel-A' OR true --",3,(1.,0.,0.)) == ()
        assert pgvector_search(con, "novel-A",1,(1.,0.,0.)) == ()
    results["checks"]["postgres_pgvector_scoped_query"] = "PASS"
    out = Path("build/ci/local_services.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, sort_keys=True, indent=2)+"\n",encoding="utf-8")
    print(json.dumps(results, sort_keys=True))

if __name__ == "__main__":
    main()
