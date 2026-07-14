import unittest

from app.task_intents import ContextSession, TaskType, detect_task_intent


class TaskIntentTests(unittest.TestCase):
    def test_detects_structured_scraping_task(self):
        prompt = """Analyze site https://books.toscrape.com/

Need collect:
- title
- price
- availability
- rating
- product_url

Result: save to CSV.
Requirements:
- logging
- error handling
- delay between requests
"""
        task = detect_task_intent(prompt)

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.target_url, "https://books.toscrape.com/")
        self.assertEqual(task.fields, ["title", "price", "availability", "rating", "product_url"])
        self.assertEqual(task.output, "csv")
        self.assertIn("logging", task.requirements)
        self.assertIn("error handling", task.requirements)
        self.assertIn("delay", task.requirements)
        self.assertGreaterEqual(len(task.plan), 5)

    def test_collect_all_phrase_becomes_scope_not_field(self):
        prompt = """Спарси https://books.toscrape.com/
собери_все_книги

Поля:
- title
- price
- availability
- rating
- product_url

CSV
"""
        task = detect_task_intent(prompt)

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.fields, ["title", "price", "availability", "rating", "product_url"])
        self.assertNotIn("собери_все_книги", task.fields)
        self.assertEqual(task.parameters["scope"], "all_pages")
        self.assertTrue(task.parameters["pagination"])
        self.assertEqual(task.output, "csv")

    def test_russian_scraping_commands_do_not_pollute_fields(self):
        prompt = """Задача: https://books.toscrape.com/
собери с первой страницы
- название книги
- цену
- наличие
- рейтинг
- ссылку на карточку
- добавить логирование
- добавить обработку ошибок
CSV
"""
        task = detect_task_intent(prompt)

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.fields, ["title", "price", "availability", "rating", "product_url"])
        self.assertNotIn("задача", task.fields)
        self.assertNotIn("собери_с_первой_страницы", task.fields)
        self.assertEqual(task.parameters["scope"], "first_page")
        self.assertEqual(task.output, "csv")
        self.assertIn("logging", task.requirements)
        self.assertIn("error handling", task.requirements)

    def test_books_full_task_keeps_report_instructions_out_of_fields(self):
        prompt = """Проанализируй сайт https://books.toscrape.com/

Задача:
1. Собери данные по всем книгам:
   - title
   - price
   - availability
   - rating
   - product_url

2. Сохрани результат в CSV.

3. Обязательно добавь:
   - логирование;
   - обработку ошибок;
   - задержку между запросами;
   - нормальную структуру функций;
   - защиту от падения при изменении HTML.

4. После выполнения напиши:
   - сколько книг собрано;
   - какие файлы созданы;
   - какие проблемы были найдены;
   - как можно улучшить парсер.
"""
        task = detect_task_intent(prompt)

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.fields, ["title", "price", "availability", "rating", "product_url"])
        self.assertEqual(task.output, "csv")
        self.assertEqual(task.parameters["scope"], "all_pages")
        self.assertTrue(task.parameters["pagination"])
        self.assertNotIn("focus_terms", task.parameters)
        self.assertIn("logging", task.requirements)
        self.assertIn("delay", task.requirements)
        self.assertIn("error handling", task.requirements)

    def test_saved_scraping_context_summary_keeps_fields(self):
        task = detect_task_intent(
            "\u041f\u043e\u043d\u044f\u043b scraping-\u0437\u0430\u0434\u0430\u0447\u0443\n"
            "\u0426\u0435\u043b\u044c: https://books.toscrape.com/\n"
            "\u041f\u043e\u043b\u044f: title, price, availability, rating, product_url\n"
            "\u0412\u044b\u0432\u043e\u0434: CSV\n"
            "\u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b: scope=first_page\n"
        )

        self.assertEqual(task.fields, ["title", "price", "availability", "rating", "product_url"])
        self.assertEqual(task.output, "csv")
        self.assertEqual(task.parameters.get("scope"), "first_page")

    def test_save_to_csv_command_in_labeled_fields_is_not_a_field(self):
        task = detect_task_intent(
            "\u0426\u0435\u043b\u044c: https://books.toscrape.com/\n"
            "\u041f\u043e\u043b\u044f: title, price, availability, rating, product_url, "
            "\u0441\u043e\u0445\u0440\u0430\u043d\u0438_\u0432_csv\n"
            "\u0412\u044b\u0432\u043e\u0434: CSV\n"
            "\u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b: pagination=True\n"
        )

        self.assertEqual(task.fields, ["title", "price", "availability", "rating", "product_url"])
        self.assertTrue(task.parameters["pagination"])

    def test_context_extends_current_scraping_task_with_later_fields(self):
        context = ContextSession()
        first = detect_task_intent("Проанализируй сайт https://books.toscrape.com/", context=context)
        second = detect_task_intent("title\nprice\nrating", context=context)

        self.assertEqual(first.type, TaskType.SCRAPING)
        self.assertEqual(second.type, TaskType.SCRAPING)
        self.assertEqual(second.target_url, "https://books.toscrape.com/")
        self.assertEqual(second.fields, ["title", "price", "rating"])

    def test_context_extends_books_scraping_with_detail_fields(self):
        context = ContextSession()
        first = detect_task_intent(
            "Analyze site https://books.toscrape.com/\n"
            "title\nprice\navailability\nrating\nproduct_url\n"
            "Result: CSV\npagination",
            context=context,
        )
        second = detect_task_intent(
            "Открой каждую карточку книги и дополнительно собери:\n"
            "- UPC\n"
            "- product_type\n"
            "- tax\n"
            "- number_of_reviews\n"
            "- description",
            context=context,
        )

        self.assertEqual(first.type, TaskType.SCRAPING)
        self.assertEqual(second.type, TaskType.SCRAPING)
        self.assertEqual(second.target_url, "https://books.toscrape.com/")
        self.assertEqual(
            second.fields,
            [
                "title",
                "price",
                "availability",
                "rating",
                "product_url",
                "upc",
                "product_type",
                "tax",
                "number_of_reviews",
                "description",
            ],
        )
        self.assertEqual(second.output, "csv")
        self.assertTrue(second.parameters["pagination"])

    def test_context_ignores_acknowledgement_as_field(self):
        context = ContextSession()
        first = detect_task_intent("Проанализируй сайт https://books.toscrape.com/\ntitle\nprice", context=context)
        second = detect_task_intent("ок", context=context)

        self.assertEqual(first.type, TaskType.SCRAPING)
        self.assertEqual(second.type, TaskType.UNKNOWN)

    def test_russian_requirements_do_not_become_fields(self):
        task = detect_task_intent(
            "спарси https://books.toscrape.com/\n"
            "- title\n"
            "- логирование\n"
            "- retry"
        )

        self.assertEqual(task.fields, ["title"])
        self.assertIn("logging", task.requirements)
        self.assertIn("retry", task.requirements)

    def test_price_assortment_prompt_gets_focus_terms_and_price_fields(self):
        task = detect_task_intent(
            "спарси цены на шашлык и общий ассортимент мясных блюд: https://chibbis.ru/orsk/restaurants"
        )

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.fields, ["title", "price", "description", "product_url"])
        self.assertIn("шашлык", task.parameters["focus_terms"])
        self.assertIn("мясных", task.parameters["focus_terms"])

    def test_live_price_assortment_prompt_with_typos_stays_scraping(self):
        task = detect_task_intent(
            "спарси цены а шашлык и общий асартимент мясных блюд!: https://chibbis.ru/orsk/restaurants"
        )

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.target_url, "https://chibbis.ru/orsk/restaurants")
        self.assertEqual(task.fields, ["title", "price", "description", "product_url"])
        self.assertIn("шашлык", task.parameters["focus_terms"])

    def test_detects_marketplace_search(self):
        task = detect_task_intent("найди держатель для телефона")

        self.assertEqual(task.type, TaskType.MARKETPLACE_SEARCH)
        self.assertEqual(task.query, "держатель для телефона")

    def test_page_classification_training_does_not_become_marketplace_search(self):
        prompt = """Открой страницу и НЕ парси сразу.
https://books.toscrape.com/

Сначала определи:
- task_type
- page_structure
- confidence

Верни:
- status
- warnings
"""
        task = detect_task_intent(prompt)

        self.assertEqual(task.type, TaskType.PAGE_CLASSIFICATION_TRAINING)
        self.assertEqual(task.plan[0], "classify_page_before_parsing")
        self.assertEqual(task.target_url, "https://books.toscrape.com/")
        self.assertIsNone(task.query)

    def test_training_protocol_fragments_do_not_become_marketplace_search(self):
        for fragment in ("Верни:", "- task_type", "- page_structure", "- confidence", "- warnings"):
            task = detect_task_intent(fragment)

            self.assertNotEqual(task.type, TaskType.MARKETPLACE_SEARCH)
            self.assertIsNone(task.query)

    def test_context_remembers_page_classification_training_status(self):
        context = ContextSession()
        task = detect_task_intent("Открой страницу и НЕ парси сразу. Сначала определи task_type", context=context)

        self.assertEqual(task.type, TaskType.PAGE_CLASSIFICATION_TRAINING)
        self.assertTrue(context.waiting_for_page_classification_url())
        self.assertEqual(context.status, "нужен URL страницы для анализа")

    def test_context_url_continues_page_classification_training(self):
        context = ContextSession()
        task = detect_task_intent("Открой страницу и НЕ парси сразу. Сначала определи task_type", context=context)
        urls = ["https://books.toscrape.com/catalogue/category/books/travel_2/index.html"]

        self.assertEqual(task.type, TaskType.PAGE_CLASSIFICATION_TRAINING)
        self.assertTrue(context.should_continue_page_classification(urls))

    def test_explicit_scrape_command_resets_page_classification_training(self):
        context = ContextSession()
        detect_task_intent(
            "\u041e\u0442\u043a\u0440\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u0438 \u041d\u0415 \u043f\u0430\u0440\u0441\u0438 \u0441\u0440\u0430\u0437\u0443. "
            "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438 task_type",
            context=context,
        )
        text = (
            "\u0441\u043f\u0430\u0440\u0441\u0438 \u0446\u0435\u043d\u044b \u043d\u0430 \u0448\u0430\u0448\u043b\u044b\u043a "
            "\u0438 \u043c\u044f\u0441\u043d\u044b\u0435 \u0431\u043b\u044e\u0434\u0430: https://chibbis.ru/orsk/restaurants"
        )

        self.assertFalse(context.should_continue_page_classification(["https://chibbis.ru/orsk/restaurants"], text))
        task = detect_task_intent(text, context=context)

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.parameters["task_type"], "restaurant_menu")
        self.assertEqual(task.parameters["entity_type"], "dish")
        self.assertEqual(task.parameters["next_strategy"], "browser")
        self.assertIsNone(context.active_intent)

    def test_books_to_scrape_scraping_gets_product_catalog_task_type(self):
        task = detect_task_intent("Analyze site https://books.toscrape.com/ collect all books")

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.parameters["task_type"], "product_catalog")
        self.assertEqual(task.parameters["entity_type"], "product")
        self.assertEqual(task.parameters["page_structure"], "catalog_or_single")

    def test_fl_project_scraping_gets_freelance_project_task_type(self):
        task = detect_task_intent(
            "\u0441\u043f\u0430\u0440\u0441\u0438 \u044d\u0442\u043e: "
            "https://www.fl.ru/projects/5504773/parsing-sayta-zolotoe-yabloko-deklaratsii-sootvetstviya.html"
        )

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.parameters["task_type"], "freelance_project")
        self.assertEqual(task.parameters["entity_type"], "project")
        self.assertEqual(task.parameters["page_structure"], "article_or_project")

    def test_jsonplaceholder_scraping_gets_api_source_task_type(self):
        task = detect_task_intent("collect data from https://jsonplaceholder.typicode.com/posts")

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(task.parameters["task_type"], "api_source")
        self.assertEqual(task.parameters["entity_type"], "record")
        self.assertEqual(task.parameters["next_strategy"], "api")

    def test_detects_card_generation(self):
        task = detect_task_intent("составь карточку для кусачки маникюрные цена 499")

        self.assertEqual(task.type, TaskType.CARD_GENERATION)
        self.assertEqual(task.payload, "кусачки маникюрные цена 499")

    def test_detects_update_task(self):
        task = detect_task_intent("обнови цены")

        self.assertEqual(task.type, TaskType.UPDATE)

    def test_detects_repair_task_for_agent_failure_report(self):
        task = detect_task_intent(
            "\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431\u0441\u044f: "
            "\u043d\u0435 \u0441\u043f\u0430\u0440\u0441\u0438\u043b BooksToScrape, "
            "No product records were extracted"
        )

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertEqual(task.parameters["repair_mode"], "regression_first")
        self.assertEqual(task.parameters["failure_area"], "parser")
        self.assertEqual(task.parameters["severity"], "high")
        self.assertEqual(task.parameters["blast_radius"], "localized")
        self.assertIn("empty_extraction", task.parameters["evidence_types"])
        self.assertIn("focused_tests", task.parameters["verification_scope"])
        self.assertIn("skillpack_validator", task.parameters["verification_scope"])
        self.assertIn("no_destructive_commands", task.parameters["safety_gates"])
        self.assertTrue(task.parameters["requires_regression_test"])
        self.assertIn("add_regression_test", task.plan)

    def test_repair_task_clears_page_classification_context(self):
        context = ContextSession()
        detect_task_intent(
            "\u041e\u0442\u043a\u0440\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 "
            "\u0438 \u041d\u0415 \u043f\u0430\u0440\u0441\u0438 \u0441\u0440\u0430\u0437\u0443. "
            "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438 task_type",
            context=context,
        )

        task = detect_task_intent(
            "\u043f\u043e\u0447\u0438\u043d\u0438 \u043e\u0448\u0438\u0431\u043a\u0443: "
            "\u0430\u0433\u0435\u043d\u0442 \u043d\u0435\u0432\u0435\u0440\u043d\u043e "
            "\u043f\u043e\u043d\u044f\u043b page_structure",
            context=context,
        )

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertIsNone(context.active_intent)

    def test_short_agent_error_becomes_repair_not_search(self):
        task = detect_task_intent("\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431\u0441\u044f")

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertIsNone(task.query)

    def test_short_agent_error_inherits_previous_scraping_context(self):
        context = ContextSession()
        scraping_task = detect_task_intent(
            "\u0441\u043f\u0430\u0440\u0441\u0438 \u044d\u0442\u043e: "
            "https://www.fl.ru/projects/5504773/parsing-sayta-zolotoe-yabloko-deklaratsii-sootvetstviya.html",
            context=context,
        )
        context.remember_failure(
            scraping_task,
            error_text=(
                "No product records were extracted.; "
                "Field 'title' is empty for all records.; "
                "Field 'price' is empty for all records."
            ),
            error_type="ScrapingError",
        )

        task = detect_task_intent("\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431\u0441\u044f", context=context)

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertEqual(
            task.target_url,
            "https://www.fl.ru/projects/5504773/parsing-sayta-zolotoe-yabloko-deklaratsii-sootvetstviya.html",
        )
        self.assertEqual(task.parameters["previous_task_type"], TaskType.SCRAPING.value)
        self.assertEqual(task.parameters["previous_domain_task_type"], "freelance_project")
        self.assertEqual(task.parameters["previous_entity_type"], "project")
        self.assertEqual(task.parameters["failure_area"], "parser")
        self.assertEqual(task.parameters["last_error_type"], "ScrapingError")
        self.assertIn("No product records", task.parameters["last_error_text"])
        self.assertIn("empty_extraction", task.parameters["evidence_types"])
        self.assertIn("Field 'title' is empty for all records.", task.parameters["last_validation_warnings"])
        self.assertFalse(task.parameters["requires_full_tests"])
        self.assertTrue(task.parameters["requires_live_smoke"])
        self.assertIn("network_requires_safe_live_smoke_or_user_approval", task.parameters["safety_gates"])

    def test_repair_task_professional_risk_metadata_for_shared_context_bug(self):
        task = detect_task_intent(
            "\u043f\u043e\u0447\u0438\u043d\u0438: \u0430\u0433\u0435\u043d\u0442 "
            "\u043d\u0435\u0432\u0435\u0440\u043d\u043e \u043f\u043e\u043d\u044f\u043b page_structure "
            "\u0438 task_type, pytest failed"
        )

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertEqual(task.parameters["failure_area"], "page_structure")
        self.assertEqual(task.parameters["severity"], "high")
        self.assertEqual(task.parameters["blast_radius"], "shared")
        self.assertIn("failing_test", task.parameters["evidence_types"])
        self.assertIn("full_test_suite", task.parameters["verification_scope"])
        self.assertTrue(task.parameters["requires_full_tests"])

    def test_html_change_protection_requirement_is_not_repair(self):
        task = detect_task_intent(
            "\u041f\u0440\u043e\u0430\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u0439 "
            "\u0441\u0430\u0439\u0442 https://books.toscrape.com/\n"
            "- title\n- price\n"
            "\u0434\u043e\u0431\u0430\u0432\u044c \u0437\u0430\u0449\u0438\u0442\u0443 "
            "\u043e\u0442 \u043f\u0430\u0434\u0435\u043d\u0438\u044f "
            "\u043f\u0440\u0438 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0438 HTML"
        )

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertIsNone(task.output)


if __name__ == "__main__":
    unittest.main()
