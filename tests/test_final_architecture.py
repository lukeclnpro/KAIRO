import unittest

from main import VERSION_FILE, get_version, version_to_tuple
from scripts.generate_readme import render_version, version_tuple


class FinalArchitectureTest(unittest.TestCase):
    def test_menu_version_metadata_matches_version_json(self):
        import json

        with VERSION_FILE.open("r", encoding="utf-8") as file:
            metadata = json.load(file)

        self.assertEqual(
            get_version(),
            (metadata["version"], metadata["patch"], metadata["modified_at"]),
        )
        self.assertIn("0.2.0.10(beta10)", render_version(metadata))

    def test_final_target_modules_are_available(self):
        import local_ia.core.memory_manager
        import local_ia.llm.session
        import local_ia.memory
        import local_ia.memory.sqlite
        import local_ia.memory.embeddings
        import local_ia.memory.retriever

        self.assertTrue(hasattr(local_ia.core.memory_manager, "get_memories"))
        self.assertTrue(hasattr(local_ia.llm.session, "OllamaSession"))
        self.assertTrue(hasattr(local_ia.memory, "get_memories"))
        self.assertTrue(hasattr(local_ia.memory.sqlite, "init_database"))
        self.assertTrue(hasattr(local_ia.memory.embeddings, "compute_embedding"))
        self.assertTrue(hasattr(local_ia.memory.retriever, "get_memories"))

    def test_beta_and_stable_versions_are_compared_numerically(self):
        beta4 = "0.2.0.2(beta4)"
        beta5 = "0.2.0.3(beta5)"
        stable = "0.2.0.4"
        self.assertGreater(version_to_tuple(beta5), version_to_tuple(beta4))
        self.assertGreater(version_to_tuple(stable), version_to_tuple(beta5))
        self.assertGreater(version_tuple(beta5), version_tuple(beta4))
        self.assertGreater(version_tuple(stable), version_tuple(beta5))
        self.assertEqual(version_to_tuple("0.2.0"), version_to_tuple("0.2.0.0"))
        self.assertEqual(version_tuple("0.2.0"), version_tuple("0.2.0.0"))


if __name__ == "__main__":
    unittest.main()
