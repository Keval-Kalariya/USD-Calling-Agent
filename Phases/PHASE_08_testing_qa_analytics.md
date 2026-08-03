# Phase 8 — Testing, QA & call analytics (2–3 days)

## 1. Objective
Build confidence that the agent behaves well before pointing a real marketing phone number at it.

## 2. Prerequisites
- Phases 5, 6, and 7 all working end-to-end.

## 3. Scope — In
- A scripted test-call checklist covering realistic scenarios: happy-path booking lead, caller names a city not in the directory, an irritated caller, dead air/silence, a caller who mixes in Hindi/Gujarati, a caller asking for pricing you don't have, a caller asking to speak to a human, and a caller who hangs up mid-sentence.
- Basic analytics, reusing Phase 7's admin page or a simple query script: calls per day, average call duration, intent distribution, leads captured, and how often the human-handoff path was triggered.
- A weekly human review of a sample of transcripts, specifically to catch bad or off-brand answers early, before volume increases.

## 4. Scope — Out (deferred)
- A full BI dashboard — worth revisiting only if/when this moves to a paid, higher-volume tier.

## 5. Files to create / modify
```
docs/
└── test_call_checklist.md
scripts/
└── call_analytics.py        # simple query/report script
```

## 6. Data model slice
No new tables — analytics reads from existing `Call` and `Lead` tables.

## 7. API surface
No new endpoints required — `call_analytics.py` can run as a CLI report; a simple `/admin/analytics` view can reuse Phase 7's page if convenient.

## 8. Frontend routes / components
Optional lightweight addition to the Phase 7 admin page showing the analytics summary above.

## 9. External integrations (this phase)
None new.

## 10. Acceptance — "Done when"
- Every scenario on the checklist passes on a live test call.
- A week of test-call data produces a coherent analytics summary (not just raw logs).
- At least one weekly transcript review has happened and any issues found have been logged.

## 11. Risks & open questions
- No new risks — this phase exists specifically to surface problems from earlier phases before real callers hit them.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
