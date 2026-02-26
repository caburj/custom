# Project Research Summary

**Project:** AI Debugger v1.6 — Per-DB IndexedDB Isolation
**Domain:** Odoo standalone OWL app — frontend storage scoping for a developer tool
**Researched:** 2026-02-26
**Confidence:** HIGH

## Executive Summary

AI Debugger v1.6 is a surgical one-line change to a fully-shipped developer tool. The existing `db.js` uses a hardcoded `const DB_NAME = "ai_debug_traces"`, which causes traces from different Odoo databases to collide in a single browser-side IndexedDB instance. The fix is to scope the IDB name by the active Odoo database name using `session.db`, the standard synchronous frontend identifier Odoo injects into every authenticated page via `odoo.__session_info__`. The change is exactly: add `import { session } from "@web/session"` and change `DB_NAME` to `` `ai_debug_${session.db}` ``. No Python changes, no OWL component changes, no schema migration, no manifest changes.

The recommended approach is direct and unambiguous: `session.db` is available synchronously at module evaluation time — before any async path, before `onWillStart`, before the first render. This is the same pattern used by `addons/web/static/src/start.js` and `user_menu.js` throughout Odoo core. The POS module uses the identical pattern for its own per-DB IDB scoping (`point-of-sale-${odoo.pos_config_id}-${odoo.info?.db}`). No alternative approach is viable — async DB name resolution would break the existing serial `onWillStart` ordering without any benefit.

The key risks are: (1) accidentally bumping `DB_VERSION`, which triggers silent full data deletion via the Odoo `IndexedDB` utility's all-or-nothing version check; (2) failing to migrate the one-time v1.5 orphan `ai_debug_traces` IDB, leaving developers with an empty trace list after upgrade; and (3) forgetting `idb._tables.add(STORE)` if the construction site is refactored, which silently prevents the `traces` object store from being created. All three are easily avoided by keeping the change minimal and targeted.

## Key Findings

### Recommended Stack

The change requires exactly two touched lines in one file. `@web/session` (already used extensively in Odoo core) provides `session.db` synchronously via `odoo.__session_info__`. The `@web/core/utils/indexed_db` `IndexedDB(name, version)` constructor accepts the name as an arbitrary string and passes it directly to `indexedDB.open()` — no normalization, no restrictions. Odoo DB names follow PostgreSQL identifier rules (alphanumeric + underscore), so no sanitization is needed.

**Core technologies:**
- `@web/session` (`session.db`): Obtain the Odoo DB name in JS — synchronous, zero async overhead, already present in the page before any JS bundle executes
- `@web/core/utils/indexed_db` (`IndexedDB`): IDB instance creation — constructor takes `name` as first arg; changing the string is the only change needed
- Template literal `` `ai_debug_${session.db}` ``: IDB name format — human-readable in DevTools, consistent with the `ai_debug` module prefix, safe for all valid Odoo DB names

**What NOT to use:**
- Any async fetch or RPC to resolve the DB name — IDB construction is synchronous at module load; async resolution breaks `onWillStart` ordering
- `session.registry_hash` as a suffix — changes on every Odoo restart, causing silent data loss
- `odoo.info.db` — only set after `startWebClient()`, which this standalone app does not call

### Expected Features

The feature surface for v1.6 is a single point change with one recommended secondary step.

**Must have (table stakes):**
- IDB name scoped to active Odoo DB — eliminates cross-DB trace pollution for developers running multiple Odoo instances in the same browser
- No UI changes — isolation is transparent by design; the sidebar, detail panels, and all event handlers are unchanged

**Should have (strongly recommended):**
- One-time migration from old `ai_debug_traces` IDB — approximately 15 lines in `onWillStart` using `indexedDB.databases()` to detect the old shared instance, copy records into the new per-DB store, and delete the old one; prevents a confusing empty-trace-list regression on upgrade

**Defer (v2+):**
- Auto-cleanup of orphaned `ai_debug_<droppedDb>` instances from dropped databases — low priority; document console command instead
- DB name stored as a field on each trace record — not needed; the IDB name is already the discriminator

