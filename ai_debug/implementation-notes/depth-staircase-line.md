# Depth Staircase Line — Implementation Notes

The sidebar tree in the AI Debugger uses a continuous SVG line that flows
vertically along the left edge, stepping rightward at each nesting depth.
Transitions between depth levels use smooth S-curves (cubic bezier).

```
|  root trace
|  root iteration
|  root tool call
 \
  |  subagent trace (depth 1)
  |  subagent iteration
  |  subagent tool call
   \
    |  sub-subagent (depth 2)
   /
  |  back to depth 1
 /
|  back to root
```

## Architecture

The tree is rendered as a **flat list** of `<div>` rows (trace, iteration,
tool call) by OWL's `t-foreach`. Each row carries a `depth` property (0–4).
A single `<svg>` element overlays the scroll container and draws the
staircase path. The SVG scrolls naturally with the row content.

### Why SVG?

| Approach | S-curves | Dynamic updates | Complexity |
|----------|----------|-----------------|------------|
| **SVG overlay** | Native cubic bezier | Reactive getter, auto re-render | Low |
| CSS pseudo-elements | Impossible (no beziers) | Needs JS class management | Medium |
| Canvas | Manual bezierCurveTo | Imperative redraw on every change | High |
| CSS gradients | No curves possible | N/A | N/A |

SVG won because it supports true cubic bezier curves natively, integrates
cleanly with OWL's reactive rendering (computed getter → `t-foreach`), and
requires zero DOM measurement.

## Key Files

| File | What |
|------|------|
| `app.js` — `depthLinePaths` getter | Computes `[{d, color}, ...]` path descriptors |
| `app.js` — `depthLineTotalHeight` getter | SVG height from summing row heights |
| `app.xml` — `<svg class="ai-depth-line-svg">` | Renders paths via `t-foreach` |
| `app.scss` — `.ai-depth-line-svg` | Absolutely positioned, `z-index: 1`, `pointer-events: none` |

## How `depthLinePaths` Works

### Pass 1: Compute y-positions

Walk `sidebarNodes` and accumulate y-positions using known CSS row heights:
- Trace rows: 44px (`min-height` in SCSS)
- Iteration / tool call rows: 34px (fixed `height` in SCSS)

No DOM measurement needed — heights are constants kept in sync with SCSS.

```
pos = [
  { top: 0,   bottom: 44,  depth: 0 },  // trace row
  { top: 44,  bottom: 78,  depth: 0 },  // iteration row
  { top: 78,  bottom: 112, depth: 0 },  // tool call row
  { top: 112, bottom: 156, depth: 1 },  // subagent trace
  ...
]
```

### Pass 2: Group consecutive same-depth rows

Collapse runs of identical depth into groups with `yTop` / `yBot`:

```
groups = [
  { depth: 0, yTop: 0,   yBot: 112 },
  { depth: 1, yTop: 112, yBot: 224 },
  { depth: 0, yTop: 224, yBot: 300 },
]
```

### Pass 3: Build SVG path segments

For each group, emit two things:

**1. Vertical line segment** at the group's x-position, trimmed by half the
transition height at each end to leave room for the S-curve:

```
x = BASE_X + depth * STEP_X
M x,yStart  L x,yEnd
```

**2. S-curve transition** to the next group (if any) using a cubic bezier:

```
boundary = group.yBot  (where depth changes)
x1 = current depth's x-position
x2 = next depth's x-position

M x1,(boundary - 8)
C x1,boundary  x2,boundary  x2,(boundary + 8)
```

This cubic bezier departs vertically from `x1`, shifts horizontally at the
boundary, and arrives vertically at `x2` — producing a smooth sigmoid
S-curve.

## Constants

Defined as static properties on `AiDebugApp`:

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEPTH_LINE_BASE_X` | 8 | x-position of depth-0 line |
| `DEPTH_LINE_STEP_X` | 8 | Horizontal offset per depth level |
| `DEPTH_LINE_TRANSITION_H` | 16 | Vertical space for S-curve (8px above + 8px below boundary) |
| `DEPTH_LINE_COLORS` | 5 hex values | Per-depth stroke colors (blue, teal, purple, amber, rose) |
| `ROW_H_TRACE` | 44 | Trace row height — must match SCSS `.ai-tree-trace-row min-height` |
| `ROW_H_DEFAULT` | 34 | Iter/tc row height — must match SCSS `.ai-tree-row height` |

## Styling

- The SVG has `z-index: 1` so it renders above row backgrounds (hover,
  selection, ancestor highlights) while `pointer-events: none` lets clicks
  pass through to the rows.
- All rows have a uniform `padding-left: 46px` to clear the SVG area.
- Depth > 0 rows also get a subtle `rgba(color, 0.04)` background tint via
  `.ai-depth-N` CSS classes.

## Reactivity

`depthLinePaths` is a computed getter that reads `this.sidebarNodes` (which
reads from reactive `this.traces`). Any trace mutation (new iteration, tool
call started, subagent spawned) automatically triggers OWL re-render, which
diffs the SVG `<path>` elements efficiently.
