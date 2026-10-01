import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core.router import RequestRouter
from local_ia.core.tool_manager import ToolManager
from local_ia.core.agent import LocalAgent
from local_ia.tools import browser


class BrowserToolTest(unittest.TestCase):
    def test_open_page_uses_default_browser_and_normalizes_domain(self):
        with patch("local_ia.tools.browser.webbrowser.open", return_value=True) as open_browser:
            result = browser.open_page("www.example.com/path")

        self.assertEqual(result, {"url": "https://www.example.com/path", "opened": True, "error": ""})
        open_browser.assert_called_once_with("https://www.example.com/path", new=2, autoraise=True)

    def test_open_page_rejects_non_web_schemes_and_embedded_credentials(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com"):
            with self.subTest(url=url), patch("local_ia.tools.browser.webbrowser.open") as open_browser:
                with self.assertRaises(ValueError):
                    browser.open_page(url)
                open_browser.assert_not_called()

    def test_open_page_reports_browser_failure(self):
        with patch("local_ia.tools.browser.webbrowser.open", return_value=False):
            result = browser.open_page("example.com")

        self.assertFalse(result["opened"])
        self.assertIn("n'a pas confirmé", result["error"])

    def test_router_uses_browser_tool_for_explicit_page_request(self):
        route = RequestRouter().route("Ouvre https://example.com", lambda *_: None)

        self.assertEqual(route["action"], "open_page")
        self.assertEqual(route["tools"], ("open_page",))

    def test_tool_manager_executes_and_verifies_browser_action(self):
        call = {"tool": "open_page", "arguments": {"url": "example.com"}}
        result = {"url": "https://example.com", "opened": True, "error": ""}
        with patch("local_ia.core.tool_manager.browser.open_page", return_value=result) as open_page:
            executed = ToolManager.execute(call, chat={}, connection=None)

        self.assertEqual(executed, result)
        open_page.assert_called_once_with("example.com")
        verification = ToolManager.verify_result(call, executed, {})
        self.assertTrue(verification["verified"])
        self.assertTrue(verification["success"])

    def test_browser_tool_prompt_is_available(self):
        prompt = ToolManager.build_prompt({"open_page"})
        self.assertIn('open_page : {"url"', prompt)

    def test_agent_parses_open_page_tool_call(self):
        tool_call = LocalAgent.parse_tool_call(
            '<tool_call>{"tool":"open_page","arguments":{"url":"example.com"}}</tool_call>'
        )

        self.assertEqual(tool_call, {"tool": "open_page", "arguments": {"url": "example.com"}})


if __name__ == "__main__":
    unittest.main()
