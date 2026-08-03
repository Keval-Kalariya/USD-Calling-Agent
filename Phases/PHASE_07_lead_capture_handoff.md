# Phase 7 — Lead capture & staff handoff (2 days)

## 1. Objective
Make captured leads actually useful to the business — notify a real person, rather than letting leads sit silently in a database.

## 2. Prerequisites
- Phase 5's `Lead` capture working end-to-end on live calls.

## 3. Scope — In
- On lead capture, send a notification to a staff inbox/channel — free options: email via SMTP or a Gmail app password, or a free-tier Telegram/WhatsApp bot message — containing the caller's number, city, intent, and a link to the transcript.
- A minimal read-only `/admin/leads` page (or, if a full page feels like too much this phase, a simple CSV export script) so staff can see captured leads without needing database access.

## 4. Scope — Out (deferred)
- Full CRM integration — it's not yet known whether the business has an existing CRM; flagged as an open question rather than assumed.

## 5. Files to create / modify
```
backend/app/
├── notify/
│   └── staff_notify.py     # email or Telegram/WhatsApp bot notification
└── routes/
    └── admin_leads.py        # read-only leads view or CSV export
```

## 6. Data model slice
No new tables — reads from the existing `Lead` table.

## 7. API surface
```
GET /admin/leads   — read-only, or a scripts/export_leads.py CSV alternative
```

## 8. Frontend routes / components
A minimal read-only leads list (plain HTML table is sufficient for v1 — no need for a JS framework here).

## 9. External integrations (this phase)
Whichever notification channel is chosen (SMTP email, or a Telegram/WhatsApp bot API).

## 10. Acceptance — "Done when"
- A test call that captures a lead results in a real notification landing in a real inbox/chat within seconds of the call ending.
- Staff can view or export the current lead list without needing direct database access.

## 11. Risks & open questions
- **Notification channel not yet chosen by the business.** Default to email for v1 (lowest friction, zero new accounts needed) and revisit once there's feedback on whether staff actually check it promptly.
- **Unknown existing CRM.** Worth a direct question to the business before Phase 8 — if a CRM already exists, routing leads there directly may be more valuable than a bespoke admin page.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
