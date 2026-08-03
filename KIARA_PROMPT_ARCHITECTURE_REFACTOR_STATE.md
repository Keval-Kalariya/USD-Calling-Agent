# Kiara Prompt Architecture Refactoring — Handoff & State Context

This file serves as the definitive context checkpoint and state handoff for continuing the **Kiara Prompt Architecture Refactoring** in a new chat session without losing any context or progress.

---

## 1. Architectural Goal & Overview
We are refactoring Kiara's system prompt architecture to achieve ultra-low streaming latency, lower token usage (~85% reduction vs legacy prompt), and better long-term scalability while strictly preserving 100% of Kiara's elite luxury persona, multilingual capabilities, safety rules, and conversational quality. 

No changes are made to Twilio, STT, TTS, or foundational conversational flow.

### The Three-Layer Architecture:
1. **Layer 1 — Permanent Identity Prompt (Category 1)**: Core persona, voice tone, luxury positioning rules, multilingual guidelines, low-latency TTS formatting, anti-hallucination protocols, and immutable critical rules. *This is the ONLY part sent to Gemini as static system instructions on every turn.*
2. **Layer 2 — Factual Knowledge Base (Category 2)**: Domain facts, treatment details, FAQs, pricing policies, warranty terms, and clinic network coverage. *Stored in JSON and retrieved deterministically in Python prior to reaching Gemini.*
3. **Layer 3 — Dynamic Conversation Guidance (Category 3)**: Situational conversation flow templates, objection handling scripts, persuasion frameworks, VIP/privacy assurance, wedding event planning, and human transfer checklists. *Stored as modular JSON data and dynamically injected in Python only when relevant to the caller's intent or conversational stage.*

---

## 2. Work Completed & Verified So Far

### ✅ Phase A: Factual Knowledge Retrieval (Category 2) — COMPLETED & TESTED
- Created structured RAG-compatible knowledge bases: `data/faq_knowledge.json` and `data/covered_cities.json`.
- Built standalone retrieval abstraction `KnowledgeRetriever` and implemented `JSONFaqRetriever` in `agent/knowledge/retriever.py` with top_k ranked semantic/keyword scoring.
- Updated `CallSession` (`agent/session/call_session.py`) to manage language preferences, conversation stages, and entity memory directly in Python.
- Upgraded `GeminiStreamClient` (`agent/streaming/gemini_stream.py`) and `cli_harness.py` to perform pre-request Python retrieval and inject `[PYTHON SESSION MEMORY & STATE]` and `[RETRIEVED FACTUAL KNOWLEDGE FOR THIS TURN]` blocks dynamically.
- Verified via automated unit tests in `tests/test_retrieval_and_memory.py` (5/5 tests passing). Removed ~8,500 tokens of static domain facts from the prompt.

### ✅ Phase B: Architectural Audit of `system_prompt.md` — COMPLETED & APPROVED
- Performed a granular section-by-section audit of `agent/prompts/system_prompt.md` (~4,500 tokens remaining after Category 2 removal).
- Classified all remaining content into Category 1 (Core Identity to keep in prompt) and Category 3 (Dynamic Guidance to extract).

### ✅ Phase C: Category 3 Guidance Extraction (Steps 1, 2, & 3) — COMPLETED & AUDITED
- Created `data/guidance/` directory containing 7 separate, single-responsibility JSON modules:
  1. `data/guidance/objections.json`: 10 elite objection reframes (price, fear of pain, trust, time, competitors, etc.) + all 7 Elite Pain Points.
  2. `data/guidance/persuasion.json`: 7 Elite Persuasion Hooks + the 6 foundational reframing strategies (Investment, Craftsmanship, Confidence, Exclusivity, Comfort, Time).
  3. `data/guidance/booking.json`: Booking scripts + 3-tier Call-to-Action levels (Soft, Medium, Strong CTA).
  4. `data/guidance/privacy.json`: Privacy assurance scripts & VIP high-profile client handling protocols.
  5. `data/guidance/transfer.json`: 6 immediate transfer escalation rules, standard transfer scripts, and pre-transfer entity capture checklist.
  6. `data/guidance/emotional.json`: Emotion matching table across 9 states, empathy validation phrases, and discovery questions.
  7. `data/guidance/situational_flows.json`: AI Smile Preview exploration, wedding/milestone timelines, competitor comparisons, uncertainty reframes, and multilingual opening/closing variants.
