
"""
Тест для универсального парсера (universal.py).
Проверяет поведение при получении пустого HTML.
"""
import asyncio
import pytest
from app.parsers.universal import UniversalParser, ParseResult

def test_universal_parser_empty_html():
    """Тестирует, что парсер корректно обрабатывает пустой HTML."""
    # Создаем парсер
    parser = UniversalParser()
    
    # Специально плохой HTML
    bad_html = """
    <html>
    <body>
    <div>Загрузка...</div>
    </body>
    </html>
    """
    
    # Вызываем метод парсинга
    result: ParseResult = asyncio.run(parser.fetch_product("https://example.com/product", bad_html))
    
    # Проверяем, что результат соответствует ожиданиям
    assert result.success is False
    assert result.page_structure == "EMPTY"
    assert "no entities found" in result.warnings
    assert result.next_strategy == "browser"
    
    # Проверяем, что data пустое
    assert result.data is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
