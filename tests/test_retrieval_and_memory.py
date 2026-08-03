"""
Unit test suite for the Three-Layer Architecture refactoring:
- Layer 2: KnowledgeRetriever & JSONFaqRetriever (ranked top_k and scoring)
- Layer 3: CallSession Python-Managed Session Memory & Mutable Language Preference
- Layer 1: Prompt architecture verification (size check & dynamic fact injection format)
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from agent.knowledge import get_retriever, KnowledgeRetriever, JSONFaqRetriever
from agent.session.call_session import CallSession
from agent.tools.get_faq import get_faq


class TestThreeLayerArchitecture(unittest.TestCase):

    def test_retriever_interface(self):
        retriever = get_retriever()
        self.assertIsInstance(retriever, KnowledgeRetriever)
        self.assertIsInstance(retriever, JSONFaqRetriever)

    def test_ranked_retrieval_scoring(self):
        retriever = get_retriever()
        # Query matching warranty and veneers
        results = retriever.retrieve(query="What is your warranty policy for veneers?", top_k=2)
        self.assertTrue(len(results) > 0)
        self.assertTrue(any(r["topic"] == "warranty" for r in results))
        self.assertIn("score", results[0])
        self.assertGreater(results[0]["score"], 0.0)

        # Verify ranking when top_k > 1
        if len(results) > 1:
            self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    def test_multilingual_retrieval_and_get_faq(self):
        # Test Hindi FAQ retrieval via get_faq wrapper
        res_hi = get_faq("cost", language="hi")
        self.assertIn("answer", res_hi)
        self.assertTrue(len(res_hi.get("answer", "")) > 20)

        # Test Gujarati FAQ retrieval via get_faq wrapper
        res_gu = get_faq("warranty", language="gu")
        self.assertIn("answer", res_gu)
        self.assertTrue(len(res_gu.get("answer", "")) > 20)

    def test_call_session_memory_and_mutable_language(self):
        session = CallSession("test_call_001", opening_intent="general")
        self.assertEqual(session.preferred_language, "en") # default
        
        # Test mutable language update
        session.update_language_if_requested("Mujhe Hindi me baat krni hai please")
        self.assertEqual(session.preferred_language, "hi")

        # Test another language change later in session
        session.update_language_if_requested("Can we switch back to English now?")
        self.assertEqual(session.preferred_language, "en")

        # Test session topic and lead info tracking
        session.update_topic("cost")
        session.update_user_info(name="Rajesh Kumar", city="Mumbai", intent="consultation")
        
        context_prompt = session.get_session_context_prompt()
        self.assertIn("Preferred Language: English (en)", context_prompt)
        self.assertIn("Active Topic in Discussion: cost", context_prompt)
        self.assertIn("Rajesh Kumar", context_prompt)
        self.assertIn("Mumbai", context_prompt)

    def test_system_prompt_size_reduction(self):
        prompt_path = os.path.join(ROOT, "agent", "prompts", "system_prompt.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()
        
        # Check that prompt size is significantly reduced compared to old ~52KB
        file_size_kb = len(prompt_text.encode('utf-8')) / 1024.0
        self.assertLess(file_size_kb, 35.0, f"System prompt size {file_size_kb:.2f} KB is too large! Should be well under 35 KB after stripping static facts.")
        
        # Verify core behavioral sections exist
        self.assertIn("IDENTITY & PERSONA", prompt_text)
        self.assertIn("LANGUAGE SYSTEM", prompt_text)
        self.assertIn("CRITICAL RULES — DO NOT VIOLATE", prompt_text)
        
        # Verify static factual bulk table is gone
        self.assertNotIn("Plot No. 1 to 8, Marutidham Industrial Estate", prompt_text)
        self.assertNotIn("++91 84 69 88 88 77", prompt_text)


if __name__ == "__main__":
    unittest.main()