**Anti-features (do not build):**
- Cross-DB trace viewer — breaks the isolation guarantee that is the entire purpose of this milestone
- Migration of old shared IDB traces without a DB discriminator field — no reliable way to know which Odoo DB old traces came from

### Architecture Approach

The AI Debugger is a standalone OWL app with a module-level IDB singleton pattern. `db.js` constructs `new IndexedDB(DB_NAME, DB_VERSION)` at module evaluation time, before `AiDebugApp` is mounted. All IDB operations (`writeTrace`, `deleteTrace`, `deleteTraces`, `loadAllTraces`, `probeIDB`) use this module-level `idb` instance. Changing `DB_NAME` to a template literal using `session.db` is safe precisely because `session` is a synchronous module-level import — the value is populated before any module code runs. The `onWillStart` serial chain (`probeIDB` -> `loadAllTraces` -> hydrate -> promote orphans) is unaffected. No new components, no new async paths.

**Key architectural invariants for v1.6:**
1. `db.js` module-level singleton — `idb` is constructed once at module load; `DB_NAME` must be a synchronous value at that point
2. `idb._tables.add(STORE)` — must remain the next line after `new IndexedDB(...)` construction; without it, `execute()` calls cannot create the `traces` object store
3. `DB_VERSION = 1` — must not be incremented; the schema (one `traces` object store) is unchanged; bumping triggers silent full deletion
4. `onWillStart` serial order — optional migration logic must run in `onWillStart` before `loadAllTraces` to avoid hydrating stale data

### Critical Pitfalls

1. **Accidental `DB_VERSION` bump** — The Odoo `IndexedDB` utility's `_checkVersion()` is all-or-nothing: any version mismatch triggers `deleteDatabase()` with no warning. Do not increment `DB_VERSION` in v1.6; the schema is unchanged. Add a locking comment explaining the naming format.

2. **`idb._tables.add(STORE)` dropped during refactoring** — The `IndexedDB` utility only auto-registers tables for `read()`/`write()`/`getAllKeys()` calls; `db.js` uses `execute()` directly. If the construction site moves, this line must travel with it. Wrap both in a `createIDB(dbName)` factory function as insurance.

3. **Module-level `session.db` resolving to `undefined`** — Produces `DB_NAME = "ai_debug_undefined"`, co-mingling all such sessions into a garbage store. The `/ai-debug` route uses `auth='user'`, so this is prevented in production, but add `|| "unknown"` as a fallback guard and confirm DevTools shows `ai_debug_<actualDbName>` before shipping.

4. **Skipping the v1.5 -> v1.6 IDB migration** — Developers who ran v1.5 will see an empty trace list after upgrading because the new per-DB IDB starts fresh. The migration is approximately 15 lines and should be included in v1.6.

5. **Async DB name resolution breaking `onWillStart`** — `session.db` is synchronous; there is no reason to reach for an async alternative. Document this in `db.js` to prevent future refactors from introducing async.

## Implications for Roadmap

This milestone is so narrowly scoped that a single implementation phase covers everything. There are no multi-phase dependencies, no blocking decisions, and no architecture unknowns.

### Phase 1: Per-DB IDB Name Scoping

**Rationale:** The entire feature is a two-line change to `db.js`. Everything else in this milestone (migration, comments, verification) is in service of that change. No phase decomposition is warranted.

**Delivers:** Per-DB IDB isolation — traces stored in `ai_debug_<dbname>` instead of the shared `ai_debug_traces`; all IDB operations automatically scoped to the current Odoo DB with no UI change visible to the developer.

**Addresses:** "IDB name scoped to current DB" (P1 table stakes from FEATURES.md); one-time migration from `ai_debug_traces` (P2 from FEATURES.md).

**Avoids:** All five pitfalls documented in PITFALLS.md.

