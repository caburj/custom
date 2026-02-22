# Phase 12: Export and Import - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can download traces as a JSON file and restore them from a previously exported file. Covers export trigger, import flow with preview/confirmation, file format, and error handling. Does not include scheduled exports, cloud sync, or sharing URLs.

</domain>

<decisions>
## Implementation Decisions

### Trigger placement
- Export and Import buttons live in the sidebar header action bar, alongside existing select-all checkbox and delete controls
- Icon-only buttons (download icon for export, upload icon for import) — no text labels
- Export button is disabled when no traces are selected (same pattern as delete button)
- Import button is always enabled

### Import behavior
- Merge mode: imported traces are added alongside existing traces (no clearing)
- Duplicate handling: if an imported trace has the same ID as an existing one, overwrite with the imported version
- Preview before import: show a summary dialog ("12 traces found, 3 duplicates will be overwritten") with confirm/cancel
- No success toast — the sidebar updating with new traces is the feedback

### Export scope
- Exports only the selected (checked) traces — leverages Phase 11 checkbox selection
- Button is disabled when nothing is selected
- Full trace data exported — everything stored in IDB, complete fidelity for restore
- Raw JSON array of trace objects — no envelope or metadata wrapper

### File format
- Export filename: `ai-debug-traces-YYYY-MM-DD.json` (timestamped with export date)
- Import file picker restricted to `.json` files only

### Error feedback
- Errors shown inline in the import preview dialog (not as Odoo notifications)
- User-friendly message with technical hint: e.g. "Invalid file: expected JSON array of traces"
- All-or-nothing validation: if any trace in the file is invalid, reject the entire import
- Existing traces are never affected by a failed import

### Claude's Discretion
- Button ordering in the action bar (relative to checkbox and delete)
- Exact validation rules for what constitutes a "valid trace"
- Preview dialog layout and styling
- File download mechanism (blob URL vs other approach)

</decisions>

<specifics>
## Specific Ideas

- Export disabled state follows the same pattern as the delete button (disabled when no checkboxes selected)
- Preview dialog should show duplicate count so the user knows what will be overwritten before confirming

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 12-export-and-import*
*Context gathered: 2026-02-22*
