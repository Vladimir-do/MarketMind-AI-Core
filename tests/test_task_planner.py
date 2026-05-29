import unittest

from app.task_intents import TaskType, detect_task_intent
from app.task_planner import SkillRegistry, SkillStatus, TaskPlanner, default_skills


class TaskPlannerTests(unittest.TestCase):
    def test_first_page_scraping_plan_is_executable_with_csv_export(self):
        task = detect_task_intent(
            """Analyze site https://books.toscrape.com/

Need collect:
- title
- price

Result: save to CSV.
Requirements:
- logging
- delay between requests
"""
        )
        plan = TaskPlanner().build_plan(task)

        self.assertTrue(plan.executable)
        self.assertEqual([step.skill_id for step in plan.steps], [
            "scraping.manual_plan",
            "scraping.fetch_pages",
            "scraping.extract_products",
            "scraping.validate_result",
            "csv.export",
            "quality.self_critic",
        ])
        self.assertEqual(plan.missing_skills, [])
        self.assertIn("Поля отделены от требований", plan.self_critic)

    def test_scraping_plan_keeps_self_critic_last_and_adds_csv_export(self):
        task = detect_task_intent(
            """Спарси https://books.toscrape.com/
собери_все_книги
- title
- price
- availability
- rating
- product_url
CSV
"""
        )

        plan = TaskPlanner().build_plan(task)

        self.assertEqual(task.parameters["scope"], "all_pages")
        self.assertEqual([step.skill_id for step in plan.steps], [
            "scraping.manual_plan",
            "scraping.fetch_pages",
            "pagination.detect",
            "scraping.extract_products",
            "scraping.validate_result",
            "csv.export",
            "quality.self_critic",
        ])
        self.assertTrue(plan.executable)
        self.assertEqual(plan.missing_skills, [])

    def test_marketplace_search_plan_is_executable(self):
        task = detect_task_intent("найди держатель для телефона")
        plan = TaskPlanner().build_plan(task)

        self.assertEqual(task.type, TaskType.MARKETPLACE_SEARCH)
        self.assertTrue(plan.executable)
        self.assertEqual(plan.steps[0].skill_id, "market.search")
        self.assertEqual(plan.steps[0].status, SkillStatus.AVAILABLE)

    def test_card_generation_plan_uses_existing_card_skill(self):
        task = detect_task_intent("составь карточку для кусачки маникюрные цена 499")
        plan = TaskPlanner().build_plan(task)

        self.assertTrue(plan.executable)
        self.assertEqual([step.skill_id for step in plan.steps], ["ozon.card.generate", "quality.self_critic"])

    def test_page_classification_training_plan_is_explicit(self):
        task = detect_task_intent("Открой страницу и НЕ парси сразу. Сначала определи task_type page_structure confidence")
        plan = TaskPlanner().build_plan(task)

        self.assertEqual(task.type, TaskType.PAGE_CLASSIFICATION_TRAINING)
        self.assertTrue(plan.executable)
        self.assertEqual([step.skill_id for step in plan.steps], ["page.classification.training"])


    def test_repair_plan_uses_regression_first_pipeline(self):
        task = detect_task_intent(
            "\u0438\u0441\u043f\u0440\u0430\u0432\u044c \u043e\u0448\u0438\u0431\u043a\u0443: "
            "\u0430\u0433\u0435\u043d\u0442 \u043d\u0435 \u0441\u043f\u0430\u0440\u0441\u0438\u043b BooksToScrape"
        )
        plan = TaskPlanner().build_plan(task)

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertTrue(plan.executable)
        self.assertEqual([step.skill_id for step in plan.steps], [
            "repair.reproduce",
            "repair.classify",
            "repair.regression_test",
            "repair.implement_fix",
            "repair.verify",
            "repair.skillpack_update",
            "quality.self_critic",
        ])
        self.assertIn("Severity, evidence types, blast radius and safety gates are explicit", plan.self_critic)
        self.assertIn("Regression test protects the repaired behavior", plan.self_critic)

    def test_registry_loads_runtime_skills_from_skill_manifests(self):
        registry = SkillRegistry(skills=[])

        csv_export = registry.get("csv.export")
        page_training = registry.get("page.classification.training")

        self.assertEqual(csv_export.title, "CSV Export")
        self.assertEqual(csv_export.status, SkillStatus.AVAILABLE)
        self.assertEqual(page_training.title, "Page Classification Training")
        self.assertEqual(page_training.status, SkillStatus.AVAILABLE)

    def test_default_skills_are_empty_after_manifest_migration(self):
        self.assertEqual(default_skills(), [])


if __name__ == "__main__":
    unittest.main()
