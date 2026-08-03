# Phase 6 — Outbound follow-up calls (2 days)

## 1. Objective
Use the same pipeline to call leads back — e.g. a lead who explicitly requested a callback — since Twilio (like most telephony providers) can originate calls, not just receive them.

## 2. Prerequisites
- Phase 5's live pipeline working reliably for inbound calls.

## 3. Scope — In
- An internal trigger (a small script or an internal-only endpoint, not exposed publicly) that tells Twilio to originate a call to a lead's number and connects it to the same media-stream pipeline, with a different opening line appropriate to a callback ("Hi, following up on your enquiry about a smile consultation...").
- A simple allow-list / rate limit so testing never accidentally calls the wrong numbers repeatedly.
- Reuse of the Phase 5 pipeline's conversation logic, with the intent pre-set to "follow-up" rather than starting from the general FAQ menu.

## 4. Scope — Out (deferred)
- Bulk/campaign calling of any kind.
- Automated DND-list compliance tooling — this is a real regulatory concern (see Risks) that v1 handles by policy, not by building compliance software.

## 5. Files to create / modify
```
backend/app/routes/
└── internal_callback.py     # internal-only trigger, not publicly exposed
agent/
└── pipeline.py                # extended to accept an "opening intent" parameter
```

## 6. Data model slice
No new tables — reuses `Lead` and `Call`, with `Call.direction = "outbound"` distinguishing these.

## 7. API surface
```
POST /internal/trigger-callback   — internal-only, not exposed to the public internet
```

## 8. Frontend routes / components
N/A this phase.

## 9. External integrations (this phase)
Twilio outbound call origination, reusing the Phase 5 media-stream pipeline.

## 10. Acceptance — "Done when"
- Triggering the endpoint for your own verified number results in your phone ringing and a coherent, appropriately-framed outbound conversation.

## 11. Risks & open questions
- **Regulatory weight.** Outbound calling carries real obligations in India (DND registry, TRAI regulations). v1's policy: only call numbers that explicitly opted in or requested a callback during an inbound call — never a cold or purchased list. This is a policy decision to document, not a technical safeguard to code around.
- **Trial account restriction still applies** — outbound test calls during dev are limited to your own verified number until Twilio is upgraded.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list, especially risk #8 on outbound-calling compliance.
