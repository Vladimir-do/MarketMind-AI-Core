from __future__ import annotations

import base64
import html
from urllib.parse import urlparse

_PLACEHOLDER_IMAGE_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "example.test",
    "img.test",
}


def displayable_image_url(value: str | None) -> str | None:
    """Return a browser-usable image URL, ignoring demo/test placeholders."""
    url = (value or "").strip()
    if not url:
        return None

    if url.startswith("//"):
        return f"https:{url}"

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if (parsed.hostname or "").lower() in _PLACEHOLDER_IMAGE_HOSTS:
        return None
    return url


def product_image_src(name: str | None, value: str | None) -> str:
    """Return a usable image source, falling back to a deterministic inline SVG."""
    displayable = displayable_image_url(value)
    if displayable:
        return displayable

    label = (name or "").strip() or "Товар"
    initials = "".join(part[0] for part in label.split()[:2]).upper() or "Т"
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320" role="img" aria-label="{html.escape(label)}">
      <rect width="320" height="320" rx="24" fill="#f3f4f6"/>
      <rect x="24" y="24" width="272" height="272" rx="20" fill="#e5eefb" stroke="#cbd5e1"/>
      <circle cx="160" cy="126" r="58" fill="#bfd3ff"/>
      <rect x="92" y="194" width="136" height="76" rx="22" fill="#94a3b8"/>
      <text x="160" y="140" text-anchor="middle" font-family="Arial, sans-serif" font-size="56" font-weight="700" fill="#1e293b">{html.escape(initials)}</text>
      <text x="160" y="242" text-anchor="middle" font-family="Arial, sans-serif" font-size="20" fill="#ffffff">Нет фото</text>
    </svg>
    """.strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
