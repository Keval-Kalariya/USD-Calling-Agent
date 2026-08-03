# Phase 3 — Conversation Design

## Overview

The USD Calling Agent supports **three languages**: English (`en`), Hindi (`hi`), and Gujarati (`gu`). The conversation design is built around a graceful language-selection flow followed by intent-driven routing. All flows must work identically across all three languages.

---

## 1. Call Opening

The agent always opens in **English** because the caller's language is unknown at this point. The opening must include:
- A clear AI/recording disclosure (legally advisable in most Indian jurisdictions).
- An immediate language choice prompt.

**Scripted Opening (English):**
> "Hello! Thank you for calling Ultimate Smile Design. This call may be recorded and is handled by an AI assistant. You can speak to me in English, Hindi, or Gujarati — please tell me which you prefer, or simply start speaking and I'll follow."

**Hindi fallback if caller starts in Hindi:**
> "नमस्ते! आप हिंदी में बात कर सकते हैं।"

**Gujarati fallback if caller starts in Gujarati:**
> "નમસ્તે! તમે ગુજરાતીમાં વાત કરી શકો છો."

---

## 2. Language Handling

### 2.1 Explicit Language Selection
The caller may say:
- "English", "Hindi", "Gujarati"
- "हिंदी में बोलो", "ગુજરાતીમાં", "speak in English"

The agent locks the session language and confirms:
- `en`: "Great, I'll continue in English."
- `hi`: "बिल्कुल, मैं हिंदी में बात करूँगा।"
- `gu`: "જ઼ĶĶ, હું ગુજરાતીમાં વાત કરીશ."

### 2.2 Implicit Detection (Natural Start)
If the caller speaks without explicitly choosing a language, the agent infers from the first utterance:
- Detects dominant script/language from STT output.
- Sets session `preferred_language` immediately.
- Confirms with a short sentence in the detected language.

### 2.3 Code-Switching Rules
Code-switching (Hinglish / Gujlish) is expected and must not break flow.

| Example Input | Rule |
|---|---|
| `"મારે Surat માં dentist જોઈએ"` | Treat as Gujarati; respond in Gujarati, retain English nouns. |
| `"Mujhe Ahmedabad mein smile design karana hai"` | Treat as Hindi; respond in Hindi. |
| `"I want dentist in Surat yaar"` | Treat as English; casual tone, English response. |
| Ambiguous / split 50-50 | Ask: "Should I continue in Hindi or English?" |

### 2.4 Language Fallback
If the agent cannot determine the language after 2 utterances:
> "I'm sorry, I can best assist you in English, Hindi, or Gujarati. Which would you prefer?"
> "माफ कीजिए, क्या आप हिंदी में बात करना चाहेंगे?"
> "માફ કરશો, શું તમે ગુજરાતીમાં વાત કરી શકો છો?"

---

## 3. Core Intents

All 5 intents must work in all 3 languages. The agent detects intent from the caller's phrasing and routes accordingly.

### Intent 1: Find a Smile Designer Dentist
**Trigger phrases:**
- `en`: "find a dentist", "dentist near me", "Smile Designer in [city]"
- `hi`: "dentist ढूंढना है", "मुझे [city] में dentist चाहिए"
- `gu`: "dentist જોઈએ", "[city]માં Smile Designer"

**Flow:**
1. Ask for city if not mentioned.
2. Call `lookup_dentists(city, language)`.
3. Read out 1–2 nearest options, offer to capture lead for callback.

### Intent 2: Book / Request a Consultation (Lead Capture)
**Trigger phrases:**
- `en`: "book appointment", "I want to consult", "schedule a visit"
- `hi`: "appointment लेना है", "consultation चाहिए"
- `gu`: "appointment જોઈએ", "consultation લેવી છે"

**Flow:**
1. Confirm city and preferred dentist (if known from Intent 1).
2. Collect: name → phone → city → notes (optional).
3. Call `capture_lead(...)`.
4. Confirm: "We'll have someone call you back within 24 hours."

### Intent 3: Verify Warranty
**Trigger phrases:**
- `en`: "warranty", "guarantee", "how long does it last"
- `hi`: "वारंटी", "गारंटी कितनी है"
- `gu`: "warranty", "ગેરંટી"

**Flow:**
1. The agent does NOT verify warranty directly (no live DB access in v1).
2. Offer to connect caller to a human specialist via callback lead capture.
3. Call `capture_lead(intent="warranty_verification", ...)`.

### Intent 4: General FAQ
**Trigger phrases:**
- `en`: "what is smile design", "how long does it take", "which cities"
- `hi`: "smile design क्या होता है", "कितना समय लगता है"
- `gu`: "smile design શું છે", "ક્યાં ક્યાં cities"

**Flow:**
1. Identify topic from phrase (process, timeline, cities, before_after, cost).
2. Call `get_faq(topic, language)`.
3. Read out the FAQ answer.
4. Offer to book a consultation.

### Intent 5: Speak to a Human / Not Interested
**Trigger phrases:**
- `en`: "speak to someone", "human please", "not interested", "bye"
- `hi`: "इंसान से बात करनी है", "रहने दो", "नहीं चाहिए"
- `gu`: "માણસ સાથે વાત કરવી છે", "ઠીક છે રહેવા દો"

**Flow:**
1. Acknowledge gracefully. Zero pressure.
2. Offer callback option one final time.
3. If declined, end call:
   - `en`: "Thank you for calling Ultimate Smile Design. Have a great day!"
   - `hi`: "Ultimate Smile Design को call करने के लिए धन्यवाद। आपका दिन शुभ हो!"
   - `gu`: "Ultimate Smile Design ને call કરવા બદલ આભાર. આપનો દિવસ સારો રહે!"

---

## 4. State Machine

```
[CALL_START]
    ↓
[LANGUAGE_SELECTION] — lock preferred_language
    ↓
[INTENT_DETECTION] — route to one of 5 intents
    ↓
[INTENT_FLOW] (find_dentist / capture_lead / faq / warranty / exit)
    ↓
[LEAD_CAPTURE?] — optional, offer at end of every intent except exit
    ↓
[CALL_END] — thank caller, close connection
```

---

## 5. Guardrails Summary

| Rule | Behaviour |
|---|---|
| Medical advice request | Decline, recommend consulting a dentist directly |
| Price quote request | State "prices vary by clinic; our team will share accurate quotes during callback" |
| Abusive / rude input | Respond calmly, offer to end call |
| Booking for a third party | Capture their name + phone for callback |
| City not in network | Acknowledge, offer to check expansion, capture lead for future contact |
