import unittest

from app.execution_state import ExecutionRun, ExecutionStatus


class ExecutionStateTests(unittest.TestCase):
    def test_execution_run_finishes_valid_sequence(self):
        run = ExecutionRun(run_id="run-1", skill_ids=["html.fetch"])

        run.transition(ExecutionStatus.PREPARING)
        run.start_current_step()
        run.finish_current_step()

        self.assertEqual(run.status, ExecutionStatus.FINISHED)
        self.assertEqual(run.steps[0].status, ExecutionStatus.FINISHED)
        self.assertEqual(run.history, [
            ExecutionStatus.PLANNING,
            ExecutionStatus.PREPARING,
            ExecutionStatus.EXECUTING,
            ExecutionStatus.VALIDATING,
            ExecutionStatus.FINISHED,
        ])

    def test_execution_run_rejects_invalid_transition(self):
        run = ExecutionRun(run_id="run-1", skill_ids=["html.fetch"])

        with self.assertRaises(ValueError):
            run.transition(ExecutionStatus.FINISHED)

    def test_execution_run_enters_recovery_on_recoverable_failure(self):
        run = ExecutionRun(run_id="run-1", skill_ids=["market.search"])
        run.transition(ExecutionStatus.PREPARING)
        run.start_current_step()

        run.fail_current_step("abt-challenge", recoverable=True)

        self.assertEqual(run.status, ExecutionStatus.RECOVERING)
        self.assertEqual(run.current_step.error, "abt-challenge")


if __name__ == "__main__":
    unittest.main()
