"""No-account, no-network contract tests for optional WordPress DRAFT adapter."""
from __future__ import annotations

import base64
import json
import unittest
from urllib.parse import urlsplit

from ai_novel_factory.wordpress_draft_api import (
    WordPressDraftError, checked_wordpress_url, post_private_draft,
)


class WordPressDraftContract(unittest.TestCase):
    def test_requires_explicit_per_request_permission(self):
        with self.assertRaises(WordPressDraftError):
            post_private_draft(
                'https://novel.example.com', 'author', 'dummy test application secret',
                title='Fictional novel', approved_final_text='Entirely invented paragraph.')

    def test_no_http_redirect_auth_injection_or_private_origin(self):
        for site in ('http://example.com', 'https://127.0.0.1',
                     'https://localhost', 'https://example.com@evil.com',
                     'https://example.com:4444',
                     'https://example.com/other', 'https://example.com?a=secret'):
            with self.subTest(site=site):
                with self.assertRaises(WordPressDraftError):
                    checked_wordpress_url(site)

    def test_no_remote_access_using_local_transport(self):
        intercepted = []
        def fake_transport(request):
            intercepted.append(request)
            return 201, b'{"id": 37, "status": "draft"}'
        receipt = post_private_draft(
            'https://novel.example.com', 'author', 'test dummy application password',
            title='Original', approved_final_text='A & B < C',
            explicitly_authorized=True, transport=fake_transport)
        self.assertTrue(receipt.remote_draft_created)
        self.assertFalse(receipt.public_publishing_performed)
        self.assertEqual(receipt.status, 'draft')
        request = intercepted[0]
        self.assertEqual(request.full_url,
                         'https://novel.example.com/wp-json/wp/v2/posts')
        payload = json.loads(request.data)
        self.assertEqual(payload['status'], 'draft')
        self.assertIn('&amp;', payload['content'])
        self.assertIn('&lt;', payload['content'])
        self.assertEqual(request.get_method(), 'POST')
        encoded = request.get_header('Authorization')
        self.assertTrue(encoded.startswith('Basic '))
        self.assertIn('author:', base64.b64decode(encoded[6:]).decode())

    def test_server_must_verify_non_public_draft(self):
        for status, data in ((201, b'{"id":37,"status":"publish"}'),
                             (200, b'{"id":37,"status":"draft"}'),
                             (201, b'{"id":0,"status":"draft"}')):
            with self.subTest(status=status, data=data):
                with self.assertRaises(WordPressDraftError):
                    post_private_draft(
                        'https://novel.example.com', 'author', 'dummy test application secret',
                        title='Original', approved_final_text='Entirely invented prose',
                        explicitly_authorized=True,
                        transport=lambda request: (status, data))


if __name__ == '__main__':
    unittest.main()
