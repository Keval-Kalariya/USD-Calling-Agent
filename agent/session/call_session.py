"""
Per-call conversation session state machine and sentence chunker buffer.
"""

import os
import asyncio
import re
from typing import Any, Optional

class CallSession:
    """
    Manages state transitions (listening, thinking, speaking), conversation history,
    and transcript buffers for real-time Gemini Live interactions.
    Also owns Layer 3 conversational memory, mutable preferred language, and session state.
    """
    def __init__(self, call_id: str, opening_intent: str | None = None, lead_id: str | None = None, preferred_language: str = "en"):
        self.call_id = call_id
        self.opening_intent = opening_intent
        self.lead_id = lead_id
        
        # State machine: "listening", "thinking", "speaking"
        self.state: str = "listening"
        
        # Layer 3: Python-managed conversation memory & mutable session state
        self.preferred_language: str = preferred_language  # mutable preferred language (en, hi, gu, multi)
        self.last_discussed_topic: Optional[str] = None
        self.booking_stage: str = "greeting"  # e.g., greeting, discovery, consultation_proposed, lead_captured, handoff
        self.collected_user_info: dict[str, str] = {
            "name": "",
            "phone": "",
            "city": "",
            "intent": "",
            "notes": ""
        }
        
        # Buffer for accumulating streaming STT transcripts in the current turn
        self.transcript_buffer: list[str] = []
        self.final_transcripts: list[str] = []
        self.interim_transcript: str = ""
        
        # Chronological record of confirmed conversational turns for logging
        self.conversation_history: list[dict[str, Any]] = []
        
        # Turn tracking for future barge-in cancellation guards
        self.current_turn_id: int = 0

    def set_preferred_language(self, lang: str) -> None:
        """Mutates preferred language immediately without restarting session."""
        clean_lang = lang.strip().lower()
        mapping = {"english": "en", "hindi": "hi", "gujarati": "gu", "en": "en", "hi": "hi", "gu": "gu", "multi": "multi"}
        if clean_lang in mapping:
            new_lang = mapping[clean_lang]
            if self.preferred_language != new_lang:
                print(f"[CallSession {self.call_id[:8]}] Preferred Language Updated: {self.preferred_language} -> {new_lang}")
                self.preferred_language = new_lang

    def update_language_if_requested(self, text: str) -> bool:
        """
        Inspects user utterance in Python for language selection or switch requests.
        Updates preferred language immediately on the fly.
        """
        text_lower = text.lower().strip()
        if any(token in text_lower for token in ["gujarati", "gujlish", "gujarati ma", "kem cho"]):
            self.set_preferred_language("gu")
            return True
        elif any(token in text_lower for token in ["hindi", "hinglish", "hindi mein", "hindi me", "hindi mein baat", "kaise ho", "namaste"]):
            self.set_preferred_language("hi")
            return True
        elif any(token in text_lower for token in ["english", "in english", "continue in english", "speak in english"]):
            self.set_preferred_language("en")
            return True
        return False

    def update_topic(self, topic: str) -> None:
        """Updates the active conversational topic in Python memory."""
        if topic and topic != self.last_discussed_topic:
            print(f"[CallSession {self.call_id[:8]}] Active Topic: {self.last_discussed_topic} -> {topic}")
            self.last_discussed_topic = topic
            if self.booking_stage == "greeting":
                self.booking_stage = "discovery"

    def update_user_info(self, name: Optional[str] = None, phone: Optional[str] = None, city: Optional[str] = None, intent: Optional[str] = None, notes: Optional[str] = None) -> None:
        """Updates collected user entities across conversational turns."""
        if name: self.collected_user_info["name"] = name
        if phone: self.collected_user_info["phone"] = phone
        if city: self.collected_user_info["city"] = city
        if intent: self.collected_user_info["intent"] = intent
        if notes: self.collected_user_info["notes"] = notes
        
        if self.collected_user_info["name"] and self.collected_user_info["phone"]:
            self.booking_stage = "lead_captured"

    def get_session_context_prompt(self) -> str:
        """
        Returns a formatted memory context block representing Python-managed session state.
        Gemini consumes this state dynamically without owning it.
        """
        info_str = ", ".join([f"{k}: {v}" for k, v in self.collected_user_info.items() if v]) or "None"
        lang_label = {"en": "English", "hi": "Hindi", "gu": "Gujarati", "multi": "Multilingual/Code-mixed"}.get(self.preferred_language, "English")
        return (
            f"[PYTHON SESSION MEMORY & STATE]\n"
            f"- Preferred Language: {lang_label} ({self.preferred_language}) - respond in this language immediately.\n"
            f"- Active Topic in Discussion: {self.last_discussed_topic or 'General Inquiry'}\n"
            f"- Current Booking Stage: {self.booking_stage}\n"
            f"- Collected User Info: {info_str}\n"
            f"- Turn History Count: {len(self.conversation_history)}"
        )

    def transition_state(self, new_state: str) -> None:
        """Transitions the call state machine and logs the change."""
        if self.state != new_state:
            print(f"[CallSession {self.call_id[:8]}] State: {self.state} -> {new_state}")
            self.state = new_state

    def add_transcript(self, text: str, role: str = "user") -> None:
        """Appends a completed utterance to the permanent conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": text.strip()
        })

    @property
    def has_unconsumed_transcript(self) -> bool:
        """Returns True if there are any unconsumed interim or final transcript fragments."""
        return bool(self.final_transcripts or self.interim_transcript or self.transcript_buffer)

    @property
    def has_finalized_transcript(self) -> bool:
        """Returns True if there is at least one confirmed final transcript."""
        return bool(self.final_transcripts)

    def append_stt_fragment(self, text: str, is_final: bool = False) -> None:
        """
        Receives live transcription fragments from voice streams.
        Partial transcripts only update interim buffer without replacing finalized text.
        Final transcripts append to confirmed history and overwrite pending interim text.
        """
        clean_text = text.strip()
        if not clean_text:
            return
        self.transcript_buffer.append(clean_text)
        if is_final:
            self.final_transcripts.append(clean_text)
            self.interim_transcript = ""
        else:
            self.interim_transcript = clean_text

    def purge_interim_state(self) -> None:
        """
        Clears stranded interim transcripts and unfinalized fragments during unexpected
        network disconnection while preserving confirmed final transcripts.
        """
        self.interim_transcript = ""
        self.transcript_buffer = list(self.final_transcripts)

    def _merge_and_deduplicate(self, fragments: list[str]) -> str:
        """Merges text fragments while stripping out duplicate overlapping words at boundaries."""
        if not fragments:
            return ""
            
        merged_words: list[str] = []
        
        def clean_word(w: str) -> str:
            return re.sub(r'^\W+|\W+$', '', w).lower()
            
        for frag in fragments:
            frag_words = frag.strip().split()
            if not frag_words:
                continue
                
            if not merged_words:
                merged_words = frag_words
                continue
                
            # Detect overlapping word sequence at the boundary of merged_words and frag_words
            max_overlap = min(len(merged_words), len(frag_words))
            overlap_len = 0
            for k in range(max_overlap, 0, -1):
                tail = [clean_word(w) for w in merged_words[-k:]]
                head = [clean_word(w) for w in frag_words[:k]]
                if tail == head:
                    overlap_len = k
                    break
                    
            # Append only non-overlapping tokens
            merged_words.extend(frag_words[overlap_len:])
            
        # Eliminate accidental consecutive stutter repeats (e.g. "I I", "not not")
        valid_repeats = {"that", "had", "can", "is", "where", "there"}
        deduped_words: list[str] = []
        for w in merged_words:
            if deduped_words:
                prev_clean = clean_word(deduped_words[-1])
                curr_clean = clean_word(w)
                if curr_clean == prev_clean and curr_clean not in valid_repeats and len(curr_clean) > 1:
                    # Retain token with richer punctuation if available
                    if len(w) > len(deduped_words[-1]):
                        deduped_words[-1] = w
                    continue
            deduped_words.append(w)
            
        return " ".join(deduped_words).strip()

    def get_merged_transcript(self, include_interim: bool = False) -> str:
        """
        Returns the merged, deduplicated transcript for the turn without clearing buffers.
        By default, unconfirmed interim transcripts are excluded to ensure LLM receives only finalized text.
        """
        parts = list(self.final_transcripts)
        if include_interim and self.interim_transcript:
            parts.append(self.interim_transcript)
        elif not parts and not self.interim_transcript and self.transcript_buffer:
            parts.append(self.transcript_buffer[-1])
            
        return self._merge_and_deduplicate(parts)

    def clear_transcripts(self) -> None:
        """Clears transcript buffers ONLY after the LLM has begun consuming them."""
        self.final_transcripts.clear()
        self.interim_transcript = ""
        self.transcript_buffer.clear()

    def consume_transcript(self) -> str:
        """
        Legacy consumer: merges finalized transcripts and clears the buffers.
        """
        text = self.get_merged_transcript(include_interim=False)
        if not text and self.interim_transcript:
            text = self.get_merged_transcript(include_interim=True)
        self.clear_transcripts()
        return text
