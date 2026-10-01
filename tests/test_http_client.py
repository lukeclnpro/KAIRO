import unittest
from urllib.error import URLError
from unittest.mock import patch

from local_ia import http_client


class HttpClientTest(unittest.TestCase):
    def test_only_absolute_http_urls_are_accepted(self):
        self.assertEqual(http_client.validate_http_url("https://example.com/path"), "https://example.com/path")
        self.assertEqual(http_client.validate_http_url("http://127.0.0.1:11434/api"), "http://127.0.0.1:11434/api")
        for url in ("file:///etc/passwd", "ftp://example.com", "/relative/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                http_client.validate_http_url(url)

    def test_get_retries_transient_network_errors(self):
        response = object()
        with patch.object(
            http_client,
            "urlopen",
            side_effect=(URLError("temporary"), response),
        ) as open_request, patch.object(http_client.time, "sleep"):
            self.assertIs(http_client.open_url("https://example.com", retries=1), response)

        self.assertEqual(open_request.call_count, 2)

    def test_post_is_not_retried_to_avoid_duplicate_requests(self):
        request = http_client.Request("https://example.com/api", data=b"{}", method="POST")
        with patch.object(http_client, "urlopen", side_effect=URLError("temporary")) as open_request:
            with self.assertRaises(URLError):
                http_client.open_url(request, retries=3)

        open_request.assert_called_once_with(request, timeout=10)

    def test_invalid_url_is_rejected_before_network_access(self):
        with patch.object(http_client, "urlopen") as open_request:
            with self.assertRaises(ValueError):
                http_client.open_url("file:///etc/passwd")

        open_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()