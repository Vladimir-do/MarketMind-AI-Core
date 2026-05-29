"""
universal.py — Универсальный парсер для обработки пустых или проблемных страниц.
Реализует поведение согласно задаче: не паниковать при пустом HTML,
а возвращать корректный ParseResult с предложением следующей стратегии.
"""
from typing import Optional
from dataclasses import dataclass
from .base import BaseParser, ProductData


@dataclass
class ParseResult:
    """Результат парсинга, который может включать не только данные, но и мета-информацию."""
    success: bool
    data: Optional[ProductData] = None
    page_structure: str = "unknown"
    warnings: list[str] = None
    next_strategy: str = "none"

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class UniversalParser(BaseParser):
    """Универсальный парсер для обработки пустых или проблемных HTML-страниц.
    
    Этот парсер всегда возвращает `ParseResult`, чтобы агент мог корректно
    восстановиться и выбрать следующую стратегию (например, использовать браузер),
    не паникуя и не генерируя исключения при отсутствии данных.
    """

    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Этот парсер может обработать любой URL.
        Он будет применяться, когда другие парсеры не подходят или как fallback.
        """
        return True

    def _detect_page_structure(self, html: str) -> str:
        """Определяет структуру страницы на основе HTML."""
        html_lower = html.lower()
        if "загрузка..." in html_lower or "loading" in html_lower or "<div>" not in html:
            return "EMPTY"
        # Здесь можно добавить больше проверок для CATALOG, PRODUCT и т.д.
        return "unknown"

    async def fetch_product(self, url: str, html: str = "<html><body></body></html>") -> ParseResult:
        """Парсит HTML и возвращает ParseResult.
        
        Args:
            url: URL страницы.
            html: Строка с HTML-контентом страницы.

        Returns:
            ParseResult с результатом и рекомендацией по следующей стратегии.
        """
        page_structure = self._detect_page_structure(html)

        if page_structure == "EMPTY":
            return ParseResult(
                success=False,
                data=None,
                page_structure=page_structure,
                warnings=["no entities found"],
                next_strategy="browser"
            )

        # В реальном сценарии здесь была бы логика парсинга
        # Сейчас для простоты возвращаем пустой результат
        return ParseResult(
            success=False,
            data=None,
            page_structure=page_structure,
            warnings=["parsing not implemented"],
            next_strategy="none"
        )

    async def search(self, query: str, max_results: int = 5) -> list[ProductData]:
        """Поиск не поддерживается универсальным парсером."""
        return []
