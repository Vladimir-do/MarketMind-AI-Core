#!/usr/bin/env python3
"""
MarketMind MCP Server — парсинг товаров с маркетплейсов.

Запуск:
    python mcp_server.py

Конфигурация (.env):
    MARKETMIND_MCP_ENABLED=1
    MARKETMIND_MCP_COMMAND_JSON=["python","/path/to/mcp_server.py"]

Протокол: JSON-RPC 2.0 over stdin/stdout (MCP stdio transport).
"""

from __future__ import annotations

import json
import sys
from typing import Any


def fetch_product_sync(url: str, marketplace: str = "", task: str = "product_snapshot") -> dict[str, Any]:
    """Парсит товар по URL синхронно (в отдельном потоке)."""
    import asyncio

    async def _fetch() -> dict[str, Any]:
        from app.parsers.ozon import OzonParser
        from app.parsers.wildberries import WildberriesParser

        normalized = (url or "").strip()
        if not normalized:
            return {"error": "URL is required"}

        mp = (marketplace or "").strip().lower()
        parser = None

        if mp in ("wildberries", "wb") or "wildberries.ru" in normalized or "wb.ru" in normalized:
            parser = WildberriesParser()
        elif mp in ("ozon",) or "ozon.ru" in normalized:
            parser = OzonParser()
        else:
            if "wildberries.ru" in normalized or "wb.ru" in normalized:
                parser = WildberriesParser()
            elif "ozon.ru" in normalized:
                parser = OzonParser()
            else:
                parser = WildberriesParser()

        try:
            product = await parser.fetch_product(normalized)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

        if product is None:
            return {"error": "Product not found"}

        return {
            "name": product.name,
            "title": product.name,
            "price": product.price,
            "currentPrice": product.price,
            "old_price": product.old_price,
            "discount_pct": product.discount_pct,
            "availability": product.availability,
            "url": product.url or normalized,
            "image_url": product.image_url,
            "imageUrl": product.image_url,
            "brand": product.brand,
            "category": product.category,
            "marketplace": product.marketplace,
            "rating": product.rating,
            "reviews_count": product.reviews_count,
            "seller_name": product.seller_name,
        }

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_fetch())
    finally:
        loop.close()


TOOLS = [
    {
        "name": "fetch_product",
        "description": "Парсит товар с маркетплейса (Wildberries, Ozon) по URL. Возвращает название, цену, бренд, наличие и другие данные.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL товара на маркетплейсе",
                },
                "marketplace": {
                    "type": "string",
                    "description": "Маркетплейс: wildberries, ozon (auto-detect если пусто)",
                    "default": "",
                },
                "task": {
                    "type": "string",
                    "description": "Тип задачи (product_snapshot)",
                    "default": "product_snapshot",
                },
            },
            "required": ["url"],
        },
    }
]


def write_response(msg_id: Any, result: Any) -> None:
    """Пишет JSON-RPC ответ в stdout."""
    response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
    line = json.dumps(response, ensure_ascii=False) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def write_error(msg_id: Any, code: int, message: str) -> None:
    """Пишет JSON-RPC ошибку в stdout."""
    response = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
    line = json.dumps(response, ensure_ascii=False) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def handle_message(line: str) -> None:
    """Обрабатывает одно JSON-RPC сообщение."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return

    msg_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "marketmind-product-parser",
                "version": "1.0.0",
            },
        }
        write_response(msg_id, result)
        return

    if method in ("notifications/initialized", "notifications/cancelled"):
        return

    if method == "tools/list":
        write_response(msg_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name != "fetch_product":
            write_error(msg_id, -32601, f"Unknown tool: {tool_name}")
            return

        url = arguments.get("url", "")
        marketplace = arguments.get("marketplace", "")
        task = arguments.get("task", "product_snapshot")

        result = fetch_product_sync(url, marketplace=marketplace, task=task)

        if "error" in result:
            write_response(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": True,
                },
            )
        else:
            write_response(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "structuredContent": result,
                },
            )
        return

    if msg_id is not None:
        write_error(msg_id, -32601, f"Method not found: {method}")


def main() -> None:
    """Читает JSON-RPC сообщения из stdin."""
    for line in sys.stdin:
        stripped = line.strip()
        if stripped:
            handle_message(stripped)


if __name__ == "__main__":
    main()
