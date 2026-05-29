import tempfile
import unittest
from pathlib import Path

from app.skill_telemetry import ExecutionMetrics, JsonlSkillTelemetryStore, SkillRunRecord


class SkillTelemetryTests(unittest.TestCase):
    def test_jsonl_store_appends_and_summarizes_skill_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlSkillTelemetryStore(Path(tmp) / "runs.jsonl")
            store.append(
                SkillRunRecord(
                    skill_id="market.search",
                    status="success",
                    metrics=ExecutionMetrics(execution_time_ms=100, retries=1, token_usage=20),
                )
            )
            store.append(
                SkillRunRecord(
                    skill_id="market.search",
                    status="failure",
                    metrics=ExecutionMetrics(execution_time_ms=300, failures=1, retries=2, token_usage=40),
                    failure_trigger="abt-challenge",
                    recovery="cooldown",
                )
            )

            summary = store.summarize("market.search")

        self.assertEqual(summary.total_runs, 2)
        self.assertEqual(summary.success_rate, 0.5)
        self.assertEqual(summary.avg_execution_time_ms, 200)
        self.assertEqual(summary.failures, 1)
        self.assertEqual(summary.retries, 3)
        self.assertEqual(summary.token_usage, 60)

    def test_jsonl_store_empty_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlSkillTelemetryStore(Path(tmp) / "runs.jsonl")

            summary = store.summarize("missing.skill")

        self.assertEqual(summary.total_runs, 0)
        self.assertEqual(summary.success_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
