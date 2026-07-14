from __future__ import annotations

import time
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.universal_parsing_core.algorithms.confidence import calculate_confidence
from app.universal_parsing_core.algorithms.entity_blocker import extract_entity_blocks
from app.universal_parsing_core.algorithms.entity_classifier import classify_entity_type
from app.universal_parsing_core.algorithms.page_structure_detector import detect_page_structure_signals
from app.universal_parsing_core.algorithms.price_extractor import extract_price_candidates
from app.universal_parsing_core.algorithms.text_cleaner import clean_text
from app.universal_parsing_core.algorithms.title_extractor import match_title_near_price
from app.universal_parsing_core.algorithms.validator import validate_entities
from app.universal_parsing_core.parsers.base import BaseParser
from app.universal_parsing_core.schemas.normalized_entity import NormalizedEntity
from app.universal_parsing_core.schemas.page_structure import PageStructure
from app.universal_parsing_core.schemas.parse_context import ParseContext
from app.universal_parsing_core.schemas.parse_result import ParseResult
from app.universal_parsing_core.schemas.task_type import TaskType


class UniversalHtmlParser(BaseParser):
    @property
    def name(self) -> str:
        return "universal_html"

    def parse(self, context: ParseContext | str, html: str | None = None) -> ParseResult:
        if isinstance(context, str):
            context = ParseContext(url=context, html=html)

        start = time.perf_counter()
        warnings: list[str] = []
        errors: list[str] = []

        try:
            source_html = context.html
            if source_html is None:
                source_html = self._fetch_html(context)

            soup = BeautifulSoup(source_html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            page_title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
            h1_tag = soup.find("h1")
            h1_text = clean_text(h1_tag.get_text(" ", strip=True)) if h1_tag else ""
            body = clean_text(soup.body.get_text("\n", strip=True), preserve_newlines=True) if soup.body else ""

            prices = extract_price_candidates(body)
            page_structure, structure_signals = detect_page_structure_signals(source_html)
            blocks = extract_entity_blocks(body, prices)
            entities: list[NormalizedEntity] = []

            entities.extend(_extract_card_entities(soup, context.url))
            for block in blocks:
                matched_title = match_title_near_price(block)
                title = matched_title or h1_text or page_title or block.text[:80]
                title_is_price_only = not matched_title or _title_is_price_only(title, block.price.raw)
                entity_type = classify_entity_type(title, block.text)
                entities.append(
                    NormalizedEntity(
                        entity_type=entity_type,
                        title=title,
                        price=block.price.value,
                        description=block.text,
                        url=context.url,
                        source="html",
                        attributes={
                            "currency": block.price.currency,
                            "raw_price": block.price.raw,
                            "snippet": block.text,
                            "title_is_price_only": title_is_price_only,
                        },
                    )
                )

            entities, validation_warnings = validate_entities(entities)
            warnings.extend(validation_warnings)
            if any(entity.attributes.get("title_is_price_only") for entity in entities):
                warnings.append("Low confidence: price found without a reliable title")
            if _uses_ai_source(context, entities):
                warnings.append("Data was extracted or enriched by AI; verify before using")
            if not entities:
                warnings.append("no entities found")
            next_strategy = _next_strategy_for_result(page_structure, entities)

            execution_time_ms = int((time.perf_counter() - start) * 1000)
            confidence = calculate_confidence(
                entities,
                page_structure=page_structure,
                has_title=bool(page_title or h1_text),
                structure_signals=structure_signals,
            )
            return ParseResult(
                success=bool(entities) or page_structure not in {PageStructure.EMPTY, PageStructure.UNKNOWN, PageStructure.UNKNOWN_JS},
                task_type=self._task_type_for_structure(page_structure),
                page_structure=page_structure,
                entities=entities,
                source_url=context.url,
                parser_used=self.name,
                confidence=confidence,
                errors=errors,
                warnings=warnings,
                raw_snapshot={
                    "title": page_title,
                    "h1": h1_text,
                    "body_sample": body[:1000],
                    "prices_found": len(prices),
                    "entities_found": len(entities),
                    "page_structure_signals": structure_signals.__dict__,
                    "execution_time_ms": execution_time_ms,
                },
                parser_chain=context.parser_chain or [self.name],
                execution_time_ms=execution_time_ms,
                next_strategy=next_strategy,
            )

        except Exception as exc:
            execution_time_ms = int((time.perf_counter() - start) * 1000)
            return ParseResult(
                success=False,
                task_type=TaskType.UNIVERSAL_PAGE,
                page_structure=PageStructure.EMPTY,
                entities=[],
                source_url=context.url,
                parser_used=self.name,
                confidence=0.0,
                errors=[str(exc)],
                warnings=warnings,
                raw_snapshot={"execution_time_ms": execution_time_ms},
                parser_chain=context.parser_chain or [self.name],
                execution_time_ms=execution_time_ms,
                next_strategy="retry",
            )

    def _fetch_html(self, context: ParseContext) -> str:
        import httpx

        response = httpx.get(
            context.url,
            headers=context.headers or None,
            cookies=context.cookies or None,
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    def _task_type_for_structure(self, page_structure: PageStructure) -> TaskType:
        if page_structure is PageStructure.CATALOG:
            return TaskType.UNIVERSAL_CATALOG
        if page_structure is PageStructure.ARTICLE:
            return TaskType.UNIVERSAL_ARTICLE
        return TaskType.UNIVERSAL_PAGE


def _title_is_price_only(title: str, raw_price: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip().lower()
    if not normalized:
        return True
    raw = re.sub(r"\s+", " ", raw_price or "").strip().lower()
    if raw and normalized == raw:
        return True
    without_price = normalized
    if raw:
        without_price = without_price.replace(raw, "")
    without_price = re.sub(r"[\d\s.,]+", "", without_price)
    without_price = re.sub(r"(₽|руб\.?|р\.?|rub|usd|eur|gbp|£|€|\$)", "", without_price, flags=re.I)
    return not without_price.strip(" :-–—")


def _uses_ai_source(context: ParseContext, entities: list[NormalizedEntity]) -> bool:
    chain = {item.lower() for item in (context.parser_chain or [])}
    if any("ai" in item or "llm" in item or "gpt" in item or "claude" in item or "grok" in item for item in chain):
        return True
    payload = context.payload
    if isinstance(payload, dict):
        source = str(payload.get("source") or payload.get("parser_used") or "").lower()
        if "ai" in source or "llm" in source:
            return True
    return any((entity.source or "").lower() in {"ai", "llm"} for entity in entities)


def _next_strategy_for_result(page_structure: PageStructure, entities: list[NormalizedEntity]) -> str:
    if entities:
        return "continue"
    if page_structure in {PageStructure.EMPTY, PageStructure.UNKNOWN, PageStructure.UNKNOWN_JS}:
        return "browser"
    return "inspect_structure"


def _extract_card_entities(soup: BeautifulSoup, base_url: str) -> list[NormalizedEntity]:
    entities: list[NormalizedEntity] = []
    cards = soup.select("article.product_pod, [class*='product'][class*='card'], [class*='product'][class*='item']")
    for card in cards:
        link = card.select_one("h3 a[href], a[href]")
        title = clean_text(link.get_text(" ", strip=True)) if link else ""
        if not title:
            title_node = card.select_one("h3, h2, [class*='title'], [class*='name']")
            title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        card_text = clean_text(card.get_text("\n", strip=True), preserve_newlines=True)
        price_candidates = extract_price_candidates(card_text)
        if not title or not price_candidates:
            continue
        price = price_candidates[0]
        href = link.get("href") if link else ""
        detail_url = urljoin(base_url, href) if href else base_url
        entities.append(
            NormalizedEntity(
                entity_type=classify_entity_type(title, card_text),
                title=title,
                price=price.value,
                description=card_text,
                url=detail_url,
                source="html",
                attributes={
                    "currency": price.currency,
                    "raw_price": price.raw,
                    "snippet": card_text,
                    "title_is_price_only": False,
                    "url_source": "detail_link" if href else "page",
                },
            )
        )
    return entities