**Implementation steps in order:**
1. Add `import { session } from "@web/session"` to `db.js`
2. Change `const DB_NAME = "ai_debug_traces"` to `` const DB_NAME = `ai_debug_${session.db || "unknown"}` ``
3. Keep `DB_VERSION = 1` unchanged — add comment locking the version and name format
4. Optionally wrap `new IndexedDB(...)` + `idb._tables.add(STORE)` in a `createIDB(dbName)` factory function to make the invariant unbreakable
5. Add one-time migration in `onWillStart` (before `loadAllTraces`) using `indexedDB.databases()` with browser compatibility guard

**Verification checklist:**
- DevTools Application > Storage > IndexedDB shows `ai_debug_<actualDbName>`, not `ai_debug_traces` or `ai_debug_undefined`
- Two browser tabs each logged into a different Odoo DB show separate IDB instances with separate trace records
- Fresh install creates `traces` object store (not just `__DBVersion__`) — verified in DevTools
- Git diff shows `DB_VERSION` still set to `1`
- Ephemeral mode still shows amber badge in private browsing — `probeIDB()` correctly detects IDB unavailability against the new name

### Phase Ordering Rationale

- There is one phase because there is one dependency chain: `session.db` synchronously available at module load -> `DB_NAME` template literal -> all IDB operations scoped correctly
- Migration runs in the same phase because it belongs to `onWillStart`, which already owns IDB initialization
- No UI changes means no second phase for frontend components

### Research Flags

Phases needing deeper research during planning: None. The full implementation is specified to the line level in STACK.md and PITFALLS.md. No unknowns remain.

Phases with standard patterns (skip research-phase):
- **Phase 1:** Pattern is documented, well-precedented in Odoo codebase (POS reference, `start.js`, `user_menu.js`), and verified against master branch source. Proceed directly to implementation.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All findings from direct source inspection of Odoo master and the custom repo; `session.db` availability and `IndexedDB` constructor signature confirmed at the line level |
| Features | HIGH | Feature surface is minimal and fully specified; anti-features clearly documented with reasoning; POS reference implementation confirmed |
| Architecture | HIGH | `db.js` module-level singleton pattern read directly; `onWillStart` serial chain verified in `app.js`; `_tables.add` requirement verified against `indexed_db.js` source |
| Pitfalls | HIGH | All pitfalls derived from direct codebase inspection; recovery strategies verified against actual API behavior; `indexedDB.databases()` compatibility matrix from MDN |

**Overall confidence:** HIGH

### Gaps to Address

- **`indexedDB.databases()` browser compatibility for migration:** Chrome 71+, Firefox 126+, Safari 15+. The migration code must guard with `typeof indexedDB.databases === "function"`. Older browsers silently skip migration — acceptable for a developer tool targeting modern browsers. Document the assumption in code.

- **Old `ai_debug_traces` migration for mixed-DB traces:** If a developer had traces from multiple Odoo DBs mixed in the old shared IDB (the original problem), migration cannot disambiguate provenance. The recommendation is to migrate all records into the current DB's new IDB — acceptable for a developer tool where traces are ephemeral and the developer can re-run sessions.

## Sources

### Primary (HIGH confidence — direct source inspection)

- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — current `DB_NAME` constant, module-level singleton, `_tables.add` pattern, `DB_VERSION = 1`
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — `onWillStart` serial ordering
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/views/ai_debug_index.xml` line 14 — `odoo.__session_info__` injection before asset scripts
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/session.js` — `export const session = odoo.__session_info__ || {}`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` lines 102-110 — `session_info()` dict, `"db": self.env.cr.dbname`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` — `IndexedDB(name, version)` constructor, `_checkVersion` all-or-nothing delete behavior, `_tables` auto-registration rules
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/start.js` line 28 — `db: session.db` precedent
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/webclient/user_menu/user_menu.js` line 21 — `this.dbName = session.db` precedent
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/static/src/app/services/data_service.js` line 139 — POS per-DB IDB reference pattern

### Secondary (MEDIUM confidence)

- MDN Web Docs on `indexedDB.databases()` — browser compatibility matrix (Chrome 71+, Firefox 126+, Safari 15+); used to bound migration guard requirement

---
*Research completed: 2026-02-26*
*Ready for roadmap: yes*
