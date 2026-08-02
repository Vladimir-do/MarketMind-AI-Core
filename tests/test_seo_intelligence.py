import unittest

from app.card_filler import build_ozon_card_draft
from app.products.schema import UnifiedProduct
from app.seo_intelligence import (
    SEOAuditResult,
    SEOFinding,
    SEORecommendation,
    audit_ozon_card_seo,
    audit_unified_product_seo,
    extract_competitor_terms,
)


def _сильная_карточка():
    return build_ozon_card_draft(
        "товар: Магний B6 цитрат 600 мг 120 капсул\n"
        "бренд: NATURI\n"
        "категория: Витамины и БАДы\n"
        "цена: 346\n"
        "вес: 100 г\n"
        "размер: 100x80x70 мм\n"
        "состав: цитрат магния, витамин B6\n"
        "форма выпуска: капсулы\n"
        "дозировка: 600 мг\n"
        "https://example.com/1.jpg\n"
        "https://example.com/2.jpg\n"
        "https://example.com/3.jpg"
    )


def _слабая_карточка():
    return build_ozon_card_draft("товар: товар\nописание: лучший товар")


def _насыщенный_продукт(**переопределения):
    по_умолчанию = dict(
        name="Набор кухонных принадлежностей из нержавеющей стали 7 предметов",
        source_id="u1",
        source_type="wildberries",
        description=(
            "Набор кухонных принадлежностей из нержавеющей качества. "
            "Включает лопатку, половник, венчик, шумовку, щипцы, резак и держатель. "
            "Подходит для всех типов посуды. "
            "Преимущества: долговечность, удобная ручка, безопасный материал, легко мыть."
        ),
        category="Кухня/Инструменты",
        image_urls=["https://e.com/1.jpg", "https://e.com/2.jpg", "https://e.com/3.jpg"],
        attributes={"Материал": "сталь", "Вес": "800 г", "Цвет": "серебро", "Кол-во": "7"},
        tags=["набор", "кухня", "сталь", "инструменты", "принадлежности", "повар"],
    )
    по_умолчанию.update(переопределения)
    return UnifiedProduct(**по_умолчанию)


