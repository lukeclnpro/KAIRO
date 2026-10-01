import unittest

from scripts.benchmark_final import BenchmarkSuite


class BenchmarkSuiteTest(unittest.TestCase):
    def test_suite_reports_metrics_for_key_scenarios(self):
        report = BenchmarkSuite().run()

        self.assertIn("scenarios", report)
        self.assertTrue(report["scenarios"])
        self.assertEqual(
            report["scenarios"]["file_edit"]["answer"],
            "Fichier modifié avec succès.",
        )
        self.assertEqual(
            report["scenarios"]["complex_tool_task"]["answer"],
            "La tâche est terminée.",
        )

        for name, result in report["scenarios"].items():
            self.assertIn("first_token_ms", result)
            self.assertIn("total_ms", result)
            self.assertIn("ollama_calls", result)
            self.assertIn("prompt_chars", result)
            self.assertIn("memory_items", result)
            self.assertIn("history_messages", result)
            self.assertIn("tool_result_chars", result)
            self.assertIn("disk_write_ms", result)
            self.assertGreaterEqual(result["total_ms"], 0)
            self.assertGreaterEqual(result["ollama_calls"], 0)
            self.assertGreaterEqual(result["prompt_chars"], 0)
            self.assertNotEqual(name, "")


if __name__ == "__main__":
    unittest.main()
