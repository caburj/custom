# Phase 11: Hydration and Trace Management - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Traces from previous sessions hydrate from IndexedDB on page load and appear in the sidebar immediately. Users can select traces via checkboxes and delete them in bulk. Only complete traces are persisted; incomplete traces lost on refresh are accepted data loss.

</domain>

<decisions>
## Implementation Decisions

### Hydration experience
- Instant render on page load — no loading skeleton or spinner. IDB reads are assumed fast enough.
- Load ALL stored traces from IDB, not just the most recent session.
- Hydrated traces have a subtle visual indicator distinguishing them from live traces (Claude picks the specific indicator style).
- The indicator persists for the entire session — it does not disappear even if the trace receives new live events. It's about source, not staleness.

### Delete interaction
- Always-visible checkboxes on every trace entry in the sidebar — no hover-to-reveal.
- Checkbox selection is separate from clicking a trace to view its detail. Checkboxes are for bulk actions only.
- "Select all" checkbox in the sidebar header to toggle all traces selected/deselected.
- Action buttons (delete, and later export) always visible in the header area, but disabled when nothing is selected.
- Delete is always instant — no confirmation dialog, no undo toast, regardless of how many traces are selected.

### Clear all flow
- No separate "Clear all" button — select-all + delete covers this use case.
- After deleting all traces, the sidebar returns to its original empty state message.
- Note: This deviates from MGMT-02's confirmation dialog requirement — user explicitly chose instant delete with no confirmation.

### Sidebar state transitions
- Latest traces always at the top, consistent with current ordering behavior.
- Empty state message shown when IDB is empty (first visit or after clearing all). Disappears when first trace arrives.
- Orphan bus events (arriving for a trace that wasn't persisted because it was incomplete at refresh) are dropped silently — accepted data loss for incomplete traces.

### Claude's Discretion
- Specific style of the hydrated-trace indicator (muted opacity, small icon, color treatment, etc.)
- Ordering behavior when a hydrated trace receives new live events
- Any animation/transition when traces are deleted from the sidebar

</decisions>

<specifics>
## Specific Ideas

- Action buttons placement in the header should accommodate future "Export" button (Phase 12) — design the header action area with that in mind.
- The checkbox + header action pattern is similar to email clients (Gmail's select + action bar).

</specifics>

<deferred>
## Deferred Ideas

- Export button in the header action area — Phase 12

</deferred>

---

*Phase: 11-hydration-and-trace-management*
*Context gathered: 2026-02-22*
