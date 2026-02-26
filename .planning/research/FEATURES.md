# Feature Research

**Domain:** Per-DB IndexedDB isolation for AI Debugger developer tool
**Researched:** 2026-02-26
**Confidence:** HIGH — grounded in direct inspection of the existing codebase, the Odoo `IndexedDB` utility, `session.db` usage patterns across the Odoo codebase, and the POS module as a reference implementation

---

## Scope Note

This milestone adds per-DB IndexedDB isolation to an existing, fully-functional tool. v1.1–v1.5 are shipped. The features below are scoped only to what v1.6 introduces. Everything prior is not reconsidered here.

**The problem:** The existing `db.js` uses a hardcoded `const DB_NAME = "ai_debug_traces"`. Developers who work across multiple Odoo databases (e.g., `mydb_prod`, `mydb_test`, `mydb_dev`) share one IDB instance. Traces from different DBs mix, and clearing traces in one context clears all of them.

**The solution:** Scope the IDB name by the active Odoo DB name, exactly as POS does with `point-of-sale-${pos_config_id}-${odoo.info?.db}`.

---

## Prerequisite: How Odoo Exposes the DB Name to JS

`session.db` is the standard Odoo pattern. It is available synchronously on page load.

- **Source:** `odoo.__session_info__` is JSON-inlined into the HTML page in the `<script>` block before any JS bundle loads (confirmed in `ai_debug/views/ai_debug_index.xml` line 14: `<t t-out="json.dumps(session_info)"/>`)
- **Python side:** `session_info["db"] = self.env.cr.dbname` in `web/models/ir_http.py` line 110
- **JS side:** `import { session } from "@web/session"` exports `odoo.__session_info__ || {}`; `session.db` is a plain string, available synchronously at module evaluation time
- **POS reference:** `get databaseName() { return \`point-of-sale-${odoo.pos_config_id}-${odoo.info?.db}\` }` in `point_of_sale/static/src/app/services/data_service.js` line 139

The AI Debugger already uses `session_info` from the same `webclient_rendering_context()` call in `controllers/main.py`. `session.db` is already present in the page.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Isolation of per-DB data is a basic expectation for any multi-tenant developer tool. Missing this makes cross-DB workflows unreliable.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| IDB name scoped to current DB | Without this, traces from different Odoo DBs collide in one store. A developer switching between `test` and `prod` sees mixed traces. | LOW | Change `DB_NAME` from `"ai_debug_traces"` to `` `ai_debug_${session.db}` ``. `session.db` is synchronous at module evaluation time. The `IndexedDB` instance is constructed once at module load — this is a one-line change in `db.js`. |
| No UI changes required | Isolation is invisible to the user — traces naturally belong to the current DB because the IDB name encodes it | LOW | Zero OWL component changes. The sidebar, detail panels, and all event handlers are unchanged. |
| Ephemeral mode still works | `probeIDB()` must succeed against the new per-DB IDB name, not the old shared one | LOW | `probeIDB()` uses the module-level `idb` instance. If the name changes correctly at construction, probe works against the right DB. No change needed. |

### Differentiators (What Makes This Correct)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| DB name from `session.db` (not URL parsing, not RPC) | Synchronous, reliable, uses the same source as all other Odoo frontend code. No async dependency on initialization order. | LOW | URL-based extraction would be fragile (multi-DB setups don't always encode DB in URL). RPC would add async complexity to `db.js` module initialization. `session.db` is the correct, zero-cost approach. |
| IDB name format: `ai_debug_${session.db}` | Human-readable in browser DevTools (Application > IndexedDB). A developer can see which DB the data belongs to without decoding. | LOW | Format matches the `ai_debug` module prefix. Underscore separator is readable and safe (Odoo DB names are ASCII identifiers). |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Migrate existing traces from `ai_debug_traces` to `ai_debug_${db}` | Preserve traces already stored under the old shared name | The old IDB contains traces from potentially multiple DBs mixed together. There is no field on a trace record that reliably identifies which Odoo DB it came from. Migration would require heuristics or a discriminator column that doesn't exist. For a developer tool, stale traces from a prior naming convention are not valuable enough to justify the complexity. | Accept the cutover: old traces in `ai_debug_traces` become invisible. Developers can re-run sessions to repopulate. The old IDB will sit inert in the browser and can be deleted manually via DevTools. |
| Cross-DB trace viewer (see traces from all DBs) | A developer running multiple DBs might want a unified view | Breaks the isolation guarantee that is the entire purpose of this milestone. Cross-DB queries would require opening multiple IDB instances and merging, with no reliable way to distinguish provenance. | Export/import already handles cross-session sharing. Each DB context stays isolated by design. |
| Store the Odoo DB name as a field on each trace record | Enable future cross-DB querying or display | Adds schema complexity for a feature that is explicitly out of scope (sidebar filter by DB is an anti-feature from PROJECT.md). The IDB name itself is the discriminator — no redundant field needed. | Let the IDB name be the single source of truth for DB provenance. |
| Auto-delete the old `ai_debug_traces` IDB | Clean up the orphaned shared IDB | Cannot be done safely from within the app — deleting a different named IDB than the one the app uses is unusual and could confuse the browser storage inspector. | Leave orphan for manual cleanup. It uses no runtime resources once the app opens a different IDB. IndexedDB storage is not charged against quota until accessed. |

