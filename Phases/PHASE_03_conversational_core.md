# Phase 3 — Conversational core (LLM brain, text-only) (3 days)

## 1. Objective
Design the actual conversation a caller has — intents, system prompt, guardrails — and test it purely as text, before any audio is in the loop. Fixing a bad conversation design is far cheaper here than after Phase 5 wires it into a live call.

## 2. Prerequisites
- Phase 0's chosen LLM provider key validated.

## 3. Scope — In
- `CONVERSATION_DESIGN.md`: documents the call opening (including a brief recording/AI-disclosure line), and the core intents the agent must handle:
  1. **Find a Smile Designer dentist near me** (by city).
  2. **Book / request a consultation** — captured as a lead, not a live booking (see INDEX.md risk #3).
  3. **Verify warranty** — point the caller to the existing verify-warranty flow / a human who can check it.
  4. **General FAQ** — what smile design is, ballpark expectations, before/after, which cities are covered.
  5. **Speak to a human / not interested** — clean exit path, no pressure.
- System prompt for the chosen LLM, with guardrails: never give clinical/medical advice, never quote a price you don't have data for, escalate anything uncertain to a human callback rather than guessing.
- Tool-use / function-calling definitions the LLM can invoke: `capture_lead(name, phone, city, intent, notes)`, `lookup_dentists(city)` (stubbed until Phase 4), `get_faq(topic)`.
- A CLI chat-loop harness simulating a caller in text, so the prompt and tools can be iterated on quickly without touching audio.

## 4. Scope — Out (deferred)
- Audio integration → Phase 5.
- Real dentist directory data → Phase 4 (this phase can stub `lookup_dentists` with fake data).

## 5. Files to create / modify
```
CONVERSATION_DESIGN.md
agent/
├── prompts/
│   └── system_prompt.md
├── tools/
│   ├── capture_lead.py
│   ├── lookup_dentists.py    # stubbed, real implementation in Phase 4
│   └── get_faq.py
└── cli_harness.py
```

## 6. Data model slice
`Lead` (id, call_id FK, name, phone, city, intent, notes, created_at).

## 7. API surface
Internal function-calling tools only (not HTTP endpoints yet): `capture_lead()`, `lookup_dentists(city)`, `get_faq(topic)`.

## 8. Frontend routes / components
N/A this phase.

## 9. External integrations (this phase)
The chosen LLM provider, called directly from the CLI harness — no telephony or audio involved.

## 10. Acceptance — "Done when"
- The CLI harness handles all five intents sensibly across at least 10 scripted test conversations, including at least one adversarial one (caller is rude, caller gives nonsense input, caller asks for a price you don't have).
- Captured leads from the harness land correctly in the `Lead` table/store.

## 11. Risks & open questions
- **Hallucinated specifics:** without Phase 4's real data, the model may invent dentist names or prices during this phase's testing — expected and fine here, but the guardrail language needs to explicitly forbid it once Phase 4's real `lookup_dentists` is wired in.
- **LLM free-tier rate limits:** note your provider's requests-per-minute ceiling now — it becomes relevant once Phase 8 runs multiple test calls back to back.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