- **Forensic Verification Audit Passed (100% Fidelity)**: Every Category 3 concept was verified word-for-word against `system_prompt.md`. Nothing was rewritten, shortened, paraphrased, or duplicated across modules. Every JSON entry includes explicit `"intent"` and keyword routing metadata.

---

## 3. Current Pause Point (Where We Left Off)
As per the strict approved instructions for Step 3:
- **ZERO deletions or modifications have been made to `system_prompt.md` yet regarding Category 3 removals.** We paused immediately after completing the verification audit so that the extracted JSON files could be confirmed before trimming the prompt.

---

## 4. Immediate Next Steps for the New Chat Session

When resuming work from this checkpoint, proceed directly with **Step 4** and **Step 5**:

### ⏳ Step 4 — Remove Extracted Category 3 Guidance from `system_prompt.md`
Remove the duplicate Category 3 sections from `agent/prompts/system_prompt.md` now that they reside in `data/guidance/*.json`:
- **Section 3**: Remove *Elite Pain Points* and *Elite Persuasion Hooks* (approx. lines 80–97).
- **Section 7**: Remove *Handling Objections (Elite-Class Specific)* sub-section (approx. lines 234–245).
- **Section 8**: Remove *Conversation Flow Templates & Booking CTA Levels* entirely (approx. lines 255–296).
- **Section 9**: Remove *Elite Persuasion Playbook* entirely (approx. lines 299–329).
- **Section 10**: Remove detailed *Human Transfer Protocol* scripts and checklists (approx. lines 332–353), keeping only a concise 20-word Category 1 routing instruction (*"If a caller requests a human, exhibits acute medical emergency, or needs unretrievable pricing, invoke human transfer protocol immediately"*).
- **Section 11**: Remove *Emotional Intelligence Guide, Empathy phrases, & Discovery Questions* entirely (approx. lines 356–388).

*Expected result: `system_prompt.md` will become an ultra-clean, lightweight ~1,950-token Category 1 Permanent Identity prompt (~13.8 KB).*

### ⏳ Step 5 — Implement Python Intent-Based Dynamic Guidance Injection
Update the Python pipeline (`agent/streaming/gemini_stream.py` and `agent/cli_harness.py`) to selectively load and inject guidance modules from `data/guidance/*.json`:
- Implement a lightweight intent/keyword scoring mechanism in Python (similar to our `KnowledgeRetriever` pattern).
- Based on conversational intent, inject the appropriate guidance module alongside retrieved factual knowledge:
  - Pain objection -> Inject `objections.json` (pain_fear)
  - Booking -> Inject `booking.json`
  - Privacy/VIP -> Inject `privacy.json`
  - Wedding/Events -> Inject `situational_flows.json`
  - Human transfer -> Inject `transfer.json`
  - Emotional caller -> Inject `emotional.json`
  - General FAQ -> Inject no guidance module unless needed.
- Append a `[DYNAMIC CONVERSATION GUIDANCE FOR THIS TURN]` block to the user prompt before sending to Gemini.

### ⏳ Step 6 — Verification & Testing
- Run all unit tests (`python -m pytest tests/test_retrieval_and_memory.py -v`) and create any required new tests for guidance module injection.
- Verify that total prompt tokens per turn drop to **~2,200 (FAQ turn) to ~2,400 (Objection turn)**, reducing latency by >75% compared to the legacy implementation while maintaining 100% conversational quality.
