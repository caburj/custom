# Phase 18: Display Components and Animation - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Render time and token metrics at a glance in the sidebar and drill into per-iteration breakdowns in detail panels. Data layer (Phase 16-17) already provides token counts, durations, and per-iteration timing. This phase builds the display components and live timer animation on top of that data.

Requirements: SIDE-01, DETL-01, DETL-02, DETL-03

</domain>

<decisions>
## Implementation Decisions

### Metrics formatting
- Smart abbreviation for token counts: exact under 1,000; "3.4k" for 1,000+; "1.2M" for 1,000,000+
- Adaptive time units: 850ms, 1.2s, 2m 14s — pick the most natural unit based on magnitude
- Middle dot separator between metrics: "1.2s · 3.4k tok"
- Sidebar metrics line shows input→output split, not just total (e.g. "1.2s · 1.2k→ 2.2k tok")

### Table design (LoopDetail Metrics tab)
- Column order: # (iteration) | Duration | Input | Output | Cached | Reasoning
- Scrollable table — all rows always rendered, no collapsing
- Totals row: bold text with horizontal rule/top border above (accounting style)
- Zero-value cells display as "–" dash to reduce visual noise (all columns always visible)

### Live timer UX
- Timer replaces the duration chip in the detail panel header while trace is running
- Pulsing animation (opacity or subtle scale) on the duration chip while running to indicate live counting
- Instant freeze on completion — pulse stops, final duration displayed, no transition animation
- Sidebar metrics line also updates live as iterations complete, showing partial totals while running

### Visual hierarchy
- Sidebar metrics line: secondary text (smaller font, muted color) below the trace name
- Metrics table: compact data-dense styling — tighter padding, reduced row height, optimized for scanning numeric data
- Numbers use normal proportional figures (app's default font), not tabular/monospace

### Claude's Discretion
- IterationDetail header chip colors (monochrome vs color-coded by metric type)
- Exact spacing, padding, and font sizes
- Error state handling
- Pulsing animation exact parameters (timing, opacity range)

</decisions>

<specifics>
## Specific Ideas

- Sidebar compact format example: "1.2s · 1.2k→ 2.2k tok"
- Middle dot separator matches the roadmap example style
- Table should feel data-dense like a developer tools panel, not a spacious UI table

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 18-display-components-and-animation*
*Context gathered: 2026-02-24*
