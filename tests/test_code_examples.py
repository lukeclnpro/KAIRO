import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "code" / "exemple"


def load_example(filename):
    spec = importlib.util.spec_from_file_location(f"example_{filename}", EXAMPLES / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


text = load_example("text.py")
collections = load_example("collection_helpers.py")
files = load_example("files.py")
validation = load_example("validation.py")
dates = load_example("dates.py")
urls = load_example("url_helpers.py")


class CodeExamplesTest(unittest.TestCase):
    def test_text_helpers_normalize_and_truncate(self):
        self.assertEqual(text.slugify("Été du café"), "ete-du-cafe")
        self.assertEqual(text.normalize_whitespace("  bon\n  jour "), "bon jour")
        self.assertEqual(text.truncate("bonjour", 5), "bonj…")
        self.assertEqual(text.mask_email("alice@example.com"), "a****@example.com")

    def test_collection_helpers_preserve_order_and_validate_pages(self):
        self.assertEqual(list(collections.chunks([1, 2, 3], 2)), [[1, 2], [3]])
        self.assertEqual(collections.unique([2, 1, 2]), [2, 1])
        self.assertEqual(collections.paginate(["a", "b", "c"], 2, 2), ["c"])
        self.assertEqual(collections.group_by([1, 2, 3], lambda value: value % 2), {1: [1, 3], 0: [2]})

    def test_validation_helpers_reject_bad_values(self):
        self.assertEqual(validation.clamp(12, 0, 10), 10)
        self.assertTrue(validation.is_valid_email("a@example.com"))
        self.assertTrue(validation.is_http_url("https://example.com"))
        self.assertFalse(validation.is_http_url("file:///etc/passwd"))
        with self.assertRaises(ValueError):
            validation.parse_integer("9", maximum=5)

    def test_file_helpers_write_json_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "items.json"
            files.save_json(path, {"nom": "été"})
            self.assertEqual(files.load_json(path), {"nom": "été"})
            self.assertEqual(files.sha256_file(path), __import__("hashlib").sha256(path.read_bytes()).hexdigest())

    def test_date_and_url_helpers(self):
        start = dates.parse_iso_date("2026-10-01")
        end = dates.parse_iso_date("2026-10-04")
        self.assertEqual(dates.days_between(start, end), 3)
        self.assertEqual(dates.format_duration(3661), "1 h 1 min 1 s")
        updated = urls.add_query_params("https://example.com/?a=1", {"b": "hello world"})
        self.assertEqual(urls.get_query_param(updated, "b"), "hello world")
        self.assertEqual(urls.normalize_http_url("example.com"), "https://example.com")


if __name__ == "__main__":
    unittest.main()
