import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.bot import (
    _build_card_task_from_url,
    _collect_batch_card_sources_from_tasks,
    _mask_proxy_url,
    _split_card_and_other_tasks,
    _split_batch_card_sources,
    build_repair_diagnostic_report,
    build_scraping_preflight_decision,
    build_unhandled_message_response,
    extract_command_payload,
    extract_urls,
    format_scraping_preflight_decision,
    parse_natural_request,
    split_natural_tasks,
    validate_search_query,
)
from app.task_intents import ContextSession, StructuredTask, TaskType, detect_task_intent
from app.telegram_messages import command_limit


class BotHelperTests(unittest.TestCase):
    def test_mask_proxy_url_hides_credentials(self):
        masked = _mask_proxy_url("http://user:secret@127.0.0.1:8080")
        self.assertEqual(masked, "http://***@127.0.0.1:8080")

    def test_mask_proxy_url_keeps_host_for_plain_proxy(self):
        masked = _mask_proxy_url("socks5://10.0.0.2:1080")
        self.assertEqual(masked, "socks5://10.0.0.2:1080")

    def test_mask_proxy_url_returns_not_set_for_empty(self):
        self.assertEqual(_mask_proxy_url(""), "не задан")

    def test_validate_search_query_accepts_plain_text(self):
        ok, message = validate_search_query("держатель для телефона")
        self.assertTrue(ok)
        self.assertIsNone(message)

    def test_validate_search_query_rejects_funpay_url(self):
        ok, message = validate_search_query("https://funpay.com/lots/offer?id=68683803")
        self.assertFalse(ok)
        self.assertIn("неподдерживаемый сайт", message)
        self.assertIn("funpay.com", message)

    def test_validate_search_query_rejects_marketplace_url_for_search(self):
        ok, message = validate_search_query("https://www.ozon.ru/product/test")
        self.assertFalse(ok)
        self.assertIn("/add", message)

    def test_validate_search_query_rejects_yandex_market_url_for_search(self):
        ok, message = validate_search_query("https://market.yandex.ru/product--phone/123")
        self.assertFalse(ok)
        self.assertIn("/add", message)

    def test_parse_natural_request_routes_short_agent_error_to_repair(self):
        intent, payload = parse_natural_request("\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431\u0441\u044f")

        self.assertEqual(intent, "repair_task")
        self.assertEqual(payload.type, TaskType.REPAIR)
        self.assertIsNone(payload.query)

    def test_extract_urls_strips_common_trailing_punctuation(self):
        urls = extract_urls("check this (https://funpay.com/lots/offer?id=68683803).")
        self.assertEqual(urls, ["https://funpay.com/lots/offer?id=68683803"])

    def test_extract_command_payload_accepts_inline_search_query(self):
        payload = extract_command_payload("/search держатель для телефона", "search")
        self.assertEqual(payload, "держатель для телефона")

    def test_extract_command_payload_accepts_bot_mention(self):
        payload = extract_command_payload("/search@price_bot держатель для телефона", "search")
        self.assertEqual(payload, "держатель для телефона")

    def test_extract_command_payload_returns_empty_without_inline_text(self):
        self.assertEqual(extract_command_payload("/search", "search"), "")

    def test_command_limit_accepts_bot_mention_and_clamps(self):
        self.assertEqual(command_limit("/metrics@price_bot 99", "metrics", max_limit=30), 30)
        self.assertEqual(command_limit("/metrics bad", "metrics", default=7), 7)

    def test_run_search_query_releases_lock_when_ai_advice_fails(self):
        import app.bot as bot_module

        class FakeMessage:
            chat = type("Chat", (), {"id": 1})()

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            if bot_module.parser_lock.locked():
                bot_module.parser_lock.release()
            message = FakeMessage()
            state = AsyncMock()
            with patch.object(bot_module.agent, "search_advice", AsyncMock(side_effect=RuntimeError("ai down"))):
                await bot_module.run_search_query(message, state, "держатель для телефона", natural=True)
            return message

        message = asyncio.run(run())

        self.assertFalse(bot_module.parser_lock.locked())
        self.assertTrue(any("ai down" in answer for answer in message.answers))

    def test_split_batch_sources_extracts_multiple_urls_from_one_line(self):
        sources = _split_batch_card_sources(
            "составь карточки: https://www.ozon.ru/product/one/, https://www.ozon.ru/product/two/"
        )
        self.assertEqual(sources, ["https://www.ozon.ru/product/one/", "https://www.ozon.ru/product/two/"])

    def test_split_natural_tasks_preserves_multiple_user_commands(self):
        tasks = split_natural_tasks(
            "составь карточку для коврика для йоги цена 1200.\n"
            "Проанализируй конкурентов для ковриков для йоги.\n"
            "Собери карточку для кусачки маникюрные цена 499."
        )
        self.assertEqual(tasks, [
            "составь карточку для коврика для йоги цена 1200",
            "Проанализируй конкурентов для ковриков для йоги",
            "Собери карточку для кусачки маникюрные цена 499",
        ])

        intents = [parse_natural_request(task)[0] for task in tasks]
        self.assertEqual(intents, ["ozon_card", "card_research", "ozon_card"])

    def test_split_natural_tasks_keeps_multiline_scraping_spec_as_one_task(self):
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
        tasks = split_natural_tasks(prompt)

        self.assertEqual(tasks, [prompt.strip()])
        intent, payload = parse_natural_request(tasks[0])
        self.assertEqual(intent, "scraping_task")
        self.assertIsInstance(payload, StructuredTask)
        self.assertEqual(payload.type, TaskType.SCRAPING)
        self.assertEqual(payload.fields, ["title", "price", "availability", "rating", "product_url"])

    def test_split_natural_tasks_keeps_training_prompt_as_one_task(self):
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
        tasks = split_natural_tasks(prompt)

        self.assertEqual(tasks, [prompt.strip()])
        intent, payload = parse_natural_request(tasks[0])
        self.assertEqual(intent, "page_classification_training")
        self.assertIsInstance(payload, StructuredTask)
        self.assertEqual(payload.type, TaskType.PAGE_CLASSIFICATION_TRAINING)
        self.assertEqual(payload.target_url, "https://books.toscrape.com/")

    def test_training_protocol_fragments_do_not_become_search(self):
        for fragment in ("Верни:", "- task_type", "- page_structure", "- confidence", "- warnings"):
            intent, payload = parse_natural_request(fragment)

            self.assertEqual(intent, "unknown")
            self.assertIsNone(payload)

    def test_training_prompt_response_does_not_use_ozon_search(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeChat:
            id = 456

        class FakeMessage:
            from_user = FakeUser()
            chat = FakeChat()
            text = (
                "Открой страницу и НЕ парси сразу.\n\n"
                "Сначала определи:\n"
                "- task_type\n"
                "- page_structure\n"
                "- confidence\n\n"
                "Верни:\n"
                "- status\n"
                "- warnings\n"
            )

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            message = FakeMessage()
            state = AsyncMock()
            with patch.object(bot_module, "handle_natural_search", AsyncMock()) as search:
                await bot_module.handle_unhandled_message(message, state)
            return message, search

        message, search = asyncio.run(run())

        search.assert_not_awaited()
        self.assertEqual(len(message.answers), 1)
        self.assertIn("Принял 1 задачу", message.answers[0])
        self.assertIn("Намерение: page_classification_training", message.answers[0])
        self.assertIn("Статус: нужен URL страницы для анализа", message.answers[0])

    def test_context_url_continues_page_classification_training(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeChat:
            id = 789

        class FakeMessage:
            from_user = FakeUser()
            chat = FakeChat()
            text = "https://example.com/menu"

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            context = ContextSession()
            training_task = detect_task_intent(
                "Открой страницу и НЕ парси сразу.\n\n"
                "Сначала определи:\n"
                "- task_type\n"
                "- page_structure\n"
                "- confidence"
            )
            context.remember(training_task)
            bot_module.CHAT_CONTEXTS[FakeChat.id] = context
            message = FakeMessage()
            state = AsyncMock()
            with (
                patch.object(bot_module, "classify_page_before_parsing", AsyncMock(return_value="classified")) as classify,
                patch.object(bot_module, "handle_scraping_task", AsyncMock()) as scraping,
                patch.object(bot_module, "handle_natural_add_urls", AsyncMock()) as add_urls,
                patch.object(bot_module, "handle_natural_search", AsyncMock()) as search,
            ):
                await bot_module.handle_unhandled_message(message, state)
            return message, context, classify, scraping, add_urls, search

        message, context, classify, scraping, add_urls, search = asyncio.run(run())

        classify.assert_awaited_once_with("https://example.com/menu")
        scraping.assert_not_awaited()
        add_urls.assert_not_awaited()
        search.assert_not_awaited()
        self.assertEqual(message.answers, ["classified"])
        self.assertIsNone(context.active_intent)
        self.assertIsNone(context.status)

    def test_scrape_command_with_url_resets_page_classification_training(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeChat:
            id = 790

        class FakeMessage:
            from_user = FakeUser()
            chat = FakeChat()
            text = (
                "\u0441\u043f\u0430\u0440\u0441\u0438 \u0446\u0435\u043d\u044b \u043d\u0430 \u0448\u0430\u0448\u043b\u044b\u043a "
                "\u0438 \u043c\u044f\u0441\u043d\u044b\u0435 \u0431\u043b\u044e\u0434\u0430: https://chibbis.ru/orsk/restaurants"
            )

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            context = ContextSession()
            training_task = detect_task_intent(
                "\u041e\u0442\u043a\u0440\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u0438 \u041d\u0415 \u043f\u0430\u0440\u0441\u0438 \u0441\u0440\u0430\u0437\u0443.\n\n"
                "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438:\n"
                "- task_type\n"
                "- page_structure\n"
                "- confidence"
            )
            context.remember(training_task)
            bot_module.CHAT_CONTEXTS[FakeChat.id] = context
            message = FakeMessage()
            state = AsyncMock()
            with (
                patch.object(bot_module, "classify_page_before_parsing", AsyncMock(return_value="classified")) as classify,
                patch.object(bot_module, "handle_scraping_task", AsyncMock()) as scraping,
            ):
                await bot_module.handle_unhandled_message(message, state)
            return context, classify, scraping

        context, classify, scraping = asyncio.run(run())

        classify.assert_not_awaited()
        scraping.assert_awaited_once()
        self.assertIsNone(context.active_intent)

    def test_classify_page_before_parsing_reports_books_catalog(self):
        import app.bot as bot_module

        html = """
        <html>
          <head><title>Travel | Books to Scrape</title></head>
          <body>
            <article class="product_pod">
              <h3><a href="../../../its-only-the-himalayas_981/index.html">It's Only the Himalayas</a></h3>
              <p class="price_color">£45.17</p>
            </article>
            <article class="product_pod">
              <h3><a href="../../../full-moon-over-noahs-ark_811/index.html">Full Moon over Noah's Ark</a></h3>
              <p class="price_color">£49.43</p>
            </article>
            <article class="product_pod">
              <h3><a href="../../../see-america_732/index.html">See America</a></h3>
              <p class="price_color">£48.87</p>
            </article>
            <ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
          </body>
        </html>
        """

        async def run():
            with patch.object(bot_module, "fetch_html", AsyncMock(return_value=(200, html))):
                return await bot_module.classify_page_before_parsing(
                    "https://books.toscrape.com/catalogue/category/books/travel_2/index.html"
                )

        response = asyncio.run(run())

        self.assertIn("task_type: universal_catalog", response)
        self.assertIn("page_structure: catalog", response)
        self.assertIn("Намерение: page_classification_training", response)
        self.assertIn("Действие: classify_page_before_parsing", response)
        self.assertIn("Почему так решил:", response)
        confidence = float(response.split("confidence: ", 1)[1].splitlines()[0])
        self.assertGreaterEqual(confidence, 0.85)

    def test_scraping_preflight_blocks_article_without_product_schema(self):
        task = detect_task_intent(
            "\u0441\u043f\u0430\u0440\u0441\u0438 \u044d\u0442\u043e: "
            "https://www.fl.ru/projects/5504773/parsing-sayta-zolotoe-yabloko-deklaratsii-sootvetstviya.html"
        )
        html_text = """
        <html>
          <head><title>Parsing project</title></head>
          <body>
            <article>
              <h1>Parsing site Zolotoe Yabloko declarations</h1>
              <time datetime="2026-05-22">22 May 2026</time>
              <p>Need scrape declaration pages and collect documents.</p>
              <p>Budget and freelancer discussion are project text, not product cards.</p>
            </article>
          </body>
        </html>
        """

        decision = build_scraping_preflight_decision(task, html_text, http_status=200)
        response = format_scraping_preflight_decision(decision)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.domain_task_type, "freelance_project")
        self.assertEqual(decision.page_structure, "article")
        self.assertEqual(decision.next_strategy, "inspect_structure")
        self.assertIn("skip_generic_scraping", response)
        self.assertIn("domain_task_type: <code>freelance_project</code>", response)
        self.assertIn("page_structure: <code>article</code>", response)

    def test_scraping_preflight_allows_unknown_js_with_browser_fetcher(self):
        task = detect_task_intent(
            "\u0441\u043f\u0430\u0440\u0441\u0438 \u0446\u0435\u043d\u044b \u043d\u0430 \u0448\u0430\u0448\u043b\u044b\u043a: "
            "https://chibbis.ru/orsk/restaurants"
        )
        html_text = """
        <html><body>
          <main>
            <h1>Restaurants</h1>
            <div id="app">Menu and delivery data are loading...</div>
          </main>
        </body></html>
        """

        decision = build_scraping_preflight_decision(task, html_text, http_status=200)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.domain_task_type, "restaurant_menu")
        self.assertEqual(decision.page_structure, "unknown_js")
        self.assertEqual(decision.next_strategy, "browser")
        self.assertEqual(decision.fetcher, "browser")

    def test_scraping_preflight_blocks_api_source_before_html_product_scraping(self):
        task = detect_task_intent("collect data from https://jsonplaceholder.typicode.com/posts")
        html_text = """
        <html><body><pre>[{"id": 1, "title": "hello"}]</pre></body></html>
        """

        decision = build_scraping_preflight_decision(task, html_text, http_status=200)
        response = format_scraping_preflight_decision(decision)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.domain_task_type, "api_source")
        self.assertEqual(decision.next_strategy, "api")
        self.assertIn("task_type=api_source", decision.reason)
        self.assertIn("skip_generic_scraping", response)

    def test_handle_scraping_task_records_preflight_block_in_failure_memory(self):
        import app.bot as bot_module

        class FakeChat:
            id = 125

        class FakeMessage:
            chat = FakeChat()

            def __init__(self):
                self.answers = []
                self.documents = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

            async def answer_document(self, document, **kwargs):
                self.documents.append((document, kwargs))

        article_html = """
        <html>
          <body>
            <article>
              <h1>Parsing site Zolotoe Yabloko declarations</h1>
              <time datetime="2026-05-22">22 May 2026</time>
              <p>This is a project brief, not a product catalog.</p>
            </article>
          </body>
        </html>
        """

        async def run():
            if bot_module.parser_lock.locked():
                bot_module.parser_lock.release()
            bot_module.CHAT_CONTEXTS.pop(FakeChat.id, None)
            task = detect_task_intent(
                "\u0441\u043f\u0430\u0440\u0441\u0438 \u044d\u0442\u043e: "
                "https://www.fl.ru/projects/5504773/parsing-sayta-zolotoe-yabloko-deklaratsii-sootvetstviya.html"
            )
            message = FakeMessage()
            with (
                patch.object(bot_module, "fetch_html", AsyncMock(return_value=(200, article_html))),
                patch("app.generic_scraper.run_scraping_task", AsyncMock()) as scraper,
            ):
                await bot_module.handle_scraping_task(message, task)
            return message, scraper, bot_module.get_chat_context(FakeChat.id)

        message, scraper, context = asyncio.run(run())

        scraper.assert_not_awaited()
        self.assertFalse(message.documents)
        self.assertTrue(any("page_structure: <code>article</code>" in answer for answer in message.answers))
        self.assertIsNotNone(context.last_failure)
        self.assertEqual(context.last_failure.error_type, "ScrapingPreflightBlocked")

    def test_handle_scraping_task_sets_browser_fallback_after_unknown_js_preflight(self):
        import app.bot as bot_module
        from app.generic_scraper import ScrapeMetrics, ScrapeResult

        class FakeChat:
            id = 126

        class FakeMessage:
            chat = FakeChat()

            def __init__(self):
                self.answers = []
                self.documents = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

            async def answer_document(self, document, **kwargs):
                self.documents.append((document, kwargs))

        loading_html = """
        <html><body>
          <main>
            <h1>Restaurants</h1>
            <div id="app">Menu and delivery data are loading...</div>
          </main>
        </body></html>
        """

        async def fake_run_scraping_task(task):
            self.assertTrue(task.parameters["browser_fallback"])
            self.assertEqual(task.parameters["next_strategy"], "browser")
            return ScrapeResult(
                records=[{"title": "Rendered dish", "price": "450"}],
                fields=["title", "price"],
                csv_bytes=b"title,price\nRendered dish,450\n",
                filename="rendered.csv",
                metrics=ScrapeMetrics(
                    url=task.target_url or "",
                    http_status=200,
                    bytes_received=128,
                    records=1,
                    pages_fetched=1,
                ),
            )

        async def run():
            if bot_module.parser_lock.locked():
                bot_module.parser_lock.release()
            bot_module.CHAT_CONTEXTS.pop(FakeChat.id, None)
            task = detect_task_intent(
                "\u0441\u043f\u0430\u0440\u0441\u0438 \u0446\u0435\u043d\u044b \u043d\u0430 \u0448\u0430\u0448\u043b\u044b\u043a: "
                "https://chibbis.ru/orsk/restaurants"
            )
            message = FakeMessage()
            with (
                patch.object(bot_module, "fetch_html", AsyncMock(return_value=(200, loading_html))),
                patch("app.generic_scraper.run_scraping_task", AsyncMock(side_effect=fake_run_scraping_task)) as scraper,
            ):
                await bot_module.handle_scraping_task(message, task)
            return message, scraper

        message, scraper = asyncio.run(run())

        scraper.assert_awaited_once()
        self.assertTrue(message.documents)
        self.assertTrue(any("fetcher: <code>browser</code>" in answer for answer in message.answers))

    def test_training_responses_use_russian_labels(self):
        import app.bot as bot_module

        task = StructuredTask(
            TaskType.SCRAPING,
            raw_text="Спарси https://books.toscrape.com/",
            target_url="https://books.toscrape.com/",
            fields=["title", "price"],
            output="csv",
            confidence=0.9,
        )

        response = bot_module.format_structured_task_plan(task)

        self.assertIn("План выполнения", response)
        self.assertIn("План", response)
        self.assertNotIn("Pipeline", response)
        self.assertNotIn("Self-check", response)
        self.assertNotIn("executor", response)

    def test_unhandled_message_dispatches_contextual_scraping_followup_without_splitting(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeChat:
            id = 123

        class FakeMessage:
            from_user = FakeUser()
            chat = FakeChat()
            text = (
                "Открой каждую карточку книги и дополнительно собери:\n"
                "- UPC\n"
                "- product_type\n"
                "- tax\n"
                "- number_of_reviews\n"
                "- description"
            )

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            context = ContextSession()
            detect_task_intent(
                "Analyze site https://books.toscrape.com/\n"
                "title\nprice\navailability\nrating\nproduct_url\n"
                "Result: CSV\npagination",
                context=context,
            )
            bot_module.CHAT_CONTEXTS[FakeChat.id] = context
            message = FakeMessage()
            state = AsyncMock()
            with patch.object(bot_module, "handle_scraping_task", AsyncMock()) as scraping:
                await bot_module.handle_unhandled_message(message, state)
            return message, scraping

        message, scraping = asyncio.run(run())

        scraping.assert_awaited_once()
        task = scraping.await_args.args[1]
        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertIn("upc", task.fields)
        self.assertIn("number_of_reviews", task.fields)
        self.assertFalse(any("Принял задач" in answer for answer in message.answers))

    def test_unhandled_short_agent_error_does_not_fall_back_to_ozon_search(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeChat:
            id = 124

        class FakeMessage:
            from_user = FakeUser()
            chat = FakeChat()
            text = "\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431\u0441\u044f"

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            context = ContextSession()
            scraping_task = detect_task_intent(
                "\u0441\u043f\u0430\u0440\u0441\u0438 \u044d\u0442\u043e: "
                "https://www.fl.ru/projects/5504773/parsing-sayta-zolotoe-yabloko-deklaratsii-sootvetstviya.html",
                context=context,
            )
            context.remember_failure(
                scraping_task,
                error_text="No product records were extracted.; Field 'title' is empty for all records.",
                error_type="ScrapingError",
            )
            bot_module.CHAT_CONTEXTS[FakeChat.id] = context
            message = FakeMessage()
            state = AsyncMock()
            with patch.object(bot_module, "handle_natural_search", AsyncMock()) as search:
                await bot_module.handle_unhandled_message(message, state)
            return message, search

        message, search = asyncio.run(run())

        search.assert_not_awaited()
        self.assertEqual(len(message.answers), 2)
        self.assertIn("repair", message.answers[0])
        self.assertIn("failure_area", message.answers[0])
        self.assertIn("last_error_text", message.answers[0])
        self.assertIn("No product records", message.answers[0])
        self.assertIn("Repair diagnostics", message.answers[1])
        self.assertIn("suggested_tests", message.answers[1])

    def test_repair_diagnostic_report_suggests_parser_tests(self):
        task = detect_task_intent(
            "\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431\u0441\u044f\n"
            "No product records were extracted."
        )

        report = build_repair_diagnostic_report(task)

        self.assertIn("Repair diagnostics", report)
        self.assertIn("tests/test_generic_scraper.py", report)
        self.assertIn("python project_skills/validate_skills.py", report)

    def test_split_natural_tasks_keeps_url_requirements_bullets_as_one_task(self):
        prompt = """Проанализируй сайт https://books.toscrape.com/

Обязательно:
- логирование
- обработка ошибок
- задержка между запросами
"""
        self.assertEqual(split_natural_tasks(prompt), [prompt.strip()])

    def test_split_natural_tasks_keeps_url_numbered_requirements_as_one_task(self):
        prompt = """Задача: собрать данные с https://books.toscrape.com/

1. Не менять сайт.
2. Сохранить результат в CSV.
3. Отчитаться об ошибках.
"""
        self.assertEqual(split_natural_tasks(prompt), [prompt.strip()])

    def test_collects_many_card_tasks_into_one_batch(self):
        tasks = [f"составь карточку для товар {i} цена {100 + i}" for i in range(100)]
        sources = _collect_batch_card_sources_from_tasks(tasks)

        self.assertIsNotNone(sources)
        self.assertEqual(len(sources), 100)
        self.assertEqual(sources[0], "товар 0 цена 100")
        self.assertEqual(sources[-1], "товар 99 цена 199")

    def test_does_not_batch_mixed_task_types(self):
        sources = _collect_batch_card_sources_from_tasks([
            "составь карточку для коврик для йоги цена 1200",
            "проанализируй конкурентов для ковриков для йоги",
        ])

        self.assertIsNone(sources)

    def test_splits_mixed_tasks_into_card_batch_and_other_tasks(self):
        card_sources, other_tasks = _split_card_and_other_tasks([
            "составь карточку для коврика для йоги цена 1200",
            "Проанализируй конкурентов для ковриков для йоги",
            "Собери карточку для кусачки маникюрные цена 499",
        ])

        self.assertEqual(card_sources, [
            "коврика для йоги цена 1200",
            "кусачки маникюрные цена 499",
        ])
        self.assertEqual(other_tasks, ["Проанализируй конкурентов для ковриков для йоги"])

    def test_build_card_task_from_ozon_url_uses_slug_as_title(self):
        task = _build_card_task_from_url(
            "https://www.ozon.ru/product/avm-center-kabel-dlya-mobilnyh-ustroystv-usb-type-c-apple-lightning-micro-usb-2-0-type-b-1-m-siniy-904750846/"
        )
        self.assertIn("товар: Avm center kabel dlya mobilnyh ustroystv usb type c", task)
        self.assertIn("Данные восстановлены из ссылки", task)

    def test_unhandled_funpay_url_gets_unsupported_site_response(self):
        message = build_unhandled_message_response("https://funpay.com/lots/offer?id=68683803")
        self.assertIsNotNone(message)
        self.assertIn("funpay.com", message)
        self.assertIn("/search", message)

    def test_unhandled_marketplace_url_suggests_add(self):
        message = build_unhandled_message_response("https://www.ozon.ru/product/test")
        self.assertIsNotNone(message)
        self.assertIn("/add", message)

    def test_unhandled_plain_text_suggests_known_commands(self):
        message = build_unhandled_message_response("hello")
        self.assertIsNotNone(message)
        self.assertIn("/search", message)
        self.assertIn("/add", message)

    def test_help_menu_exposes_adaptive_diagnostics(self):
        from app.bot import HELP_TEXT, TELEGRAM_COMMANDS

        self.assertIn("/metrics", HELP_TEXT)
        self.assertIn("/blocks", HELP_TEXT)
        self.assertIn("/health", HELP_TEXT)
        self.assertIn("/skill_note", HELP_TEXT)
        commands = {command.command for command in TELEGRAM_COMMANDS}
        self.assertIn("metrics", commands)
        self.assertIn("blocks", commands)
        self.assertIn("health", commands)
        self.assertIn("skill_note", commands)
        self.assertIn("skill_pending", commands)

    def test_skill_note_command_creates_pending_proposal(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeMessage:
            from_user = FakeUser()
            text = "/skill_note router должен помнить training prompt"

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            message = FakeMessage()
            fake_path = Path("D:/LLM/parser_agent/project_skills/session_updates/test.yaml")
            proposal = type("Proposal", (), {"path": fake_path, "proposed_id": "router-training"})()
            with patch.object(bot_module, "create_skill_note_proposal", return_value=proposal) as create:
                await bot_module.cmd_skill_note(message)
            return message, create

        message, create = asyncio.run(run())

        create.assert_called_once()
        self.assertIn("Создал pending skill proposal", message.answers[0])
        self.assertIn("router-training", message.answers[0])

    def test_skill_pending_lists_pending_proposals(self):
        import app.bot as bot_module

        class FakeUser:
            id = 956343475

        class FakeMessage:
            from_user = FakeUser()

            def __init__(self):
                self.answers = []

            async def answer(self, text, **kwargs):
                self.answers.append(text)

        async def run():
            message = FakeMessage()
            path = Path("D:/LLM/parser_agent/project_skills/session_updates/test.yaml")
            with patch.object(bot_module, "list_pending_skill_proposals", return_value=[path]):
                await bot_module.cmd_skill_pending(message)
            return message

        message = asyncio.run(run())

        self.assertIn("Pending skill proposals", message.answers[0])
        self.assertIn("project_skills", message.answers[0])

    def test_natural_request_adds_marketplace_url(self):
        intent, payload = parse_natural_request("добавь https://www.ozon.ru/product/test")
        self.assertEqual(intent, "add_urls")
        self.assertEqual(payload, ["https://www.ozon.ru/product/test"])

    def test_natural_request_builds_card_from_marketplace_url(self):
        intent, payload = parse_natural_request("составь карточку на этот товар: https://www.ozon.ru/product/test")
        self.assertEqual(intent, "ozon_card_urls")
        self.assertEqual(payload, ["https://www.ozon.ru/product/test"])

    def test_natural_request_understands_batch_cards_with_urls(self):
        intent, payload = parse_natural_request("сделай пачку карточек\nhttps://www.ozon.ru/product/test")
        self.assertEqual(intent, "ozon_batch_cards")
        self.assertIn("https://www.ozon.ru/product/test", payload)

    def test_natural_request_routes_multiple_card_urls_to_batch(self):
        intent, payload = parse_natural_request(
            "составь карточки на это: https://www.ozon.ru/product/one/, "
            "https://www.ozon.ru/product/two/"
        )
        self.assertEqual(intent, "ozon_batch_cards")
        self.assertIn("https://www.ozon.ru/product/one/", payload)
        self.assertIn("https://www.ozon.ru/product/two/", payload)

    def test_natural_request_prompts_for_batch_cards(self):
        intent, payload = parse_natural_request("сделай пачку карточек")
        self.assertEqual(intent, "ozon_batch_prompt")
        self.assertIsNone(payload)

    def test_natural_request_understands_update(self):
        intent, payload = parse_natural_request("обнови цены")
        self.assertEqual(intent, "update")
        self.assertIsNone(payload)

    def test_natural_request_understands_search_prefix(self):
        intent, payload = parse_natural_request("найди держатель для телефона")
        self.assertEqual(intent, "search")
        self.assertEqual(payload, "держатель для телефона")

    def test_natural_request_understands_card_for_last_product(self):
        intent, payload = parse_natural_request("сделай карточку последнего товара")
        self.assertEqual(intent, "make_card_last")
        self.assertIsNone(payload)

    def test_natural_request_understands_card_task(self):
        intent, payload = parse_natural_request("собери карточку для кусачки маникюрные цена 499")
        self.assertEqual(intent, "ozon_card")
        self.assertEqual(payload, "кусачки маникюрные цена 499")

    def test_natural_request_combines_competitor_query_and_card_price(self):
        intent, payload = parse_natural_request(
            "Проанализируй конкурентов для ковриков для йоги и набросай карточку для моего товара за 1200р"
        )
        self.assertEqual(intent, "ozon_card")
        self.assertEqual(payload, "товар: ковриков для йоги\nцена: 1200")

    def test_natural_request_understands_sostav_card_task(self):
        intent, payload = parse_natural_request("составь карточку для кусачки маникюрные")
        self.assertEqual(intent, "ozon_card")
        self.assertEqual(payload, "кусачки маникюрные")

    def test_natural_request_prompts_for_card_task_without_payload(self):
        intent, payload = parse_natural_request("сделай ozon_card")
        self.assertEqual(intent, "ozon_card_prompt")
        self.assertIsNone(payload)

    def test_natural_request_prompts_for_vague_card_reference(self):
        intent, payload = parse_natural_request("составь карточку на этот товар")
        self.assertEqual(intent, "ozon_card_prompt")
        self.assertIsNone(payload)

    def test_natural_request_prompts_for_vague_card_reference_with_price(self):
        intent, payload = parse_natural_request("набросай карточку для моего товара за 1200р")
        self.assertEqual(intent, "ozon_card_prompt")
        self.assertIsNone(payload)

    def test_natural_request_understands_competitor_research(self):
        intent, payload = parse_natural_request("проанализируй конкурентов для кусачек")
        self.assertEqual(intent, "card_research")
        self.assertEqual(payload, "кусачек")
