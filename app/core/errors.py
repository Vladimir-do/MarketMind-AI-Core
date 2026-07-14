from __future__ import annotations


class ScraperError(Exception):
    """Base domain error for scraping pipeline."""


class BlockedError(ScraperError):
    """Anti-bot/captcha/blocked response."""


class NotFoundError(ScraperError):
    """Product not found (404/deleted)."""


class ParseError(ScraperError):
    """HTML/JSON structure changed, extraction failed."""


class NetworkError(ScraperError):
    """Network/transport error."""

