import unittest

from app.agent_loop import AgentLoopStage, build_agent_loop, should_fallback, stage_label_ru
from app.task_intents import TaskType, detect_task_intent


class AgentLoopTests(unittest.TestCase):
    def test_scraping_loop_orders_classify_strategy_execute_confidence_fallback_experience(self):
        task = detect_task_intent(
            """Scrape https://books.toscrape.com/
- title
- price
CSV
"""
        )

        plan = build_agent_loop(task)

        self.assertEqual(task.type, TaskType.SCRAPING)
        self.assertEqual(
            plan.stage_order,
            (
                AgentLoopStage.CLASSIFY_PAGE,
                AgentLoopStage.CHOOSE_STRATEGY,
                AgentLoopStage.EXECUTE,
                AgentLoopStage.EVALUATE_CONFIDENCE,
                AgentLoopStage.FALLBACK_ON_ERROR,
                AgentLoopStage.SAVE_EXPERIENCE,
            ),
        )
        self.assertEqual(plan.strategy, "classify_then_scrape")
        self.assertEqual(plan.min_confidence, 0.85)
        self.assertTrue(plan.steps[-1].records_experience)
        self.assertIn("books.toscrape.com", plan.experience_key)

    def test_page_classification_training_loop_does_not_execute_scraping(self):
        task = detect_task_intent(
            """Open page and do not parse immediately:
https://books.toscrape.com/
Return task_type page_structure confidence
"""
        )

        plan = build_agent_loop(task)

        self.assertEqual(task.type, TaskType.PAGE_CLASSIFICATION_TRAINING)
        self.assertTrue(plan.classification_only)
        self.assertEqual(
            plan.stage_order,
            (
                AgentLoopStage.CLASSIFY_PAGE,
                AgentLoopStage.EVALUATE_CONFIDENCE,
                AgentLoopStage.SAVE_EXPERIENCE,
            ),
        )
        self.assertNotIn(AgentLoopStage.EXECUTE, plan.stage_order)
        self.assertEqual(plan.steps[0].action, "classify_page_before_parsing")

    def test_low_confidence_or_error_requests_fallback(self):
        self.assertTrue(should_fallback(confidence=0.2))
        self.assertTrue(should_fallback(error=ConnectionResetError("reset")))
        self.assertFalse(should_fallback(confidence=0.9))

    def test_existing_experience_is_reused_before_strategy_choice(self):
        task = detect_task_intent(
            """Scrape all https://books.toscrape.com/
- title
- price
"""
        )

        plan = build_agent_loop(task, has_experience=True)

        self.assertEqual(plan.stage_order[0], AgentLoopStage.CLASSIFY_PAGE)
        self.assertEqual(plan.stage_order[1], AgentLoopStage.REUSE_EXPERIENCE)
        self.assertEqual(plan.stage_order[2], AgentLoopStage.CHOOSE_STRATEGY)
        self.assertTrue(plan.steps[1].uses_experience)
        self.assertTrue(plan.steps[2].uses_experience)

    def test_stage_labels_are_russian_for_bot_responses(self):
        self.assertEqual(stage_label_ru(AgentLoopStage.CLASSIFY_PAGE), "определить тип страницы")
        self.assertEqual(stage_label_ru(AgentLoopStage.SAVE_EXPERIENCE), "сохранить опыт")


    def test_repair_loop_is_regression_first(self):
        task = detect_task_intent(
            "\u043f\u043e\u0447\u0438\u043d\u0438 \u043e\u0448\u0438\u0431\u043a\u0443: "
            "\u0430\u0433\u0435\u043d\u0442 \u043d\u0435 \u0441\u043f\u0430\u0440\u0441\u0438\u043b BooksToScrape"
        )

        plan = build_agent_loop(task)

        self.assertEqual(task.type, TaskType.REPAIR)
        self.assertEqual(plan.strategy, "regression_first_repair")
        self.assertEqual(
            plan.stage_order,
            (
                AgentLoopStage.REPRODUCE_FAILURE,
                AgentLoopStage.DIAGNOSE_FAILURE,
                AgentLoopStage.ASSESS_RISK,
                AgentLoopStage.CHECK_SAFETY_GATES,
                AgentLoopStage.WRITE_REGRESSION,
                AgentLoopStage.IMPLEMENT_FIX,
                AgentLoopStage.VERIFY_FIX,
                AgentLoopStage.SAVE_EXPERIENCE,
            ),
        )
        self.assertTrue(plan.steps[-1].records_experience)
        self.assertEqual(stage_label_ru(AgentLoopStage.WRITE_REGRESSION), "write regression")
        self.assertEqual(stage_label_ru(AgentLoopStage.CHECK_SAFETY_GATES), "check safety gates")


if __name__ == "__main__":
    unittest.main()
