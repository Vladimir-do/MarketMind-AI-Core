"""Security regression tests for product image URL fetching."""

from __future__ import annotations

from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

from app.importers.image_fetcher import (
    _is_safe_public_http_url,
    _normalize_url,
    _SafeRedirectHandler,
    resolve_image_url_from_source,
)


def _public_dns(*args, **kwargs):
    return [(None, None, None, None, ("93.184.216.34", 0))]


def _private_dns(*args, **kwargs):
    return [(None, None, None, None, ("192.168.1.10", 0))]


def test_rejects_loopback_and_private_ip_literals():
    for url in (
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
    ):
        assert not _is_safe_public_http_url(url)


def test_rejects_hostnames_resolving_to_private_addresses():
    with patch("app.importers.image_fetcher.socket.getaddrinfo", side_effect=_private_dns):
        assert not _is_safe_public_http_url("https://internal.example/product")


def test_accepts_public_host_when_all_dns_answers_are_public():
    with patch("app.importers.image_fetcher.socket.getaddrinfo", side_effect=_public_dns):
        assert _is_safe_public_http_url("https://shop.example/product")


def test_rejects_non_http_credentials_and_malformed_urls():
    for url in (
        "file:///etc/passwd",
        "ftp://example.com/file",
        "https://user:password@example.com/item",
        "https://example.com:99999/item",
        "https://example.com/item with spaces",
    ):
        assert not _is_safe_public_http_url(url)


def test_relative_image_url_is_normalized_and_checked():
    with patch("app.importers.image_fetcher.socket.getaddrinfo", side_effect=_public_dns):
        assert _normalize_url("/images/item.jpg", base_url="https://shop.example/product/1") == (
            "https://shop.example/images/item.jpg"
        )


def test_relative_image_url_cannot_escape_to_private_host():
    with patch("app.importers.image_fetcher.socket.getaddrinfo", side_effect=_private_dns):
        assert _normalize_url("//internal.example/image.jpg", base_url="https://shop.example/product/1") is None


def test_redirect_handler_rejects_private_network_target():
    handler = _SafeRedirectHandler()
    with patch("app.importers.image_fetcher.socket.getaddrinfo", side_effect=_private_dns):
        try:
            handler.redirect_request(
                req=Request("https://shop.example/product"),
                fp=None,
                code=302,
                msg="Found",
                headers={},
                newurl="http://internal.example/admin",
            )
        except URLError as exc:
            assert "not a public" in str(exc)
        else:
            raise AssertionError("Private-network redirect must be rejected")


def test_private_source_url_is_rejected_before_fetch():
    with patch("app.importers.image_fetcher.build_opener") as build_opener:
        assert resolve_image_url_from_source("http://127.0.0.1/admin") is None
        build_opener.assert_not_called()
