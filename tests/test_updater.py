import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from local_ia import updater


class UpdaterTest(unittest.TestCase):
    def test_collect_update_files_keeps_only_managed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "web").mkdir()
            (source / ".github" / "workflows").mkdir(parents=True)
            (source / "__pycache__").mkdir()
            for relative in (
                "main.py",
                "config.json",
                "web/app.js",
                "web/icon.svg",
                ".github/workflows/ci.py",
                "__pycache__/cached.py",
            ):
                (source / relative).write_text("data", encoding="utf-8")

            required = [Path("version.json"), Path("update.json"), Path("LICENSE")]
            found = updater.collect_update_files(source, lambda _: required)

        self.assertEqual(
            set(found),
            {Path("main.py"), Path("web/app.js"), *required},
        )

    def test_update_program_installs_archive_and_preserves_user_json(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("repo/main.py", "new version\n")
            archive.writestr("repo/version.json", '{"version": "2.0.0"}')
            archive.writestr("repo/update.json", '{"versions": []}')
            archive.writestr("repo/LICENSE", "license\n")
            archive.writestr("repo/THIRD_PARTY_NOTICES.md", "notices\n")
            archive.writestr("repo/config.json", "user settings\n")
            archive.writestr("repo/web/app.js", "new web app\n")

        class Response:
            def read(self):
                return archive_bytes.getvalue()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            (destination / "main.py").write_text("old version\n", encoding="utf-8")
            (destination / "config.json").write_text("user settings\n", encoding="utf-8")
            ui_module = Mock()
            ui_module.prompt.return_value = "o"
            pause = Mock()
            with patch.object(updater, "open_url", return_value=Response()):
                updater.update_program(
                    destination,
                    "https://example.invalid/repo.zip",
                    ui_module,
                    pause,
                    lambda show_message: (True, "2.0.0"),
                    updater.required_update_files,
                    lambda: "2.0.0",
                    updater.version_to_tuple,
                )

            self.assertEqual((destination / "main.py").read_text(encoding="utf-8"), "new version\n")
            self.assertEqual((destination / "config.json").read_text(encoding="utf-8"), "user settings\n")
            self.assertEqual((destination / "web/app.js").read_text(encoding="utf-8"), "new web app\n")
            pause.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()