import unittest


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


if __name__ == "__main__":
    unittest.main()
