"""
Guidance retrieval engine for USD Calling Agent.
Provides standalone, deterministic, ranked retrieval of dynamic behavioral and conversational
guidance (objections, booking flows, persuasion, privacy, empathy, etc.) with phrase weighting
and overlapping keyword handling.
"""

import os
import json
import re
from typing import List, Dict, Any, Optional

from agent.knowledge.retriever import KnowledgeRetriever, _STOP_WORDS


class GuidanceRetriever(KnowledgeRetriever):
    """
    Concrete implementation of KnowledgeRetriever specifically designed for conversational
    and situational guidance documents stored as JSON in data/guidance/.
    
    Features:
    - Startup JSON validation and in-memory caching
    - Deterministic intent scoring with phrase weighting
    - Word-boundary matching and token density overlap for overlapping keywords
    - Graceful fallback for unknown queries or missing/corrupted files
    """

    def __init__(self, guidance_dir: Optional[str] = None):
        if guidance_dir is None:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            guidance_dir = os.path.join(root_dir, "data", "guidance")
        self.guidance_dir = guidance_dir
        self._guidance_items: List[Dict[str, Any]] = []
        self.load_data()

    def load_data(self) -> None:
        """
        Loads, validates, and caches all JSON guidance files from the guidance directory.
        Performs startup validation without crashing on malformed files.
        """
        self._guidance_items.clear()
        if not os.path.exists(self.guidance_dir):
            print(f"[GuidanceRetriever] Warning: Guidance directory not found at {self.guidance_dir}")
            return

        try:
            for filename in sorted(os.listdir(self.guidance_dir)):
                if not filename.endswith(".json"):
                    continue
                file_path = os.path.join(self.guidance_dir, filename)
                category = filename[:-5]  # Strip .json extension (e.g., "objections", "booking")
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    if not isinstance(data, dict):
                        print(f"[GuidanceRetriever] Warning: File {filename} root is not a dictionary. Skipping.")
                        continue

                    for item_id, item_data in data.items():
                        if not isinstance(item_data, dict):
                            print(f"[GuidanceRetriever] Warning: Item '{item_id}' in {filename} is not a dict. Skipping.")
                            continue
                        
                        # Validate basic expected keys
                        valid_keys = {"intent", "guidance", "reframe", "script", "scripts", "rules", "conditions", "examples", "checklist", "reframes"}
                        if not any(k in item_data for k in valid_keys):
                            print(f"[GuidanceRetriever] Warning: Item '{item_id}' in {filename} lacks standard guidance keys. Skipping.")
                            continue

                        keywords = item_data.get("keywords", [])
                        if not isinstance(keywords, list):
                            keywords = []

                        intent = item_data.get("intent", item_id)

                        self._guidance_items.append({
                            "id": item_id,
                            "topic": category,
                            "intent": intent,
                            "keywords": [kw.strip().lower() for kw in keywords if isinstance(kw, str) and kw.strip()],
                            "raw_data": item_data,
                            "formatted_content": self._format_content(category, item_id, item_data)
                        })

                except json.JSONDecodeError as e:
                    print(f"[GuidanceRetriever] Error: Invalid JSON in {filename}: {e}. Skipping file.")
                except Exception as e:
                    print(f"[GuidanceRetriever] Error loading {filename}: {e}. Skipping file.")
        except Exception as e:
            print(f"[GuidanceRetriever] Unexpected error scanning directory {self.guidance_dir}: {e}")

    def _format_content(self, category: str, item_id: str, item_dict: Dict[str, Any]) -> str:
        """
        Converts a guidance item dict into clean, runtime-ready conversational coaching text
        during startup indexing. Does not emit markdown headers, JSON keys, intent names,
        category names, or matched keywords so that runtime injection requires zero cleanup.
        """
        lines = []
        for k, v in item_dict.items():
            if k in ("intent", "keywords", "id", "topic"):
                continue
            if isinstance(v, str):
                if k in ("script", "reframe", "response"):
                    lines.append(f"Suggested Phrasing: \"{v}\"")
                else:
                    lines.append(f"• {v}")
            elif isinstance(v, list):
                for item in v:
                    lines.append(f"  - {item}")
            elif isinstance(v, dict):
                if any(lang in v for lang in ("en", "hi", "gu", "hinglish")):
                    lines.append("Suggested Phrasing Options:")
                    for lang_key, script_val in v.items():
                        lang_label = {"en": "English", "hi": "Hindi", "gu": "Gujarati", "hinglish": "Hinglish"}.get(lang_key, lang_key.upper())
                        lines.append(f"  - ({lang_label}): \"{script_val}\"")
                else:
                    for sub_k, sub_v in v.items():
                        lines.append(f"  - When caller seems {sub_k.replace('_', ' ')}: {sub_v}")
            else:
                lines.append(f"• {str(v)}")
        return "\n".join(lines)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenizes text, cleans symbols, and filters common stop words."""
        words = re.findall(r"\w+(?:\.\w+)?", text.lower())
        return [w for w in words if w not in _STOP_WORDS and len(w) > 1]

    def _match_keyword(self, kw: str, query_lower: str) -> bool:
        """Checks if a keyword phrase occurs in the query with safe boundary matching."""
        if not kw:
            return False
        start_boundary = r"\b" if kw[0].isalnum() else ""
        end_boundary = r"\b" if kw[-1].isalnum() else ""
        pattern = start_boundary + re.escape(kw) + end_boundary
        return bool(re.search(pattern, query_lower))

    def retrieve(
        self,
        query: str,
        topic: Optional[str] = None,
        top_k: int = 2,
        threshold: float = 0.8,
        language: str = "en"
    ) -> List[Dict[str, Any]]:
        """
        Retrieves relevant guidance items ranked by deterministic relevance scoring.
        Uses word-boundary phrase matching and token density overlap to score items.
        
        Args:
            query: The user's message or utterance.
            topic: Optional explicit topic/category constraint (e.g., "objections" or "privacy").
            top_k: Maximum number of ranked guidance items to return.
            threshold: Minimum relevance score required to include an item.
            language: Preferred language parameter (retained for interface compatibility).
            
        Returns:
            List of dicts with keys: id, topic, intent, score, content, related_topics, raw_data, matched_keywords.
        """
        if not self._guidance_items:
            self.load_data()

        query_clean = query.strip()
        if not query_clean:
            return []

        query_lower = query_clean.lower()
        query_tokens = set(self._tokenize(query_lower))
        scored_results = []

        for item in self._guidance_items:
            score = 0.0
            item_id = item["id"]
            item_topic = item["topic"].lower()
            item_intent = item["intent"].lower()
            keywords: List[str] = item["keywords"]
            matched_keywords: List[str] = []

            # 1. Explicit topic / category boost
            if topic and (topic.strip().lower() == item_topic or topic.strip().lower() == item_intent):
                score += 1.5

            # 2. Keyword matching with Phrase Weighting
            # Exact word-boundary matches get significantly higher weight for multi-word phrases
            for kw in keywords:
                if self._match_keyword(kw, query_lower):
                    matched_keywords.append(kw)
                    word_count = len(kw.split())
                    # Phrase Weighting Formula: multi-word phrases receive progressive multiplier
                    if word_count == 1:
                        score += 1.0
                    elif word_count == 2:
                        score += 1.6
                    else:
                        score += 2.2 + 0.3 * (word_count - 3)

            # 3. Token Overlap Density (handles scattered matches & semantic affinity)
            if keywords or item_intent:
                item_text_for_tokens = item_topic + " " + item_intent + " " + " ".join(keywords)
                item_tokens = set(self._tokenize(item_text_for_tokens))
                if query_tokens and item_tokens:
                    intersection = query_tokens.intersection(item_tokens)
                    if intersection:
                        overlap_ratio = len(intersection) / min(len(query_tokens), max(len(item_tokens), 1))
                        score += overlap_ratio * 0.4

            # 4. Filter by threshold and build response
            if score >= threshold:
                scored_results.append({
                    "id": item_id,
                    "topic": item["topic"],
                    "intent": item["intent"],
                    "score": round(score, 3),
                    "content": item["formatted_content"],
                    "related_topics": keywords,
                    "raw_data": item["raw_data"],
                    "matched_keywords": matched_keywords
                })

        # Sort descending by relevance score, breaking ties by number of matched keywords
        scored_results.sort(key=lambda x: (x["score"], len(x["matched_keywords"])), reverse=True)
        return scored_results[:top_k]


# Global singleton instance for efficient zero-cost retrieval across turns
_default_guidance_retriever: Optional[GuidanceRetriever] = None

def get_guidance_retriever() -> GuidanceRetriever:
    global _default_guidance_retriever
    if _default_guidance_retriever is None:
        _default_guidance_retriever = GuidanceRetriever()
    return _default_guidance_retriever


def _format_guidance_for_prompt(guidance_results: list, **kwargs) -> str:
    """
    Concatenates preformatted, runtime-ready conversational guidance strings.
    Performs zero parsing, formatting, or cleanup at runtime, relying entirely on
    the clean content field generated during startup indexing.
    """
    return "\n\n".join(r["content"] for r in guidance_results if r.get("content"))
