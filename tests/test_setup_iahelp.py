import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import setup


class SetupIahelpTest(unittest.TestCase):
    def test_launcher_is_installed_and_path_configuration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home user"
            project = Path(directory) / "local ia project"
            home.mkdir()
            project.mkdir()
            python = project / ".venv" / "bin" / "python"

            with patch.object(setup, "get_system", return_value="linux"), \
                 patch.object(setup.Path, "home", return_value=home):
                launcher = setup.install_iahelp_command(project, python)
                setup.install_iahelp_command(project, python)

            self.assertEqual(launcher, home / ".local" / "bin" / "iahelp")
            self.assertIn('"$@"', launcher.read_text(encoding="utf-8"))
            self.assertIn("local ia project/main.py", launcher.read_text(encoding="utf-8"))
            self.assertTrue(stat.S_IMODE(launcher.stat().st_mode) & stat.S_IXUSR)
            profile = (home / ".profile").read_text(encoding="utf-8")
            self.assertEqual(profile.count("# local_ia iahelp PATH"), 1)
            fish_config = home / ".config" / "fish" / "conf.d" / "local_ia_iahelp.fish"
            self.assertIn("fish_add_path", fish_config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
