"""External-only LLM API boundaries; no real cloud or local inference calls."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import Mock, patch

from urllib3.exceptions import NewConnectionError

from patent_sar_extractor.integrations.llm.external_api import (
    PublicHTTPSConnection,
    validate_external_endpoint,
)


class ExternalAPITests(unittest.TestCase):
    def test_https_external_urls_only(self):
        for value in (
            "http://api.example.org/v1",
            "https://localhost/v1",
            "https://host.local/v1",
            "https://127.0.0.1/v1",
            "https://10.0.0.1/v1",
            "https://[::1]/v1",
            "https://[::ffff:127.0.0.1]/v1",
            "https://169.254.169.254/v1",
            "https://user:key@api.example.org/v1",
            "https://api.example.org:11434/v1",
            "https://api.example.org/v1?key=secret",
            "https://api.example.org/v1#secret",
            "https://api.example.org/../private",
            "https://api.example.org/%2e%2e/x",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_external_endpoint(value)
        self.assertEqual(
            validate_external_endpoint("https://API.example.org/v1/"),
            "https://api.example.org/v1",
        )

    def test_mixed_private_dns_fails_before_socket(self):
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ("1.1.1.1", "127.0.0.1")
        ]
        with (
            patch("socket.getaddrinfo", return_value=addresses),
            patch("socket.socket") as sock,
        ):
            with self.assertRaises(NewConnectionError):
                PublicHTTPSConnection("api.example.org")._new_conn()
        sock.assert_not_called()

    def test_connection_uses_exact_checked_address_without_second_dns(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))]
        connection = Mock()
        with (
            patch("socket.getaddrinfo", return_value=addresses) as dns,
            patch("socket.socket", return_value=connection),
        ):
            self.assertIs(
                PublicHTTPSConnection("api.example.org", timeout=1)._new_conn(),
                connection,
            )
        self.assertEqual(dns.call_count, 1)
        connection.connect.assert_called_once_with(("1.1.1.1", 443))
