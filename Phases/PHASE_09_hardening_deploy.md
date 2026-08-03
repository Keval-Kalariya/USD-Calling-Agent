# Phase 9 — Hardening & free-tier deployment (2–3 days)

## 1. Objective
Get the agent running somewhere persistent — not just your laptop plus ngrok — while still spending $0.

## 2. Prerequisites
- Phase 8's checklist passed.

## 3. Scope — In
- Deploy to a free or low-cost host that supports long-lived WebSocket connections (e.g. Render's free/starter tier, Fly.io's free allowance, or a low-cost VPS) — ngrok is dev-only, and Twilio needs a stable public webhook URL in production.
- Process supervision: systemd unit (or the host's equivalent) keeping the app alive; nginx in front if self-managing a VPS.
- Basic error alerting — even a simple email-on-unhandled-exception — so a crashed call fails loudly instead of silently.
- Secrets management on the host itself (never committed to the repo).
- Point the real Twilio number's webhook configuration at the production URL.

## 4. Scope — Out (deferred)
- High availability / multi-region — unnecessary at this validation stage.

## 5. Files to create / modify
```
deploy/
├── app.service          # systemd unit
└── nginx.conf             # if self-managing a VPS
```

## 6. Data model slice
No changes — same schema, now running against production-persisted storage rather than a dev machine.

## 7. API surface
Unchanged — same endpoints, now on a stable public URL.

## 8. Frontend routes / components
N/A this phase.

## 9. External integrations (this phase)
Whichever hosting provider is chosen; Twilio webhook reconfiguration.

## 10. Acceptance — "Done when"
- The phone number works reliably for 48 hours of real test traffic without a manual restart.
- A deliberately triggered error results in an alert actually being received.

## 11. Risks & open questions
- **WebSocket support varies across free tiers** more than typical web-app hosting does — confirm the chosen host explicitly supports long-lived WS connections before committing time to it, rather than discovering a limitation mid-deploy.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
