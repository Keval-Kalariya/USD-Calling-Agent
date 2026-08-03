# Phase 4 — Dentist directory & lead data model (2 days)

## 1. Objective
Give the agent real data to work from instead of letting the LLM improvise dentist names, cities, or clinic details.

## 2. Prerequisites
- Phase 3's `lookup_dentists(city)` stub in place, ready to be backed by real data.

## 3. Scope — In
- `data/dentists.json` (or a small DB table) seeded from the public certified-dentists directory — city, dentist name, clinic name, contact number, active/inactive flag. Known cities from the public site include Ahmedabad, Surat, Rajkot, Mumbai, Jamnagar, Indore, and others — compile the initial list manually or with a light one-time scrape.
- Wire `lookup_dentists(city)` to actually read this file/table and return real matches, replacing the Phase 3 stub.
- **Open question to resolve with the business, not assume:** does Ultimate Smile Design (or Advance Dental Export) have any internal scheduling/calendar system with live appointment slots? If yes, that changes Phase 5's design meaningfully. If no — the v1 assumption stands: the agent captures a lead with preferred city/time, and a human team completes the actual booking.
- A small admin script to add/update/deactivate dentist entries in the directory without a code deploy.

## 4. Scope — Out (deferred)
- Live appointment-slot booking or calendar sync — flagged as a future, likely paid-tier feature contingent on the business's own scheduling system existing and being made accessible.

## 5. Files to create / modify
```
data/
└── dentists.json              # or dentists table if using a DB from this phase on
scripts/
└── manage_dentists.py          # add / update / deactivate entries
agent/tools/
└── lookup_dentists.py          # now reads real data instead of the Phase 3 stub
```

## 6. Data model slice
`Dentist` (id, name, city, clinic_name, phone, is_active).

## 7. API surface
No new HTTP endpoints — `lookup_dentists(city)` remains an internal tool call used by the LLM.

## 8. Frontend routes / components
N/A this phase — the admin script is CLI-only for now; a read-only web view can be added in Phase 7/8 if useful.

## 9. External integrations (this phase)
None — this is local data management. (If the business does expose an internal scheduling system, that integration would be scoped as an addition to this phase.)

## 10. Acceptance — "Done when"
- `lookup_dentists("Surat")` returns the known Surat dentists correctly.
- Adding a new dentist via the admin script requires no code change or redeploy.
- The "does a live scheduling system exist?" question has an explicit answer on record (even if the answer is "no, not yet").

## 11. Risks & open questions
- **Data drift:** this directory will drift from the live website over time as dentists join/leave the network — v1 has no auto-sync, and needs an owner and a refresh cadence, not a technical fix.
- **Scope creep risk:** if a real scheduling system does turn out to exist, resist folding live booking into this MVP — treat it as a defined addition to Phase 5's scope with its own estimate, rather than open-ending this phase.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
