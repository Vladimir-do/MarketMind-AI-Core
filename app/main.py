import argparse
import asyncio
import os
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")


def main():
    parser = argparse.ArgumentParser(description="Агент мониторинга цен маркетплейсов")
    parser.add_argument("--telegram", action="store_true", help="Запустить Telegram-бота")
    parser.add_argument("--update",   action="store_true", help="Обновить цены всех товаров")
    parser.add_argument("--metrics", type=int, metavar="N", help="Показать последние N попыток парсинга")
    parser.add_argument("--blocks", type=int, metavar="N", help="Показать последние N блокировок/сетевых сбоев")
    parser.add_argument("--ozon-login", action="store_true", help="Open visible Ozon browser and save cookies")
    parser.add_argument("--ozon-url", default="https://www.ozon.ru/", help="URL for --ozon-login")
    parser.add_argument("--report", action="store_true", help="Generate HTML report file")
    parser.add_argument("--embed-images", action="store_true", help="Embed product images into generated HTML report")
    parser.add_argument("--deploy-wb", action="store_true", help="Deploy WB Yandex Cloud Function")
    parser.add_argument("--enrich", metavar="INPUT", help="Enrich XLSX/CSV product table")
    parser.add_argument("--out", metavar="OUTPUT", help="Output XLSX path for --enrich")
    parser.add_argument("--limit", type=int, help="Process at most N rows for --enrich")
    parser.add_argument("--resume", action="store_true", help="Resume --enrich using checkpoint")
    parser.add_argument("--mode", choices=["generic", "brd"], default="generic", help="Enrichment mode")
    parser.add_argument("--brd-categories", help="Path to BRD categories DOCX for --mode brd")
    parser.add_argument("--online", action="store_true", help="For --mode brd, research rows on the web")
    parser.add_argument("--img-dir", help="Directory for downloaded BRD images")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between online BRD rows, seconds")
    args = parser.parse_args()

    if args.telegram:
        from app.bot import start_bot
        ok = asyncio.run(start_bot())
        if not ok:
            print("Telegram bot was not started. See the log message above and fix the configuration, then try again.")
            return

    elif args.update:
        async def _update():
            from app.config import PROXY
            from app.database import Database
            from app.worker import worker_update_all
            db = Database()
            await db.init()
            proxy = PROXY if PROXY else None

            async def _notify(text: str):
                print(text)

            await worker_update_all(db, _notify, proxy=proxy)

        asyncio.run(_update())

    elif args.metrics:
        async def _metrics():
            from app.database import Database
            db = Database()
            await db.init()
            attempts = await db.get_recent_scrape_attempts(limit=args.metrics)
            if not attempts:
                print("Измерения не найдены")
                return

            print("time | marketplace | source | status | http | latency_ms | url")
            for a in attempts:
                ts = a.recorded_at.strftime("%Y-%m-%d %H:%M:%S") if a.recorded_at else ""
                http = a.http_status if a.http_status is not None else "-"
                print(
                    f"{ts} | {a.marketplace} | {a.source} | {a.status} | "
                    f"{http} | {a.latency_ms} | {a.url}"
                )

        asyncio.run(_metrics())

    elif args.blocks:
        async def _blocks():
            from app.database import Database
            db = Database()
            await db.init()
            rows = await db.get_recent_blocked_patterns(limit=args.blocks)
            if not rows:
                print("Блокировки и сетевые сбои не найдены")
                return

            print("time | marketplace | source | status | trigger | http | latency_ms | strategy | url")
            for row in rows:
                ts = row.recorded_at.strftime("%Y-%m-%d %H:%M:%S") if row.recorded_at else ""
                http = row.http_status if row.http_status is not None else "-"
                strategy = row.strategy or "-"
                print(
                    f"{ts} | {row.marketplace} | {row.source} | {row.status} | "
                    f"{row.trigger} | {http} | {row.latency_ms} | {strategy} | {row.url or '-'}"
                )

        asyncio.run(_blocks())

    elif args.ozon_login:
        async def _ozon_login():
            from playwright.async_api import async_playwright

            from app.updater import STEALTH_SCRIPT, USER_AGENTS, VIEWPORTS

            root = Path(__file__).resolve().parent.parent
            profile_dir = os.getenv("OZON_PROFILE_DIR", "").strip()
            if not profile_dir:
                profile_dir = str(root / "app" / "data" / "ozon_profile")
                os.environ["OZON_PROFILE_DIR"] = profile_dir
            Path(profile_dir).mkdir(parents=True, exist_ok=True)

            print("Opening visible Ozon browser.")
            print(f"Profile: {profile_dir}")
            print("Log in to Ozon and complete abt-challenge/captcha once.")
            print("Cookies will be saved into the persistent profile for next parser runs.")
            print("After successful login/check, return here and press Enter.")

            pw = await async_playwright().start()
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                user_agent=USER_AGENTS[0],
                no_viewport=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--start-maximized",
                    "--lang=ru-RU",
                ],
                extra_http_headers={
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            try:
                await context.add_init_script(STEALTH_SCRIPT)
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(args.ozon_url, wait_until="domcontentloaded", timeout=60_000)
                await asyncio.to_thread(input, "Press Enter here after Ozon opens normally...")
            finally:
                await context.close()
                await pw.stop()

        asyncio.run(_ozon_login())

    elif args.report:
        async def _report():
            from datetime import datetime

            from app.database import Database
            from app.reporter import export_html_report

            db = Database()
            await db.init()
            buf = await export_html_report(db, embed_images=args.embed_images)
            payload = buf.read()
            out_dir = Path("app") / "data" / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            out.write_bytes(payload)
            await db._engine.dispose()
            print(f"Report saved: {out.resolve()}")
            print(f"Product image tags: {payload.count(b'<img ')}")
            print(f"Embedded images: {payload.count(b'data:image')}")

        asyncio.run(_report())

    elif args.deploy_wb:
        import deploy_cloud

        raise SystemExit(deploy_cloud.main())

    elif args.enrich:
        if not args.out:
            parser.error("--out is required with --enrich")
        if args.mode == "brd":
            from app.brd_enricher import prepare_brd_table

            result = prepare_brd_table(
                args.enrich,
                args.out,
                categories_path=args.brd_categories,
                limit=args.limit,
                resume=args.resume,
                online=args.online,
                img_dir=args.img_dir,
                delay_sec=args.delay,
            )
            print("BRD preparation complete")
            print(f"Categories: {result['categories']}")
            print(f"Categories count: {result['categories_count']}")
            print(f"Sheet: {result['sheet']}")
        else:
            from app.batch_enricher import enrich_file

            result = enrich_file(
                args.enrich,
                args.out,
                limit=args.limit,
                resume=args.resume,
            )
            print("Enrichment complete")
        print(f"Input: {result['input']}")
        print(f"Output: {result['output']}")
        print(f"Rows total: {result['total_rows']}")
        print(f"Processed now: {result['processed']}")
        print(f"Skipped by checkpoint: {result['skipped']}")
        print(f"Checkpoint: {result['checkpoint']}")

    else:
        print("Укажите режим:")
        print("  python -m app.main --telegram   # запустить бота")
        print("  python -m app.main --update     # обновить цены без бота")
        print("  python -m app.main --metrics 20 # последние измерения")
        print("  python -m app.main --blocks 20  # последние блокировки/сетевые сбои")
        print("  python -m app.main --ozon-login # open Ozon browser profile")
        print("  python -m app.main --report --embed-images # save self-contained HTML report")
        print("  python -m app.main --enrich input.xlsx --out output.xlsx --limit 50")
        print("  python -m app.main --enrich \"Таблица BRD.xlsx\" --out \"Таблица BRD ИИ.xlsx\" --mode brd --limit 50")
        print("  python -m app.main --enrich \"Таблица BRD.xlsx\" --out \"Таблица BRD ИИ.xlsx\" --mode brd --online --limit 5")
        print("  python -m app.main --deploy-wb # deploy WB Yandex Cloud Function")
        parser.print_help()


if __name__ == "__main__":
    main()
