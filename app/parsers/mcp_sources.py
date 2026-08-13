"""
mcp_sources.py - optional MCP-backed product data source.

This module is opt-in via environment variables. It lets MarketMind call an
external MCP stdio server for marketplace product snapshots without making MCP
a hard runtime dependency for the normal parser pipeline.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from typing import Any

from app.config import logger

_ALLOWED_AVAILABILITY = {"in_stock", "out_of_stock", "deleted", "blocked", "unknown"}


def _env_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


def _mcp_command_from_env() -> list[str]:
    raw_json = os.getenv("MARKETMIND_MCP_COMMAND_JSON", "").strip()
    if raw_json:
        try:
            command = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("MARKETMIND_MCP_COMMAND_JSON is not valid JSON")
            return []
        if isinstance(command, list) and all(isinstance(part, str) and part for part in command):
            return command
        logger.warning("MARKETMIND_MCP_COMMAND_JSON must be a non-empty JSON string array")
        return []

    raw = os.getenv("MARKETMIND_MCP_COMMAND", "").strip()
    if not raw:
        return []
    return shlex.split(raw, posix=os.name != "nt")


def _parse_price(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        price = int(value)
        return price if 10 < price < 10_000_000 else None
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if digits:
            price = int(digits)
            return price if 10 < price < 10_000_000 else None
    return None


def _extract_payload(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured

        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str):
                    continue
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        if any(key in result for key in ("name", "title", "price", "image_url", "imageUrl")):
            return result
    return None


def normalize_mcp_product_payload(payload: dict[str, Any], url: str) -> dict | None:
    name = payload.get("name") or payload.get("title") or payload.get("productName")
    name = str(name).strip() if name is not None else ""
    if len(name) < 3:
        return None

    price = _parse_price(payload.get("price") or payload.get("currentPrice") or payload.get("finalPrice"))
    image_url = payload.get("image_url") or payload.get("imageUrl") or payload.get("image")
    if image_url is not None:
        image_url = str(image_url).strip() or None

    availability = str(payload.get("availability") or "unknown").strip().lower()
    if availability not in _ALLOWED_AVAILABILITY:
        availability = "unknown"

    return {
        "url": url,
        "name": name[:220],
        "price": price,
        "availability": availability,
        "brand": payload.get("brand"),
        "image_url": image_url,
        "source": "mcp",
    }


class McpStdioClient:
    def __init__(self, command: list[str], timeout: float):
        self.command = command
        self.timeout = timeout
        self._next_id = 1
        self._process: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> McpStdioClient:
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return self

    async def __aexit__(self, *args) -> None:
        process = self._process
        self._process = None
        if not process:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError("MCP process is not running")

        request_id = self._next_id
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        self._process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._process.stdin.drain()

        while True:
            raw = await asyncio.wait_for(self._process.stdout.readline(), timeout=self.timeout)
            if not raw:
                raise RuntimeError("MCP server closed stdout")
            try:
                response = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if response.get("id") != request_id:
                continue
            if response.get("error"):
                err = response["error"]
                message = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"MCP {method} failed: {message}")
            return response.get("result")

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("MCP process is not running")
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self._process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._process.stdin.drain()


async def fetch_product_via_mcp(url: str, *, marketplace: str = "ozon") -> dict | None:
    if not _env_bool("MARKETMIND_MCP_ENABLED"):
        return None

    command = _mcp_command_from_env()
    if not command:
        logger.warning("MCP product source enabled but command is not configured")
        return None

    tool_name = os.getenv("MARKETMIND_MCP_PRODUCT_TOOL", "fetch_product").strip() or "fetch_product"
    protocol_version = os.getenv("MARKETMIND_MCP_PROTOCOL_VERSION", "2025-06-18").strip()
    timeout = float(os.getenv("MARKETMIND_MCP_TIMEOUT", "20"))

    try:
        async with McpStdioClient(command, timeout=timeout) as client:
            await client.request(
                "initialize",
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "marketmind-ai-core", "version": "0.1"},
                },
            )
            await client.notify("notifications/initialized")
            result = await client.request(
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": {
                        "url": url,
                        "marketplace": marketplace,
                        "task": "product_snapshot",
                    },
                },
            )
    except Exception as exc:
        logger.warning(f"MCP product source failed: {type(exc).__name__}: {exc}")
        return None

    payload = _extract_payload(result)
    if not payload:
        return None
    return normalize_mcp_product_payload(payload, url)
