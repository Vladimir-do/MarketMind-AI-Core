import asyncio
import aiohttp
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

async def smoke_wb_card_json():
    item_id = "311895731"
    
    # Расширенный список корзин на 2026 год
    # WB добавил много новых диапазонов
    def get_basket_extended(mid):
        mid = int(mid)
        if 0 <= mid <= 143999: return "01"
        if 144000 <= mid <= 287999: return "02"
        if 288000 <= mid <= 431999: return "03"
        if 432000 <= mid <= 719999: return "04"
        if 720000 <= mid <= 1007999: return "05"
        if 1008000 <= mid <= 1061999: return "06"
        if 1062000 <= mid <= 1115999: return "07"
        if 1116000 <= mid <= 1169999: return "08"
        if 1170000 <= mid <= 1313999: return "09"
        if 1314000 <= mid <= 1601999: return "10"
        if 1602000 <= mid <= 1655999: return "11"
        if 1656000 <= mid <= 1919999: return "12"
        if 1920000 <= mid <= 2045999: return "13"
        if 2046000 <= mid <= 2189999: return "14"
        if 2190000 <= mid <= 2405999: return "15"
        if 2406000 <= mid <= 2621999: return "16"
        if 2622000 <= mid <= 2873999: return "17"
        if 2874000 <= mid <= 3125999: return "18"
        return "19" # и так далее

    # Пробуем вычислить корзину для твоего ID
    short_id = int(item_id) // 100
    basket = get_basket_extended(short_id)
    vol = int(item_id) // 100000
    part = int(item_id) // 1000
    
    async with aiohttp.ClientSession() as session:
        print(f"--- Тестируем товар {item_id} ---")
        # Сначала пробуем расчетную корзину
        # А потом еще пару соседних на всякий случай
        for b in [basket, "17", "18", "19", "20", "21"]:
            url = f"https://basket-{b}.wbbasket.ru/vol{vol}/part{part}/{item_id}/info/ru/card.json"
            print(f"Пробую: {url}")
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                async with session.get(url, headers=headers, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"\nOK! Сработала корзина {b}")
                        print(f"Название: {data.get('imt_name')}")
                        sizes = data.get("sizes") or []
                        price = None
                        if sizes:
                            total = (sizes[0].get("price") or {}).get("total")
                            if total:
                                price = total / 100
                        print(f"Цена: {price if price is not None else 'нет в card.json'} руб.")
                        return
                    else:
                        print(f"FAIL {b}: Код {resp.status}")
            except Exception as e:
                print(f"WARN Ошибка на {b}: {e}")

if __name__ == "__main__":
    asyncio.run(smoke_wb_card_json())
