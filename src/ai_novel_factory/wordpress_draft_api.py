"""Opt-in official WordPress REST API *draft* publishing adapter.

WordPress supports POST /wp/v2/posts with status=draft and HTTPS
Application Password authentication. No user credentials persist or appear in
logs. This makes a remote private DRAFT, NOT publication, not Korean webnovel
platform support, and not user/account acceptance testing.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
import ipaddress
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    Request, build_opener, HTTPSHandler, HTTPRedirectHandler,
)


class WordPressDraftError(ValueError):
    """Never includes network addresses, manuscripts or credentials."""


@dataclass(frozen=True)
class WordPressDraftReceipt:
    post_id: int
    status: str
    origin_host: str
    remote_draft_created: bool
    public_publishing_performed: bool = False


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WordPressDraftError('리디렉션이 차단되었습니다. 대상 서버를 확인하세요.')


def checked_wordpress_url(raw: str) -> tuple[str, str]:
    if type(raw) is not str or not 12 <= len(raw) <= 220 or any(
            c.isspace() or ord(c) < 32 for c in raw):
        raise WordPressDraftError('워드프레스 HTTPS 주소 형식이 올바르지 않습니다.')
    parsed = urlsplit(raw)
    if parsed.scheme != 'https' or not parsed.hostname or (
            parsed.port is not None and parsed.port != 443
    ) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WordPressDraftError('표준 HTTPS 사이트 주소만 사용할 수 있습니다.')
    if parsed.path not in ('', '/'):
        raise WordPressDraftError('사이트 루트 주소만 입력하세요.')
    host = parsed.hostname.strip('.').lower()
    if (not re.fullmatch(r'[a-z0-9.-]{4,200}', host)
            or host.endswith(('.local', '.internal', '.test', '.localhost'))
            or '.' not in host):
        raise WordPressDraftError('공개 HTTPS 호스트 이름이 필요합니다.')
    try:
        ipaddress.ip_address(host)
        raise WordPressDraftError('IP 주소 직접 접속은 허용하지 않습니다.')
    except ValueError as exc:
        if isinstance(exc, WordPressDraftError):
            raise
    return f'https://{host}/wp-json/wp/v2/posts', host


def post_private_draft(
    site_url: str, username: str, app_password: str, *,
    title: str, approved_final_text: str,
    explicitly_authorized: bool = False,
    transport=None,
) -> WordPressDraftReceipt:
    """Sends a single draft. Call only after the user explicitly confirms.

    Test transport injection lets CI inspect the request without any Internet
    connection, while production uses a TLS-verifying non-redirecting opener.
    Actual transport is NOT exercised without a user-owned WordPress site.
    """
    if explicitly_authorized is not True:
        raise WordPressDraftError('이 업로드를 사용자에게 직접 승인받아야 합니다.')
    endpoint, host = checked_wordpress_url(site_url)
    if not (type(username) is str and 1 <= len(username) <= 100
            and type(app_password) is str and 10 <= len(app_password) <= 300
            and type(title) is str and 1 <= len(title.strip()) <= 180
            and type(approved_final_text) is str
            and 1 <= len(approved_final_text.strip()) <= 500_000):
        raise WordPressDraftError('계정·제목·최종 원고가 올바르지 않습니다.')
    body = json.dumps(
        {'status': 'draft', 'title': title,
         'content': '<p>' + escape(approved_final_text).replace('\n', '</p><p>') + '</p>',
         'comment_status': 'closed', 'ping_status': 'closed'},
        ensure_ascii=False).encode('utf-8')
    token = base64.b64encode((username + ':' + app_password).encode('utf-8')).decode('ascii')
    request = Request(endpoint, data=body,
                      headers={'Authorization': 'Basic ' + token,
                               'Content-Type': 'application/json; charset=utf-8',
                               'Accept': 'application/json'},
                      method='POST')
    try:
        if transport is None:
            opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
            with opener.open(request, timeout=15) as response:
                code = response.status
                data = response.read(65000)
        else:
            code, data = transport(request)
        if code != 201:
            raise WordPressDraftError('원격 초고 작성 상태를 확인하지 못했습니다.')
        result = json.loads(data)
        if (type(result) is not dict or type(result.get('id')) is not int
                or result['id'] <= 0 or result.get('status') != 'draft'):
            raise WordPressDraftError('원격 서버에서 비공개 초고를 확인하지 못했습니다.')
        return WordPressDraftReceipt(
            result['id'], 'draft', host, remote_draft_created=True)
    except (OSError, ValueError, HTTPError, URLError) as exc:
        if type(exc) is WordPressDraftError:
            raise
        raise WordPressDraftError('워드프레스 연결·인증·응답 검증에 실패했습니다.') from None
