# Phase 1: Data Models and Instrumentation - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Persistent trace models (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`) plus a generator yield passthrough that captures every agentic loop event without altering loop behavior. This is the foundational data layer — Phase 2 (views) and Phase 3 (live panel) build on top of it.

</domain>

<decisions>
## Implementation Decisions

### State snapshot strategy
- State snapshots captured **per tool call** (before and after each individual tool execution)
- Always store **full state** — no truncation regardless of size
- Claude's Discretion: whether to chain from iteration-start baseline or pure tool-call chain for the 'before' snapshot

### Large payload handling
- Messages arrays and raw LLM responses stored **always verbatim** — no truncation
- Tool call results (args and return values) stored **always verbatim** — consistent policy across all captured data
- Use **Json fields** (Odoo 17.0+ native JSON support) for all JSON data — not Text fields
- **Binary content** (base64-encoded images): strip and replace with placeholder (`{binary: 'image/png', size: 12345}`). Future enhancement: save stripped binaries as `ir.attachment` and link back

### Module identity
- Technical name: `ai_debug`
- Category: Technical
- Not an application (regular module — no Apps grid tile)
- Menu location: Settings > Technical > AI Debug
- Display name: "AI Debug"

### Capture failure behavior
- On instrumentation error: **log warning** via `_logger.warning()` and skip the record — loop continues unaffected
- Transaction strategy: **separate cursors** (`registry.cursor()`) for trace writes — traces committed independently, survive loop rollbacks
- When config param `ai_debugger.enabled` is off: override remains active as **no-op passthrough** (checks flag, returns immediately)

### Access & retention
- Security access: **admin only** (Administration/Settings group)
- Retention config: **ir.config_parameter only** (`ai_debugger.retention_days`, default 7) — no Settings UI field
- Autovacuum cron deletes traces older than retention period

### Claude's Discretion
- Exact model field types and naming beyond the Json field decision
- Internal architecture of the generator passthrough
- Savepoint vs cursor strategy for partial writes within a single trace
- How to handle the error-case trace preservation (CAPT-08) with separate cursors

</decisions>

<specifics>
## Specific Ideas

- Binary content stripping should leave a note/TODO for future `ir.attachment` storage — don't lose the intent even though it's not built now
- Separate cursor pattern should follow the established Odoo pattern used by `bus.bus` (`registry.cursor()` in postcommit-style blocks)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-data-models-and-instrumentation*
*Context gathered: 2026-02-20*
