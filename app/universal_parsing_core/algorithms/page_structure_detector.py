from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.universal_parsing_core.algorithms.price_extractor import extract_price_candidates
from app.universal_parsing_core.algorithms.text_cleaner import clean_text
from app.universal_parsing_core.schemas.page_structure import PageStructure


_CARD_CLASS_RE = re.compile(r"(?:^|[-_\s])(product|card|item)(?:$|[-_\s])", re.I)
_DETAIL_LINK_RE = re.compile(r"(?:/product/|/item/|/detail|/catalogue/.+?_\d+/|_\d+/index\.html)", re.I)
_PAGINATION_CLASS_RE = re.compile(r"(pagination|pager|next)", re.I)
_AUTHOR_CLASS_RE = re.compile(r"(author|byline)", re.I)


@dataclass(frozen=True)
class PageStructureSignals:
    text_length: int
    price_count: int
    link_count: int
    h1_count: int
    product_pod_count: int
    card_like_count: int
    detail_link_count: int
    has_pagination: bool
    has_article_marker: bool
    has_time_marker: bool
    has_author_marker: bool


def detect_page_structure(html: str | None) -> PageStructure:
    return detect_page_structure_signals(html)[0]


def detect_page_structure_signals(html: str | None) -> tuple[PageStructure, PageStructureSignals]:
    source_html = html or ""
    if not source_html.strip():
        return PageStructure.EMPTY, _empty_signals()

    soup = BeautifulSoup(source_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body = soup.body or soup
    body_text = clean_text(body.get_text(" ", strip=True))
    prices = extract_price_candidates(body_text)
    links = [link.get("href", "") for link in body.find_all("a", href=True)]
    product_pods = body.select("article.product_pod")
    card_like_elements = [
        tag
        for tag in body.find_all(True)
        if _has_matching_class(tag.get("class"), _CARD_CLASS_RE)
    ]
    detail_links = [href for href in links if _DETAIL_LINK_RE.search(href)]
    has_pagination = bool(
        body.select('[rel="next"], a.next, li.next')
        or body.find_all(class_=_PAGINATION_CLASS_RE)
        or any("next" in link.lower() for link in links)
    )
    has_article_marker = bool(body.find("article"))
    has_time_marker = bool(body.find("time"))
    has_author_marker = bool(
        body.find(attrs={"rel": "author"})
        or body.find(attrs={"name": "author"})
        or body.find(class_=_AUTHOR_CLASS_RE)
    )

    signals = PageStructureSignals(
        text_length=len(body_text),
        price_count=len(prices),
        link_count=len(links),
        h1_count=len(body.find_all("h1")),
        product_pod_count=len(product_pods),
        card_like_count=len(card_like_elements),
        detail_link_count=len(detail_links),
        has_pagination=has_pagination,
        has_article_marker=has_article_marker,
        has_time_marker=has_time_marker,
        has_author_marker=has_author_marker,
    )

    if signals.text_length < 20 and not _has_listing_structure(signals):
        return PageStructure.EMPTY, signals

    catalog_score = 0
    if signals.product_pod_count >= 2:
        catalog_score += 3
    if signals.card_like_count >= 3:
        catalog_score += 1
    if signals.detail_link_count >= 3:
        catalog_score += 1
    if signals.price_count >= 2:
        catalog_score += 1
    if signals.has_pagination:
        catalog_score += 1
    if catalog_score >= 2:
        return PageStructure.CATALOG, signals

    if signals.h1_count == 1 and signals.price_count == 1 and signals.link_count <= 10:
        return PageStructure.SINGLE, signals

    article_score = 0
    if signals.text_length >= 500:
        article_score += 1
    if signals.has_article_marker:
        article_score += 1
    if signals.has_time_marker:
        article_score += 1
    if signals.has_author_marker:
        article_score += 1
    if article_score >= 2:
        return PageStructure.ARTICLE, signals

    return PageStructure.UNKNOWN_JS, signals


def _has_listing_structure(signals: PageStructureSignals) -> bool:
    return (
        signals.product_pod_count > 0
        or signals.card_like_count >= 2
        or signals.detail_link_count >= 2
        or signals.price_count >= 2
        or signals.has_pagination
    )


def _has_matching_class(classes: object, pattern: re.Pattern[str]) -> bool:
    if not classes:
        return False
    if isinstance(classes, str):
        class_names = classes.split()
    else:
        class_names = [str(item) for item in classes]
    return any(pattern.search(class_name) for class_name in class_names)


def _empty_signals() -> PageStructureSignals:
    return PageStructureSignals(
        text_length=0,
        price_count=0,
        link_count=0,
        h1_count=0,
        product_pod_count=0,
        card_like_count=0,
        detail_link_count=0,
        has_pagination=False,
        has_article_marker=False,
        has_time_marker=False,
        has_author_marker=False,
    )
