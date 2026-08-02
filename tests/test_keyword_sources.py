"""Тесты для модуля keyword_sources."""

import unittest

from app.keyword_sources import (
    CompetitorSource,
    ManualCSVSource,
    merge_keyword_sources,
)
from app.products.schema import UnifiedProduct
from app.seo_intelligence import extract_competitor_terms


def _пустой_товар(**kwargs):
    defaults = dict(name="", source_id="t1", source_type="test")
    defaults.update(kwargs)
    return UnifiedProduct(**defaults)


CSV_ДАННЫЕ = "keyword,frequency,marketplace,category\nнабор,100,ozon,кухня\nложка,80,ozon,кухня\nвилка,50,wildberries,кухня\nнабор,100,ozon,кухня\n"

CSV_БЕЗ_FREQ = "keyword,marketplace,category\nнабор,ozon,кухня\nложка,ozon,кухня\n"

CSV_ПУСТОЙ = "keyword\n"

CSV_ОДНА_КОЛОНКА = "keyword\nтоп\nлучший\nнедорого\n"


class ТестыManualCSVSource(unittest.TestCase):
    def test_парсинг_базовый(self):
        source = ManualCSVSource(CSV_ДАННЫЕ)
        keywords = source.get_keywords(_пустой_товар())
        self.assertIn("набор", keywords)
        self.assertIn("ложка", keywords)
        self.assertIn("вилка", keywords)

    def test_дубли_фильтруются(self):
        source = ManualCSVSource(CSV_ДАННЫЕ)
        keywords = source.get_keywords(_пустой_товар())
        self.assertEqual(keywords.count("набор"), 1)

    def test_сортировка_по_frequency(self):
        source = ManualCSVSource(CSV_ДАННЫЕ)
        keywords = source.get_keywords(_пустой_товар())
        idx_набор = keywords.index("набор")
        idx_ложка = keywords.index("ложка")
        idx_вилка = keywords.index("вилка")
        self.assertLess(idx_набор, idx_ложка)
        self.assertLess(idx_ложка, idx_вилка)

    def test_некорректная_frequency_не_роняет_импорт(self):
        source = ManualCSVSource("keyword,frequency\nложка,abc\nнабор,1 000\nвилка,10.5\n")
        keywords = source.get_keywords(_пустой_товар())
        self.assertEqual(keywords[:3], ["набор", "вилка", "ложка"])

    def test_без_frequency_порядок_сохраняется(self):
        source = ManualCSVSource(CSV_БЕЗ_FREQ)
        keywords = source.get_keywords(_пустой_товар())
        self.assertEqual(keywords, ["набор", "ложка"])

    def test_пустой_csv(self):
        source = ManualCSVSource(CSV_ПУСТОЙ)
        keywords = source.get_keywords(_пустой_товар())
        self.assertEqual(keywords, [])

    def test_bytes_вход(self):
        source = ManualCSVSource(CSV_ДАННЫЕ.encode("utf-8"))
        keywords = source.get_keywords(_пустой_товар())
        self.assertIn("набор", keywords)

    def test_только_keyword_колонка(self):
        source = ManualCSVSource(CSV_ОДНА_КОЛОНКА)
        keywords = source.get_keywords(_пустой_товар())
        self.assertEqual(keywords, ["топ", "лучший", "недорого"])


class ТестыCompetitorSource(unittest.TestCase):
    def test_извлечение_терминов(self):
        competitors = [
            {"name": "Набор ложек кухонных из нержавеющей стали"},
            {"name": "Набор вилок кухонных нержавеющая сталь"},
            {"name": "Набор ножей кухонных сталь"},
        ]
        source = CompetitorSource(competitors)
        keywords = source.get_keywords(_пустой_товар())
        self.assertIsInstance(keywords, list)
        for kw in keywords:
            self.assertIsInstance(kw, str)

    def test_интеграция_с_extract_competitor_terms(self):
        competitors = [{"name": "Блендер кухонный"}, {"name": "Блендер настольный"}]
        expected = extract_competitor_terms(competitors)
        source = CompetitorSource(competitors)
        result = source.get_keywords(_пустой_товар())
        self.assertEqual(result, expected)

    def test_пустой_список(self):
        source = CompetitorSource([])
        keywords = source.get_keywords(_пустой_товар())
        self.assertEqual(keywords, [])


class ТестыMergeKeywordSources(unittest.TestCase):
    def test_объединение_источников(self):
        csv_source = ManualCSVSource("keyword,frequency\nнабор,100\nложка,50\n")
        comp_source = CompetitorSource([{"name": "Набор ложек вилок"}])
        result = merge_keyword_sources([csv_source, comp_source], _пустой_товар())
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_дубли_удаляются(self):
        csv_source = ManualCSVSource("keyword,frequency\nнабор,100\n")
        comp_source = CompetitorSource([{"name": "Набор кухонный"}])
        result = merge_keyword_sources([csv_source, comp_source], _пустой_товар())
        self.assertEqual(len(result), len(set(result)))

    def test_приоритет_manual_перед_competitor(self):
        csv_source = ManualCSVSource("keyword\nаб\nбв\n")
        comp_source = CompetitorSource([{"name": "аб бв гг"}])
        result = merge_keyword_sources([csv_source, comp_source], _пустой_товар())
        manual_last = max(result.index(kw) for kw in ["аб", "бв"] if kw in result)
        comp_first = next((i for i, kw in enumerate(result) if kw not in ("аб", "бв")), len(result))
        self.assertLess(manual_last, comp_first)

    def test_лимит_50(self):
        csv_data = "keyword\n" + "\n".join(f"слово{i}" for i in range(60))
        csv_source = ManualCSVSource(csv_data)
        result = merge_keyword_sources([csv_source], _пустой_товар())
        self.assertLessEqual(len(result), 50)

    def test_кастомный_лимит(self):
        csv_data = "keyword\n" + "\n".join(f"слово{i}" for i in range(10))
        csv_source = ManualCSVSource(csv_data)
        result = merge_keyword_sources([csv_source], _пустой_товар(), limit=5)
        self.assertLessEqual(len(result), 5)

    def test_пустые_источники(self):
        result = merge_keyword_sources([], _пустой_товар())
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
