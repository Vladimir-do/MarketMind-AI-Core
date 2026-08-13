from __future__ import annotations

from datetime import datetime
from typing import Literal

from aiogram import Bot, types

from app.database import Database

ExportKind = Literal["csv", "excel"]


def _require_active_bot(bot: Bot | None) -> Bot:
    if bot is None:
        raise RuntimeError("Telegram bot is not connected")
    return bot


async def send_price_export(bot: Bot | None, db: Database, chat_id: int, kind: ExportKind) -> None:
    active_bot = _require_active_bot(bot)
    if kind == "csv":
        from app.exporter import export_csv

        buf = await export_csv(db)
        filename = f"prices_{datetime.now().strftime('%Y%m%d')}.csv"
        caption = "📊 Экспорт цен в CSV"
    elif kind == "excel":
        from app.exporter import export_excel

        buf = await export_excel(db)
        filename = f"prices_{datetime.now().strftime('%Y%m%d')}.xlsx"
        caption = "📊 Мониторинг цен — Excel отчёт"
    else:
        raise ValueError(f"Unsupported export kind: {kind}")

    await active_bot.send_document(
        chat_id,
        types.BufferedInputFile(buf.read(), filename=filename),
        caption=caption,
    )


async def send_html_report(bot: Bot | None, db: Database, chat_id: int) -> None:
    active_bot = _require_active_bot(bot)
    from app.reporter import export_html_report

    buf = await export_html_report(db)
    await active_bot.send_document(
        chat_id,
        types.BufferedInputFile(buf.read(), filename=f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"),
        caption=(
            "📊 <b>Отчёт мониторинга цен</b>\n\n"
            "Откройте файл в браузере — там интерактивные графики, "
            "карточки товаров, тепловая карта активности и рекомендации."
        ),
        parse_mode="HTML",
    )
