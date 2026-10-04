import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from local_ia import updater


class UpdaterTest(unittest.TestCase):
    def test_inspect_git_update_rejects_local_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            updater, "_run_git", side_effect=[directory, " M local.py"]
        ):
            with self.assertRaisesRegex(RuntimeError, "modifications locales"):
                updater.inspect_git_update(directory)

    def test_update_via_git_uses_fast_forward_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            updater,
            "_run_git",
            side_effect=[directory, "", "main", "origin/main", "Already up to date."],
        ) as run_git:
            result = updater.update_via_git(directory)

        self.assertEqual(result["upstream"], "origin/main")
        self.assertEqual(result["output"], "Already up to date.")
        self.assertEqual(
            run_git.call_args_list[3].args[1],
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        )
        self.assertEqual(run_git.call_args.args[1], ["pull", "--ff-only"])

    def test_collect_update_files_keeps_only_managed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / ".github" / "workflows").mkdir(parents=True)
            (source / "__pycache__").mkdir()
            for relative in (
                "main.py",
                "config.json",
                "program_catalog.json",
                ".github/workflows/ci.py",
                "__pycache__/cached.py",
            ):
                (source / relative).write_text("data", encoding="utf-8")

            required = [Path("version.json"), Path("update.json"), Path("LICENSE")]
            found = updater.collect_update_files(source, lambda _: required)

        self.assertEqual(
            set(found),
            {Path("main.py"), Path("program_catalog.json"), *required},
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
            archive.writestr("repo/program_catalog.json", '{"programs": []}')

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
            self.assertEqual((destination / "program_catalog.json").read_text(encoding="utf-8"), '{"programs": []}')
            pause.assert_called_once_with()

    def test_update_from_archive_preserves_user_files_and_readme(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("KAIRO-main/main.py", "new version\n")
            archive.writestr("KAIRO-main/version.json", '{"version": "2.0.0"}')
            archive.writestr("KAIRO-main/update.json", '{"versions": []}')
            archive.writestr("KAIRO-main/LICENSE", "license\n")
            archive.writestr("KAIRO-main/THIRD_PARTY_NOTICES.md", "notices\n")
            archive.writestr("KAIRO-main/config.json", "remote config\n")
            archive.writestr("KAIRO-main/README.md", "remote readme\n")
            archive.writestr("KAIRO-main/chats/777.json", "remote chat\n")

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
            (destination / "config.json").write_text("user config\n", encoding="utf-8")
            (destination / "README.md").write_text("user readme\n", encoding="utf-8")
            chat_dir = destination / "chats"
            chat_dir.mkdir()
            (chat_dir / "777.json").write_text("user chat\n", encoding="utf-8")
            with patch.object(updater, "open_url", return_value=Response()):
                result = updater.update_from_archive(destination, "2.0.0", "https://example.invalid/kairo.zip")

            self.assertEqual(result["version"], "2.0.0")
            self.assertEqual((destination / "main.py").read_text(encoding="utf-8"), "new version\n")
            self.assertEqual((destination / "config.json").read_text(encoding="utf-8"), "user config\n")
            self.assertEqual((destination / "README.md").read_text(encoding="utf-8"), "user readme\n")
            self.assertEqual((chat_dir / "777.json").read_text(encoding="utf-8"), "user chat\n")


if __name__ == "__main__":
    unittest.main()