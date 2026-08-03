"""
Tool: get_faq
Returns FAQ content for the USD calling agent by delegating to the standalone KnowledgeRetriever.
Supported languages: en, hi, gu.
"""

from typing import Optional, Dict, Any
from agent.knowledge import get_retriever

_NOT_FOUND = {
    "en": (
        "I don't have specific information on that topic right now. "
        "I'd recommend speaking with our team directly — I can arrange a callback for you."
    ),
    "hi": (
        "मुझे अभी उस topic पर specific information नहीं है। "
        "मैं recommend करूँगा कि आप हमारी team से directly बात करें — मैं आपके लिए callback arrange कर सकता हूँ।"
    ),
    "gu": (
        "Maṇe halyāre te topic par specific information nathī. "
        "Maiṃ recommend karīś ke āp amārī team sāthe directly vāt karo — maiṃ āpnā māṭe callback arrange karī śakuṃ."
    ),
}

SUPPORTED_TOPICS = [
    "about_usd", "about_ade_haresh_savani", "safety_quality_materials",
    "warranty", "veneers", "implants", "whitening", "treatments_general",
    "preview_ai_digital", "process_timeline", "cities_coverage", "cost_value",
    "aftercare_comfort", "privacy_busy_schedule", "contact_booking",
    "process", "timeline", "cities", "cost", "before_after"
]


def get_faq(topic: str, language: str = "en") -> Dict[str, Any]:
    """
    Returns FAQ content for the requested topic or keyword query in the requested language.
    Delegates retrieval to the modular KnowledgeRetriever architecture.
    
    Args:
        topic: Topic name or keyword query string.
        language: en | hi | gu | multi.

    Returns:
        A dict with:
          - found (bool): whether matching knowledge was retrieved.
          - topic (str): queried topic or keywords.
          - language (str): language used.
          - answer (str): the retrieved FAQ answer in the requested language.
          - score (float): retrieval relevance score.
          - related_topics (list): suggested follow-up topics.
    """
    query_topic = topic.strip()
    lang = language.strip().lower() if language.strip().lower() in ("en", "hi", "gu") else "en"
    
    # Delegate to standalone knowledge retriever
    retriever = get_retriever()
    results = retriever.retrieve(query=query_topic, topic=query_topic, top_k=2, threshold=0.1, language=lang)
    
    if not results:
        return {
            "found": False,
            "topic": query_topic,
            "language": lang,
            "answer": _NOT_FOUND.get(lang, _NOT_FOUND["en"]),
            "score": 0.0,
            "related_topics": []
        }
    
    # Combine answers if multiple highly relevant items returned
    primary = results[0]
    answer = primary["content"]
    related = list(primary["related_topics"])
    
    if len(results) > 1 and results[1]["score"] > 0.3:
        second_content = results[1]["content"]
        if second_content != answer:
            answer = f"{answer}\n\n{second_content}"
            for t in results[1]["related_topics"]:
                if t not in related:
                    related.append(t)

    return {
        "found": True,
        "topic": primary["topic"] or query_topic,
        "language": lang,
        "answer": answer,
        "score": primary["score"],
        "related_topics": related
    }