class ТестыSEO(unittest.TestCase):
    # ── Сильная карточка ───────────────────────────────────────────────

    def test_сильная_карточка_получает_высокий_балл(self):
        draft = _сильная_карточка()
        результат = audit_ozon_card_seo(draft)

        self.assertGreaterEqual(результат.score, 70)
        self.assertIn(результат.tier, {"usable", "strong"})
        self.assertFalse(any(н.severity == "critical" for н in результат.findings))

    def test_свойство_ready_у_сильной_карточки(self):
        draft = _сильная_карточка()
        результат = audit_ozon_card_seo(draft)
        if результат.score >= 75 and not any(ф.severity == "critical" for ф in результат.findings):
            self.assertTrue(результат.ready)
        else:
            self.assertFalse(результат.ready)

    # ── Слабая карточка ───────────────────────────────────────────────

    def test_слабая_карточка_получает_рекомендации(self):
        draft = _слабая_карточка()
        результат = audit_ozon_card_seo(draft)

        правила = {н.rule for н in результат.findings}
        self.assertLess(результат.score, 70)
        self.assertIn("seo_title_product_type", правила)
        self.assertIn("seo_category_missing", правила)
        self.assertIn("seo_attributes_few", правила)
        self.assertIn("seo_keywords_few", правила)
        self.assertTrue(результат.recommendations)
        self.assertEqual(результат.recommendations[0].priority, 2)

    def test_уровень_слабой_карточки(self):
        draft = _слабая_карточка()
        результат = audit_ozon_card_seo(draft)
        self.assertIn(результат.tier, {"weak", "needs_work"})

    # ── Границы уровней ───────────────────────────────────────────────

    def test_уровень_strong_при_балле_85_и_выше(self):
        from app.seo_intelligence import _tier
        self.assertEqual(_tier(100), "strong")
        self.assertEqual(_tier(85), "strong")
        self.assertEqual(_tier(84), "usable")

    def test_уровень_usable_при_балле_70_до_84(self):
        from app.seo_intelligence import _tier
        self.assertEqual(_tier(84), "usable")
        self.assertEqual(_tier(70), "usable")
        self.assertEqual(_tier(69), "needs_work")

    def test_уровень_needs_work_при_балле_50_до_69(self):
        from app.seo_intelligence import _tier
        self.assertEqual(_tier(69), "needs_work")
        self.assertEqual(_tier(50), "needs_work")
        self.assertEqual(_tier(49), "weak")

    def test_уровень_weak_при_балле_ниже_50(self):
        from app.seo_intelligence import _tier
        self.assertEqual(_tier(49), "weak")
        self.assertEqual(_tier(0), "weak")

    # ── Механика балла ─────────────────────────────────────────────────

    def test_балл_начинается_с_100_и_уменьшается_за_находки(self):
        from app.seo_intelligence import _score
        без_находок = []
        self.assertEqual(_score(без_находок), 100)

    def test_критичная_находка_вычитает_25(self):
        from app.seo_intelligence import _score
        находка = SEOFinding("правило", "поле", "critical", "сообщение")
        self.assertEqual(_score([находка]), 75)

    def test_предупреждение_вычитает_10(self):
        from app.seo_intelligence import _score
        находка = SEOFinding("правило", "поле", "warning", "сообщение")
        self.assertEqual(_score([находка]), 90)

    def test_информация_вычитает_4(self):
        from app.seo_intelligence import _score
        находка = SEOFinding("правило", "поле", "info", "сообщение")
        self.assertEqual(_score([находка]), 96)

    def test_балл_ограничен_снизу_нулем(self):
        from app.seo_intelligence import _score
        много = [SEOFinding(f"р{i}", "п", "critical", "с") for i in range(20)]
        self.assertEqual(_score(много), 0)

    def test_балл_ограничен_сверху_ста(self):
        from app.seo_intelligence import _score
        self.assertEqual(_score([]), 100)

    # ── Свойство ready ─────────────────────────────────────────────────

    def test_ready_требует_балл_75_и_нет_критичных(self):
        результат = SEOAuditResult(score=80, tier="usable", findings=[
            SEOFinding("р", "п", "warning", "с"),
        ])
        self.assertTrue(результат.ready)

    def test_ready_ложь_при_критичной_находке(self):
        результат = SEOAuditResult(score=90, tier="strong", findings=[
            SEOFinding("р", "п", "critical", "с"),
        ])
        self.assertFalse(результат.ready)

    def test_ready_ложь_при_балле_ниже_75(self):
        результат = SEOAuditResult(score=60, tier="needs_work", findings=[])
        self.assertFalse(результат.ready)

    # ── Проверки названия ──────────────────────────────────────────────

    def test_короткое_название_вызывает_предупреждение(self):
        продукт = _насыщенный_продукт(name="Кабель")
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_title_short", правила)

    def test_длинное_название_вызывает_критичную_ошибку(self):
        длинное = "Кабель " * 30
        продукт = _насыщенный_продукт(name=длинное.rstrip())
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_title_long", правила)
        критичные_найдены = any(н.rule == "seo_title_long" and н.severity == "critical" for н in результат.findings)
        self.assertTrue(критичные_найдены)

    def test_название_с_общим_типом_товара(self):
        продукт = _насыщенный_продукт(name="Товар для кухни из нержавеющей стали")
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_title_product_type", правила)

    def test_название_с_запрещёнными_словами(self):
        продукт = _насыщенный_продукт(name="Лучший набор кухонных принадлежностей из стали")
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_title_forbidden_words", правила)

    def test_хорошее_название_без_ошибок(self):
        продукт = _насыщенный_продукт(
            name="Кабель USB-C для зарядки и передачи данных 1 м черный"
        )
        результат = audit_unified_product_seo(продукт)
        правила_названия = {н.rule for н in результат.findings if н.field == "name"}
        self.assertNotIn("seo_title_short", правила_названия)
        self.assertNotIn("seo_title_long", правила_названия)
        self.assertNotIn("seo_title_product_type", правила_названия)

    # ── Проверки описания ──────────────────────────────────────────────

    def test_короткое_описание(self):
        продукт = _насыщенный_продукт(description="Короткое описание")
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_description_short", правила)

    def test_описание_без_блока_преимуществ(self):
        продукт = _насыщенный_продукт(
            description="Длинное описание товара " * 30
        )
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_description_benefits", правила)

    def test_описание_с_блоком_преимуществ_без_ошибки(self):
        описание = (
            "Подробное описание товара для кухни из нержавеющей стали. "
            "Подходит для профессионального и домашнего использования. "
            "Безопасный материал, долговечное покрытие. "
            "Преимущества: удобная ручка, безопасный материал, легко мыть, долговечность."
        )
        продукт = _насыщенный_продукт(description=описание)
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertNotIn("seo_description_benefits", правила)

    def test_описание_с_запрещёнными_словами(self):
        продукт = _насыщенный_продукт(
            description=(
                "Купить набор кухонных инструментов по скидке. "
                "Лучший выбор для вашего дома. "
                "Акция только сегодня. Гарантируем качество. "
                "Преимущества: долговечность, удобная ручка, безопасный материал, легко мыть."
            ) * 2
        )
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_description_forbidden_words", правила)

    # ── Проверки ключевых слов ─────────────────────────────────────────

    def test_мало_ключевых_слов(self):
        продукт = _насыщенный_продукт(tags=["кабель", "usb"])
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_keywords_few", правила)

    def test_достаточно_ключевых_слов_без_ошибки(self):
        продукт = _насыщенный_продукт(
            tags=["набор", "кухня", "сталь", "инструменты", "принадлежности", "повар"]
        )
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings if н.field == "keywords"}
        self.assertNotIn("seo_keywords_few", правила)

    def test_пробел_в_конкурентных_словах(self):
        конкуренты = [
            {"name": "Набор кухонный нержавеющая сталь"},
            {"name": "Кухонный набор из нержавеющей стали"},
            {"name": "Стальной кухонный набор инструментов"},
        ]
        термины = extract_competitor_terms(конкуренты)
        продукт = _насыщенный_продукт(
            tags=["набор", "кухня", "сталь", "инструменты", "принадлежности", "повар"]
        )
        результат = audit_unified_product_seo(продукт, competitor_terms=термины)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_keywords_competitor_gap", правила)

    def test_конкурентные_слова_покрыты_без_пробела(self):
        конкуренты = [
            {"name": "Набор кухонный нержавеющая сталь"},
            {"name": "Кухонный набор из нержавеющей стали"},
        ]
        термины = extract_competitor_terms(конкуренты)
        продукт = _насыщенный_продукт(
            tags=["набор", "кухня", "сталь", "нержавеющая", "нержавеющей", "кухонный", "инструменты", "принадлежности", "повар"]
        )
        результат = audit_unified_product_seo(продукт, competitor_terms=термины)
        правила = {н.rule for н in результат.findings if н.field == "keywords"}
        self.assertNotIn("seo_keywords_competitor_gap", правила)

    # ── Проверки глубины контента ──────────────────────────────────────

    def test_нет_категории(self):
        продукт = _насыщенный_продукт(category=None)
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_category_missing", правила)

    def test_мало_характеристик(self):
        продукт = _насыщенный_продукт(attributes={"Материал": "сталь"})
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_attributes_few", правила)

    def test_мало_изображений(self):
        продукт = _насыщенный_продукт(image_urls=["https://e.com/1.jpg"])
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings}
        self.assertIn("seo_images_few", правила)

    def test_достаточно_изображений_без_ошибки(self):
        продукт = _насыщенный_продукт(
            image_urls=["https://e.com/1.jpg", "https://e.com/2.jpg", "https://e.com/3.jpg"]
        )
        результат = audit_unified_product_seo(продукт)
        правила = {н.rule for н in результат.findings if н.field == "images"}
        self.assertNotIn("seo_images_few", правила)

    # ── Рекомендации ──────────────────────────────────────────────────

    def test_рекомендации_отсортированы_по_приоритету(self):
        draft = _слабая_карточка()
        результат = audit_ozon_card_seo(draft)
        приоритеты = [р.priority for р in результат.recommendations]
        self.assertEqual(приоритеты, sorted(приоритеты))

    def test_рекомендации_имеют_известные_действия(self):
        draft = _слабая_карточка()
        результат = audit_ozon_card_seo(draft)
        известные_действия = {
            "Расширить название: тип товара + ключевые свойства + бренд.",
            "Начать название с конкретного типа товара.",
            "Убрать рекламные обещания из названия.",
            "Расширить описание: назначение, сценарии, преимущества, характеристики.",
            "Добавить блок преимуществ в описание.",
            "Добавить релевантные ключевые слова из названия, категории и характеристик.",
            "Уточнить категорию Ozon.",
            "Заполнить характеристики, которые участвуют в фильтрах и поиске.",
            "Добавить главное фото и 2-4 дополнительных ракурса.",
            "Сформулировать 3-4 преимущества без неподтвержденных обещаний.",
        }
        for р in результат.recommendations:
            self.assertIn(р.action, известные_действия, f"Неизвестное действие: {р.action}")

    # ── Извлечение конкурентных терминов ───────────────────────────────

    def test_фильтрация_общих_и_запрещённых_слов(self):
        конкуренты = [
            {"name": "Лучший товар для кухни"},
            {"name": "Лучший товар для кухни"},
        ]
        термины = extract_competitor_terms(конкуренты)
        self.assertNotIn("лучший", термины)
        self.assertNotIn("товар", термины)

    def test_ограничение_количества_терминов(self):
        конкуренты = [
            {"name": f"Слово{i} большой набор слов для теста"}
            for i in range(30)
        ]
        термины = extract_competitor_terms(конкуренты, limit=5)
        self.assertLessEqual(len(термины), 5)

    def test_уникальные_слова_не_попадают_в_термины(self):
        конкуренты = [
            {"name": "Уникальное слово А"},
            {"name": "Другое слово Б"},
        ]
        термины = extract_competitor_terms(конкуренты)
        self.assertNotIn("уникальное", термины)
        self.assertNotIn("другое", термины)

    def test_пустой_ввод(self):
        self.assertEqual(extract_competitor_terms([]), [])

    def test_пустые_имена(self):
        конкуренты = [{"name": ""}, {"name": ""}]
        термины = extract_competitor_terms(конкуренты)
        self.assertEqual(термины, [])

    # ── Граничные случаи UnifiedProduct ────────────────────────────────

    def test_пустые_поля_дают_низкий_балл(self):
        продукт = UnifiedProduct(
            name="",
            source_id="u2",
            source_type="unknown",
            description="",
            image_urls=[],
            attributes={},
            tags=[],
        )
        результат = audit_unified_product_seo(продукт)
        self.assertLess(результат.score, 50)
        self.assertIn(результат.tier, {"weak", "needs_work"})

    def test_без_конкурентных_терминов(self):
        продукт = _насыщенный_продукт()
        результат = audit_unified_product_seo(продукт, competitor_terms=None)
        self.assertIsNotNone(результат)

    def test_пустой_список_конкурентных_терминов(self):
        продукт = _насыщенный_продукт()
        результат = audit_unified_product_seo(продукт, competitor_terms=[])
        self.assertIsNotNone(результат)

    # ── Dataclass находки и рекомендации ───────────────────────────────

    def test_находка_заморожена(self):
        находка = SEOFinding("р", "п", "info", "с")
        with self.assertRaises(AttributeError):
            находка.rule = "новое"

    def test_рекомендация_заморожена(self):
        рекомендация = SEORecommendation("п", "д", 1, "р")
        with self.assertRaises(AttributeError):
            рекомендация.field = "новое"

    def test_находка_содержит_все_поля(self):
        находка = SEOFinding("правило1", "название", "warning", "сообщение")
        self.assertEqual(находка.rule, "правило1")
        self.assertEqual(находка.field, "название")
        self.assertEqual(находка.severity, "warning")
        self.assertEqual(находка.message, "сообщение")


    # ── Граничные случаи UnifiedProduct (None-поля) ─────────────────────

    def test_продукт_name_none_не_падает(self):
        продукт = _насыщенный_продукт(name=None)
        результат = audit_unified_product_seo(продукт)
        self.assertIsInstance(результат.score, int)
        self.assertIn("seo_title_short", {н.rule for н in результат.findings})

    def test_продукт_description_none_не_падает(self):
        продукт = _насыщенный_продукт(description=None)
        результат = audit_unified_product_seo(продукт)
        self.assertIsInstance(результат.score, int)
        self.assertIn("seo_description_short", {н.rule for н in результат.findings})

    def test_продукт_tags_none_не_падает(self):
        продукт = _насыщенный_продукт(tags=None)
        результат = audit_unified_product_seo(продукт)
        self.assertIsInstance(результат.score, int)
        self.assertIn("seo_keywords_few", {н.rule for н in результат.findings})

    def test_продукт_attributes_none_не_падает(self):
        продукт = UnifiedProduct(
            name="Тестовый товар для проверки None attributes",
            source_id="u4",
            source_type="test",
            description="Описание товара для проверки None attributes",
            category="Категория",
            image_urls=["https://e.com/1.jpg", "https://e.com/2.jpg", "https://e.com/3.jpg"],
            attributes=None,
            tags=["тег1", "тег2", "тег3", "тег4", "тег5", "тег6"],
        )
        результат = audit_unified_product_seo(продукт)
        self.assertIsInstance(результат.score, int)
        self.assertIn("seo_attributes_few", {н.rule for н in результат.findings})

    def test_продукт_image_urls_none_не_падает(self):
        продукт = UnifiedProduct(
            name="Тестовый товар для проверки None image_urls",
            source_id="u3",
            source_type="test",
            description="Описание товара для проверки None image_urls достаточно длинное",
            category="Категория",
            image_urls=None,
            attributes={"A": "1", "B": "2", "C": "3", "D": "4"},
            tags=["тег1", "тег2", "тег3", "тег4", "тег5", "тег6"],
        )
        результат = audit_unified_product_seo(продукт)
        self.assertIsInstance(результат.score, int)
        self.assertIn("seo_images_few", {н.rule for н in результат.findings})

    # ── Граничные случаи score ──────────────────────────────────────────

    def test_score_все_типы_находок_одновременно(self):
        from app.seo_intelligence import _score
        находки = [
            SEOFinding("crit1", "п", "critical", "критическая"),
            SEOFinding("warn1", "п", "warning", "предупреждение"),
            SEOFinding("info1", "п", "info", "информация"),
        ]
        # 100 - 25 - 10 - 4 = 61
        self.assertEqual(_score(находки), 61)

    def test_score_ровно_ноль_находок(self):
        from app.seo_intelligence import _score
        self.assertEqual(_score([]), 100)

    def test_score_ровно_по_одной_находке_каждого_типа(self):
        from app.seo_intelligence import _score
        критическая = [SEOFinding("р", "п", "critical", "с")]
        предупреждение = [SEOFinding("р", "п", "warning", "с")]
        информация = [SEOFinding("р", "п", "info", "с")]
        self.assertEqual(_score(критическая), 75)
        self.assertEqual(_score(предупреждение), 90)
        self.assertEqual(_score(информация), 96)

    # ── Competitor terms edge cases ──────────────────────────────────────

    def test_один_конкурент_одно_слово(self):
        конкуренты = [{"name": "Магний"}]
        термины = extract_competitor_terms(конкуренты)
        # Одно слово одного конкурента не проходит фильтр count > 1
        self.assertEqual(термины, [])

    def test_конкурент_с_пустым_name(self):
        конкуренты = [{"name": ""}]
        термины = extract_competitor_terms(конкуренты)
        self.assertEqual(термины, [])

    def test_конкурент_с_name_none(self):
        конкуренты = [{"name": None}]
        термины = extract_competitor_terms(конкуренты)
        self.assertEqual(термины, [])

    def test_100_конкурентов_с_limit_3(self):
        конкуренты = [
            {"name": "Кухонный набор инструмент"}
            for _ in range(100)
        ]
        термины = extract_competitor_terms(конкуренты, limit=3)
        self.assertLessEqual(len(термины), 3)

    # ── Рекомендации точно соответствуют находкам ───────────────────────

    def test_каждая_находка_порождает_одну_рекомендацию(self):
        from app.seo_intelligence import _recommend
        находки = [
            SEOFinding("rule1", "name", "critical", "сообщение1"),
            SEOFinding("rule2", "description", "warning", "сообщение2"),
            SEOFinding("rule3", "keywords", "info", "сообщение3"),
        ]
        рекомендации = _recommend(находки)
        self.assertEqual(len(рекомендации), len(находки))

    def test_количество_рекомендаций_равно_количеству_находок(self):
        from app.seo_intelligence import _recommend
        находки = [
            SEOFinding("r1", "f1", "critical", "m1"),
            SEOFinding("r2", "f2", "warning", "m2"),
            SEOFinding("r3", "f3", "info", "m3"),
            SEOFinding("r4", "f4", "critical", "m4"),
        ]
        рекомендации = _recommend(находки)
        self.assertEqual(len(рекомендации), 4)

    def test_без_находок_нет_рекомендаций(self):
        from app.seo_intelligence import _recommend
        self.assertEqual(_recommend([]), [])

    # ── tier(score) все граничные значения ──────────────────────────────

    def test_tier_все_граничные_значения(self):
        from app.seo_intelligence import _tier
        self.assertEqual(_tier(0), "weak")
        self.assertEqual(_tier(49), "weak")
        self.assertEqual(_tier(50), "needs_work")
        self.assertEqual(_tier(69), "needs_work")
        self.assertEqual(_tier(70), "usable")
        self.assertEqual(_tier(84), "usable")
        self.assertEqual(_tier(85), "strong")
        self.assertEqual(_tier(100), "strong")


if __name__ == "__main__":
    unittest.main()
