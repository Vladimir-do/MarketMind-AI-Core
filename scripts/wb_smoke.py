"""Ручная диагностика доступности card.json Wildberries."""

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8", errors="backslashreplace")


async def smoke_wb_card_json(item_id: int = 311895731) -> bool:
    """Проверяет card.json по тем же корзинам и путям, что и основной парсер."""
    from app.parsers.wildberries import (
        _build_wb_headers,
        _extract_wb_id,
        _extract_wbbasket_prices,
        _wb_path_parts,
        _wbbasket_candidates,
    )

    nm_id = _extract_wb_id(str(item_id))
    if nm_id is None:
        raise ValueError("Артикул WB должен содержать от 6 до 12 цифр")

    vol, part = _wb_path_parts(nm_id)
    baskets = _wbbasket_candidates(nm_id)

    async with aiohttp.ClientSession(headers=_build_wb_headers()) as session:
        print(f"--- Проверка товара WB {nm_id} ---")
        print(f"Корзина по алгоритму парсера: {baskets[0]}; кандидатов: {len(baskets)}")

        for basket in baskets:
            url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/info/ru/card.json"
            print(f"Пробую корзину {basket}: {url}")
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        print(f"  HTTP {resp.status}")
                        continue
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                print(f"  Ошибка: {type(exc).__name__}: {exc}")
                continue

            if not isinstance(data, dict) or not (data.get("imt_name") or "").strip():
                print("  HTTP 200, но карточка не содержит названия товара")
                continue

            print(f"\nOK! Найдена карточка в корзине {basket}")
            print(f"Название: {data['imt_name']}")
            price, _old_price = _extract_wbbasket_prices(data.get("sizes"))
            print(f"Цена: {price if price is not None else 'нет в card.json'} руб.")
            return True

    print("FAIL: карточка не найдена ни в одной корзине из списка основного парсера.")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка card.json Wildberries")
    parser.add_argument("item_id", nargs="?", default="311895731", help="Артикул WB (6–12 цифр)")
    args = parser.parse_args(argv)
    try:
        return 0 if asyncio.run(smoke_wb_card_json(int(args.item_id))) else 1
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
