import unittest

from scripts.performance_targets import PerformanceTargetChecker


class PerformanceTargetCheckerTest(unittest.TestCase):
    def test_evaluates_targets_against_expected_ranges(self):
        report = {
            "scenarios": {
                "simple_question": {"ollama_calls": 1, "total_ms": 250, "tool_steps": 0},
                "simple_action": {"ollama_calls": 0, "total_ms": 40, "tool_steps": 0},
                "tool_request": {"ollama_calls": 2, "total_ms": 400, "tool_steps": 1},
                "complex_task": {"ollama_calls": 3, "total_ms": 800, "tool_steps": 4},
            }
        }

        evaluation = PerformanceTargetChecker().evaluate(report)

        self.assertEqual(evaluation["simple_question"]["status"], "pass")
        self.assertEqual(evaluation["simple_action"]["status"], "pass")
        self.assertEqual(evaluation["tool_request"]["status"], "pass")
        self.assertEqual(evaluation["complex_task"]["status"], "pass")
        self.assertIn("summary", evaluation)


if __name__ == "__main__":
    unittest.main()
