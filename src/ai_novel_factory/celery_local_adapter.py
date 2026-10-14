"""Stage 67 optional Redis/Celery *configuration*, never an implicit connection.

Live Redis and Celery worker transport is intentionally unverified until a
user provisions a local loopback-only service and approves starting it.
"""
from __future__ import annotations

from urllib.parse import urlsplit


class LocalBrokerError(ValueError):
    pass


def validate_loopback_redis(url: str) -> str:
    """Only literal loopback Redis URLs; no usernames/passwords or remote names."""
    if type(url) is not str or len(url) > 150 or any(c.isspace() for c in url):
        raise LocalBrokerError('invalid local redis configuration')
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise LocalBrokerError('invalid local redis configuration') from exc
    if (parts.scheme != 'redis' or parts.hostname not in ('127.0.0.1', '::1')
            or parts.username is not None or parts.password is not None
            or port is None or not 1 <= port <= 65535
            or parts.path not in ('/0', '/1') or parts.query or parts.fragment):
        raise LocalBrokerError('only loopback redis with no credentials is allowed')
    return url


def configure_local_celery(*, broker_url: str = 'redis://127.0.0.1:6379/0',
                           explicitly_approved: bool = False):
    """Return a configured Celery app; NEVER connects or sends jobs.

    An actual Celery worker/Redis integration requires later explicit execution
    and tests. Import is optional; no cloud endpoints can be configured here.
    """
    if type(explicitly_approved) is not bool or not explicitly_approved:
        raise LocalBrokerError('local broker configuration requires explicit approval')
    validate_loopback_redis(broker_url)
    try:
        from celery import Celery
    except ImportError as exc:
        raise LocalBrokerError('optional celery package is not installed') from exc
    app = Celery('ai_novel_factory_local', broker=broker_url, backend=None)
    app.conf.update(task_serializer='json', accept_content=['json'], result_serializer='json',
                    task_ignore_result=True, task_always_eager=False,
                    broker_connection_retry_on_startup=False)
    return app
