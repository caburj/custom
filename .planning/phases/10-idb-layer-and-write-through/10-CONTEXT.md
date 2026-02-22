# Phase 10: IDB Layer and Write-Through - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Create db.js with IndexedDB schema, define the trace object store, and wire fire-and-forget writes into existing bus event handlers so traces are durably written as agentic loops complete. Covers PERS-01 (auto-persist) and PERS-04 (graceful degradation). Hydration, delete/clear, and export/import are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Write timing
- Write on trace completion (loop end event), not per bus event
- In-flight traces are not persisted — a reload mid-loop simply loses the incomplete trace (no corruption, no partial records)
- No beforeunload flush — accept the loss of in-progress traces
- Fire-and-forget: write failures are logged via console.warn but do not block the UI
- No retry on write failure

### Degradation UX
- Show a subtle ephemeral mode indicator in the header/toolbar area when IndexedDB is unavailable
- Icon (e.g. crossed-out disk) with tooltip explaining: "IndexedDB unavailable — traces won't persist across refreshes"
- Dynamic detection: if a write fails mid-session, switch to ephemeral mode and show the indicator (not just a startup check)
- Console.warn on IDB unavailability in addition to the visual indicator

### Trace record shape
- UUID as the IDB key for each trace record (not tied to ai.session.id or any backend identifier)
- No IDB schema versioning until end of milestone — keep it simple, deal with migrations if needed later
- Record metadata beyond raw trace data: Claude's discretion (e.g. storedAt timestamp for Phase 11 hydration ordering)
- Record structure (full blob vs split): Claude's discretion based on existing reactive store data structures

### Claude's Discretion
- Exact record structure (full denormalized blob vs split) — decide based on existing store shape
- Whether to include metadata fields (storedAt, version tag) alongside trace data
- IDB database and store naming
- Exact icon and tooltip styling for ephemeral mode indicator

</decisions>

<specifics>
## Specific Ideas

- User noted that ai.session.id exists in the backend but should NOT be used as the IDB key — use a client-generated UUID instead
- "Avoid versioning until end of milestone" — keep the IDB schema as simple as possible for now

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 10-idb-layer-and-write-through*
*Context gathered: 2026-02-22*
