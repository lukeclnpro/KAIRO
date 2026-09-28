import unittest

from main import version_to_tuple
from scripts.generate_readme import version_tuple


class FinalArchitectureTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
