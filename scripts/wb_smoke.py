"""Smoke-check that Wildberries card.json is reachable for a given nm_id.

Usage:
    .venv/bin/python scripts/wb_smoke.py 311895731

Reuses the basket/path helpers from app.parsers.wildberries instead of keeping
a second, divergent copy of WB's basket ranges in this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import aiohttp

from app.parsers.wildberries import _wb_path_parts, _wbbasket_candidates

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

_TIMEOUT = aiohttp.ClientTimeout(total=5)


async def smoke_wb_card_json(nm_id: int) -> int:
    vol, part = _wb_path_parts(nm_id)
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        for basket in _wbbasket_candidates(nm_id):
            url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/info/ru/card.json"
            try:
                async with session.get(url, timeout=_TIMEOUT) as resp:
                    if resp.status != 200:
                        print(f"[{basket}] HTTP {resp.status}")
                        continue
                    data = await resp.json(content_type=None)
                    sizes = data.get("sizes") or []
                    price = None
                    if sizes:
                        total = (sizes[0].get("price") or {}).get("total")
                        if total:
                            price = total / 100
                    print(
                        json.dumps(
                            {
                                "basket": basket,
                                "url": url,
                                "name": data.get("imt_name"),
                                "price": price,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    return 0
            except (aiohttp.ClientError, TimeoutError) as exc:
                print(f"[{basket}] {type(exc).__name__}: {exc}")
    print(f"nm_id={nm_id}: card.json not found in any basket")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nm_id", type=int, help="Wildberries nm_id (article number)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    return asyncio.run(smoke_wb_card_json(args.nm_id))


if __name__ == "__main__":
    raise SystemExit(main())
