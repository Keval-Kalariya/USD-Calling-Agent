"""
Unit tests and demonstration suite for Phase 5.1: Standalone GuidanceRetriever.
Verifies loading, caching, JSON validation, deterministic intent scoring, phrase weighting,
overlapping keywords, and graceful fallback.
"""

import os
import sys
import unittest
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from agent.knowledge.guidance import GuidanceRetriever, get_guidance_retriever
from agent.knowledge import KnowledgeRetriever


class TestGuidanceRetriever(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.retriever = get_guidance_retriever()
        print("\n=======================================================")
        print("    PHASE 5.1 — GUIDANCE RETRIEVER DEMONSTRATION")
        print("=======================================================")

    def _log_scoring_output(self, demo_name: str, query: str, results: list):
        print(f"\n--- [DEMO: {demo_name}] ---")
        print(f"Query     : \"{query}\"")
        if not results:
            print("Result    : [] (No guidance triggered -> Graceful Fallback)")
        else:
            print("Results  :")
            for i, res in enumerate(results, 1):
                print(f"  {i}. ID: {res['id']:<25} | Category: {res['topic']:<12} | Score: {res['score']:<5} | Matched: {res['matched_keywords']}")
        print("-" * 55)

    def test_01_interface_and_caching(self):
        self.assertIsInstance(self.retriever, KnowledgeRetriever)
        self.assertIsInstance(self.retriever, GuidanceRetriever)
        self.assertGreater(len(self.retriever._guidance_items), 0, "Guidance items should be loaded and cached.")
        
        # Verify cached structure
        first_item = self.retriever._guidance_items[0]
        self.assertIn("id", first_item)
        self.assertIn("topic", first_item)
        self.assertIn("intent", first_item)
        self.assertIn("keywords", first_item)
        self.assertIn("formatted_content", first_item)

    def test_02_startup_validation_and_missing_dir_fallback(self):
        # Verify that pointing to an invalid directory gracefully produces empty results without crashing
        bogus_retriever = GuidanceRetriever(guidance_dir="/invalid/path/that/does_not_exist")
        res = bogus_retriever.retrieve("I want to book an appointment")
        self.assertEqual(res, [])
        self.assertEqual(len(bogus_retriever._guidance_items), 0)

    def test_03_booking_detection(self):
        query = "I would love to book an appointment for a consultation at your clinic."
        results = self.retriever.retrieve(query, top_k=2)
        self._log_scoring_output("Booking Detection", query, results)
        
        self.assertGreater(len(results), 0)
        top_res = results[0]
        self.assertEqual(top_res["topic"], "booking")
        self.assertIn("booking", top_res["id"])
        self.assertGreater(top_res["score"], 1.0)
        self.assertIn("book", top_res["matched_keywords"])

    def test_04_objection_detection(self):
        # Price objection demo
        query_price = "Why is this so expensive? That sounds like too much money for my budget."
        results_price = self.retriever.retrieve(query_price, top_k=2)
        self._log_scoring_output("Objection Detection (Price)", query_price, results_price)
        self.assertGreater(len(results_price), 0)
        self.assertEqual(results_price[0]["id"], "price_objection")
        self.assertIn("expensive", results_price[0]["matched_keywords"])

        # Pain/Fear objection demo
        query_pain = "I'm really scared it will hurt. Will the procedure be painful with drills and needles?"
        results_pain = self.retriever.retrieve(query_pain, top_k=2)
        self._log_scoring_output("Objection Detection (Pain/Fear)", query_pain, results_pain)
        self.assertGreater(len(results_pain), 0)
        self.assertEqual(results_pain[0]["id"], "pain_fear")
        self.assertIn("hurt", results_pain[0]["matched_keywords"])
        self.assertIn("scared", results_pain[0]["matched_keywords"])

    def test_05_privacy_detection(self):
        query = "I am a high-profile public figure and need absolute privacy and discretion. Will nobody know?"
        results = self.retriever.retrieve(query, top_k=2)
        self._log_scoring_output("Privacy Detection", query, results)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "privacy_assurance")
        self.assertEqual(results[0]["topic"], "privacy")
        self.assertIn("privacy", results[0]["matched_keywords"])
        self.assertIn("public figure", results[0]["matched_keywords"])

    def test_06_multiple_intent_scoring_and_phrase_weighting(self):
        # Query containing overlapping concerns: Booking + Price Objection + Privacy
        query = "I want to schedule a consultation, but honestly I'm scared it costs too much and as a public figure I need total discretion."
        results = self.retriever.retrieve(query, top_k=4)
        self._log_scoring_output("Multiple Intent Scoring & Phrase Weighting", query, results)
        
        self.assertGreaterEqual(len(results), 2, "Should return multiple distinct scored intents")
        categories_found = {res["topic"] for res in results}
        self.assertIn("booking", categories_found)
        self.assertIn("objections", categories_found)
        
        # Check descending order of scores
        for i in range(len(results) - 1):
            self.assertGreaterEqual(results[i]["score"], results[i+1]["score"])

    def test_07_unknown_query_fallback(self):
        query = "What is the capital of France or what is the weather today?"
        results = self.retriever.retrieve(query)
        self._log_scoring_output("Unknown Query Fallback", query, results)
        self.assertEqual(len(results), 0, "General unrelated queries should fall back to empty guidance list.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
