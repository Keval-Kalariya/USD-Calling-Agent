"""
Standalone knowledge retrieval architecture for USD Calling Agent.
Defines an abstract KnowledgeRetriever interface capable of ranked (top_k) retrieval
with scores, designed to seamlessly support vector RAG in the future without API changes.
"""

import os
import json
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

# Standard stop words to ignore during token scoring
_STOP_WORDS = {
    "a", "about", "above", "after", "again", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "can't", "could", "did", "do", "does", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "me", "more", "most", "my", "myself", "nor",
    "of", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "that's",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "we're",
    "what", "what's", "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "won't", "would", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself"
}

class KnowledgeRetriever(ABC):
    """
    Abstract interface for retrieving domain knowledge.
    Whether backed by a local JSON file or a Vector RAG database, implementations
    must conform to this interface to return ranked items with similarity scores.
    """
    @abstractmethod
    def retrieve(
        self,
        query: str,
        topic: Optional[str] = None,
        top_k: int = 2,
        threshold: float = 0.15,
        language: str = "en"
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant knowledge entries ranked by score.
        
        Args:
            query: The user's natural language question or utterance.
            topic: Optional explicit topic constraint (e.g., from tool calling).
            top_k: Maximum number of ranked entries to return.
            threshold: Minimum score required for inclusion.
            language: Preferred language ('en', 'hi', 'gu', or 'multi') for text selection if structured.
            
        Returns:
            A list of dicts with keys: id, topic, intent, score, content, related_topics.
        """
        pass


class JSONFaqRetriever(KnowledgeRetriever):
    """
    Concrete implementation of KnowledgeRetriever using lexical scoring and keyword match
    against structured FAQ data. Serves as Phase 1 retrieval engine before vector embedding RAG.
    """
    def __init__(self, data_path: Optional[str] = None):
        if data_path is None:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_path = os.path.join(root_dir, "data", "faq_knowledge.json")
        self.data_path = data_path
        self._knowledge_items: List[Dict[str, Any]] = []
        self.load_data()

    def load_data(self) -> None:
        """Loads the structured FAQ JSON file into memory."""
        if not os.path.exists(self.data_path):
            print(f"[JSONFaqRetriever] Warning: data file not found at {self.data_path}")
            return
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                self._knowledge_items = json.load(f)
        except Exception as e:
            print(f"[JSONFaqRetriever Error] Failed to load JSON knowledge: {e}")

    def _tokenize(self, text: str) -> List[str]:
        """Tokenizes text, cleans symbols, and filters common stop words."""
        words = re.findall(r"\w+(?:\.\w+)?", text.lower())
        return [w for w in words if w not in _STOP_WORDS and len(w) > 1]

    def _get_content_for_language(self, content: Any, lang: str) -> str:
        """Extracts the appropriate language string if content is multilingual dictionary."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            clean_lang = lang.strip().lower() if lang.strip().lower() in ("en", "hi", "gu") else "en"
            return content.get(clean_lang) or content.get("en") or str(content)
        return str(content)

    def retrieve(
        self,
        query: str,
        topic: Optional[str] = None,
        top_k: int = 2,
        threshold: float = 0.15,
        language: str = "en"
    ) -> List[Dict[str, Any]]:
        """
        Computes relevance score for each knowledge entry based on query token matches,
        keyword phrase overlap, topic matching, and priority weight.
        """
        if not self._knowledge_items:
            self.load_data()

        query_tokens = set(self._tokenize(query))
        query_lower = query.strip().lower()
        scored_results = []

        for item in self._knowledge_items:
            score = 0.0
            item_topic = item.get("topic", "").lower()
            item_id = item.get("id", "").lower()
            item_intent = item.get("intent", "").lower()
            keywords = [kw.lower() for kw in item.get("related_topics", []) + item.get("keywords", [])]

            # 1. Direct topic match (e.g. via explicit tool invocation or topic parameter)
            if topic and (topic.strip().lower() == item_topic or topic.strip().lower() == item_intent or topic.strip().lower() in item_topic):
                score += 1.0

            # 2. Exact keyword or phrase occurrences in raw query string
            for kw in item.get("keywords", []):
                kw_lower = kw.lower()
                if kw_lower in query_lower:
                    # Longer phrases get higher weight (e.g., "how long" vs "cost")
                    phrase_len = len(kw_lower.split())
                    score += 0.35 * (1 + 0.2 * phrase_len)

            # 3. Token overlap density against keywords and topics
            item_tokens = set(self._tokenize(item_topic + " " + " ".join(keywords) + " " + item_intent))
            if query_tokens and item_tokens:
                intersection = query_tokens.intersection(item_tokens)
                if intersection:
                    # Token similarity ratio
                    overlap_score = len(intersection) / min(len(query_tokens), max(len(item_tokens), 1))
                    score += overlap_score * 0.5

            # 4. Tie-breaking and boosting via item priority
            priority = item.get("priority", 5)
            if score > 0:
                score += priority * 0.01

            if score >= threshold:
                content_str = self._get_content_for_language(item.get("content", ""), language)
                scored_results.append({
                    "id": item.get("id", ""),
                    "topic": item.get("topic", ""),
                    "intent": item.get("intent", ""),
                    "score": round(min(score, 1.0), 3),
                    "content": content_str,
                    "related_topics": item.get("related_topics", []),
                    "raw_content": item.get("content", "")
                })

        # Sort descending by relevance score
        scored_results.sort(key=lambda x: x["score"], reverse=True)
        return scored_results[:top_k]


# Global singleton instance for efficient zero-cost retrieval across turns
_default_retriever: Optional[KnowledgeRetriever] = None

def get_retriever() -> KnowledgeRetriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = JSONFaqRetriever()
    return _default_retriever