---

## Feature Dependencies

```
[session.db available at module load time]
    └──required by──> [Scoped IDB name construction in db.js]
                          └──required by──> [All IDB operations: read, write, delete, probe]

[Scoped IDB name]
    └──provides──> [Natural per-DB isolation — no UI changes needed]
    └──makes orphan──> [Old "ai_debug_traces" IDB — inert, harmless]
```

### Dependency Notes

- **`session.db` is the only new dependency.** It is already present in `odoo.__session_info__` on every page load of the app. No new RPC, no new Python changes.

- **The `IndexedDB` instance is module-scoped.** `db.js` constructs `new IndexedDB(DB_NAME, DB_VERSION)` at module evaluation time. Changing `DB_NAME` to a template literal using `session.db` works because `session` is imported synchronously and `session.db` is populated before any module code runs.

- **No schema migration needed.** The new per-DB IDB starts empty. Writes from the first session on the new DB name populate it. This is identical to the initial v1.3 installation experience — correct behavior.

- **All existing operations are unchanged.** `writeTrace`, `deleteTrace`, `deleteTraces`, `loadAllTraces`, `probeIDB` all use the module-level `idb` instance. They work correctly with no modification once `idb` is constructed with the right name.

---

## MVP Definition

This milestone is a single-point change with one optional follow-up.

### Launch With (v1.6)

- [x] **Scoped IDB name** — Change `DB_NAME` constant in `db.js` from `"ai_debug_traces"` to `` `ai_debug_${session.db}` ``. Add `import { session } from "@web/session"` if not already present. This is the entire feature.

### Nothing to Defer

There are no phase 2 additions for this milestone. The feature is complete with the DB name change. No UI, no migration, no new Python.

### Future Consideration (v2+)

- Old `ai_debug_traces` IDB cleanup: could add a one-time migration to `deleteDatabase()` the old shared IDB after opening the new scoped one. Low priority — orphaned IDB does not consume quota until accessed and causes no errors.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Scoped IDB name via `session.db` | HIGH — eliminates cross-DB trace pollution | LOW — one-line change | P1 — the entire milestone |
| Old IDB migration | LOW — traces are ephemeral developer data | HIGH — no reliable discriminator | P3 — do not build |
| Cross-DB trace viewer | LOW — breaks isolation guarantee | HIGH | Out of scope by design |
| DB name as trace field | LOW — IDB name is already the discriminator | LOW-MEDIUM | P3 — only if cross-DB querying becomes needed |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Sources

- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — current `DB_NAME = "ai_debug_traces"` constant and module-level `idb` construction (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/views/ai_debug_index.xml` line 14 — `session_info` JSON-inlined into page before JS runs (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/session.js` — `export const session = odoo.__session_info__ || {}` (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` line 110 — `"db": self.env.cr.dbname` in session_info (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/static/src/app/services/data_service.js` line 139 — `\`point-of-sale-${odoo.pos_config_id}-${odoo.info?.db}\`` as reference pattern (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` — `IndexedDB` constructor signature: `constructor(name, version)` — name is the IDB database name, passed directly to `indexedDB.open(this.name, ...)` (HIGH — direct inspection)

---

*Feature research for: AI Debugger v1.6 Per-DB IndexedDB Isolation*
*Researched: 2026-02-26*
