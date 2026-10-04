import unittest

from scripts.response_evaluation import ResponseEvaluationSuite


class ResponseEvaluationSuiteTest(unittest.TestCase):
    def test_contract_scenarios_pass_without_real_model(self):
        report = ResponseEvaluationSuite().run()

        self.assertEqual(report["mode"], "offline deterministic fixtures; no real model or network")
        self.assertEqual(report["summary"], {"passed": 5, "failed": 0, "total": 5})
        self.assertIn("file_created", report["scenarios"]["code_file"]["checks"])
        self.assertTrue(report["scenarios"]["command_copy"]["checks"]["command_not_executed"])
        self.assertTrue(report["scenarios"]["application_install"]["checks"]["confirmation_required"])


if __name__ == "__main__":
    unittest.main()