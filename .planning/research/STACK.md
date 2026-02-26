# Stack Research

**Domain:** Per-DB IndexedDB isolation for Odoo standalone OWL app
**Researched:** 2026-02-26
**Confidence:** HIGH — all findings from direct source inspection of Odoo master branch

---

## v1.6 Scope: Per-DB IndexedDB Isolation

### Summary

The change requires exactly one line of addition and one line of modification in `db.js`. No new libraries, no new imports beyond `@web/session` (already used extensively in Odoo core), no Python changes, no manifest changes, no schema migration.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `@web/session` (`session.db`) | Odoo master | Obtain Odoo DB name in frontend JS | Authoritative source — `session.db` is `self.env.cr.dbname` injected by `ir_http.session_info()` into `odoo.__session_info__` before any JS module runs. Available synchronously at module scope with zero async overhead. |
| `@web/core/utils/indexed_db` (`IndexedDB`) | Odoo master | IDB instance creation scoped to DB name | The `IndexedDB(name, version)` constructor takes `name` as its first argument. Changing the string passed here is the only change needed — the class itself requires no modification. |

### Supporting Libraries

None. No new libraries are needed. The change is a string interpolation on an existing import.

---

## The Exact Mechanism

### How `session.db` Reaches the Frontend

1. The controller at `/ai-debug` calls `request.env['ir.http'].webclient_rendering_context()`.
2. `webclient_rendering_context()` calls `self.session_info()`, which returns a dict containing `"db": self.env.cr.dbname` (source: `odoo/addons/web/models/ir_http.py`, line 110).
3. The QWeb template `ai_debug.index` serializes this as `odoo.__session_info__ = <json.dumps(session_info)/>` in an inline `<script>` tag that runs before any asset JS.
4. `@web/session` exports `export const session = odoo.__session_info__ || {}`, making `session.db` available to any JS module as a synchronous string value.

### The Required Change in db.js

Current (hardcoded):
```javascript
import { IndexedDB } from "@web/core/utils/indexed_db";
const DB_NAME = "ai_debug_traces";
const idb = new IndexedDB(DB_NAME, DB_VERSION);
```

Target (per-DB):
```javascript
import { IndexedDB } from "@web/core/utils/indexed_db";
import { session } from "@web/session";
const DB_NAME = `ai_debug_${session.db}`;
const idb = new IndexedDB(DB_NAME, DB_VERSION);
```

`session.db` is a plain string (e.g. `"aaa"`). IDB names are arbitrary strings with no character restrictions per the browser spec, so no sanitization is needed.

### Why Module Scope Is Safe

`session.db` is populated synchronously from `odoo.__session_info__` when the `@web/session` module is first evaluated. It is not a Promise and not deferred. The inline `<script>` block in `ai_debug_index.xml` guarantees `odoo.__session_info__` exists before the asset bundle's deferred scripts execute. This is the same pattern used throughout Odoo core:

- `addons/web/static/src/start.js` line 28 — `odoo.info = { db: session.db, ... }`
- `addons/web/static/src/webclient/user_menu/user_menu.js` line 21 — `this.dbName = session.db`

### How `IndexedDB` Class Handles the Name

The `IndexedDB` constructor stores `name` as `this.name` and passes it directly to `indexedDB.open(this.name, idbVersion)`. No hashing, normalization, or transformation is applied. The string `"ai_debug_aaa"` becomes the literal IDB database name visible in browser DevTools.

The `_checkVersion` method also uses `this.name` for `indexedDB.deleteDatabase(this.name)` calls on version mismatch. Because `DB_VERSION` is unchanged (still `1`), a fresh IDB database is created per Odoo DB name on first open, with no cross-DB data leakage.

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| `session.db` as IDB name suffix | `session.registry_hash` as suffix | `registry_hash` changes on every Odoo restart (keyed on `registry_sequence`), causing silent data loss for traces still in IDB. `session.db` is stable across restarts. |
| `session.db` at module scope | `odoo.info.db` at module scope | `odoo.info` is set in `startWebClient()` which runs after `whenReady()`. This app does not call `startWebClient()`. `odoo.info` is not reliably populated before `db.js` module evaluation in this standalone context. `session.db` reads directly from `odoo.__session_info__` with no timing dependency. |
| Rename the IDB in `DB_NAME` | Per-table prefix within a shared IDB | A shared IDB with prefixed table names still contaminates the same database browser-side. Complete IDB isolation per Odoo DB is architecturally cleaner and matches browser DevTools expectations. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Any async fetch to get the DB name | IDB initialization happens at `db.js` module evaluation time — before `onWillStart`, before any `await`. Async would require restructuring the module-level IDB singleton pattern. | `session.db` — synchronous |
| New npm packages (idb, localforage, etc.) | Project constraint: no new IDB libraries. `@web/core/utils/indexed_db` is the validated wrapper for this codebase. | Existing `@web/core/utils/indexed_db` |
| Migrating or deleting the old `"ai_debug_traces"` IDB | No migration strategy exists for the anonymous store because DB identity was never recorded in it. The old IDB simply becomes an unused browser artifact. Attempting to migrate would require knowing which Odoo DB the old traces belong to — unknowable after the fact. | Leave old IDB; abandon it in place. |

---

## Files Changed

| File | Change |
|------|--------|
| `ai_debug/static/src/app/db.js` | Add `import { session } from "@web/session"`. Change `const DB_NAME = "ai_debug_traces"` to `` const DB_NAME = `ai_debug_${session.db}` ``. |

No other files require changes. The exported functions (`probeIDB`, `writeTrace`, `deleteTrace`, `deleteTraces`, `loadAllTraces`, `serializeTrace`) are unchanged in signature. The `app.js` import of `db.js` is unchanged. No Python changes. No QWeb changes. No manifest changes.

---

## Stack Patterns by Variant

**If `session.db` is empty (no DB selected — not reachable in practice since the route requires `auth='user'`):**
- The resulting name would be `"ai_debug_"` — still a valid IDB name
- No defensive guard needed; the auth requirement prevents this case

**If the DB name contains spaces or special characters:**
- IDB database names are arbitrary strings per the IndexedDB spec
- No sanitization required; the `IndexedDB` class passes the name as-is to `indexedDB.open()`

---

## Version Compatibility

| Source | Verified Against | Notes |
|--------|-----------------|-------|
| `@web/core/utils/indexed_db` | Odoo master, 2026-02-26 | `IndexedDB(name, version)` constructor signature confirmed stable — first arg is the IDB database name |
| `@web/session` | Odoo master, 2026-02-26 | `session.db` field confirmed present in `session_info()` return value at `ir_http.py:110` |

---

## Sources

- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` lines 102-110 — `session_info()` dict with `"db": self.env.cr.dbname`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/session.js` — `export const session = odoo.__session_info__ || {}`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` lines 17-23 — `IndexedDB` constructor, `this.name = name`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/start.js` line 28 — precedent: `db: session.db` pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/webclient/user_menu/user_menu.js` line 21 — precedent: `this.dbName = session.db`
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — current `DB_NAME = "ai_debug_traces"` hardcoded constant
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/views/ai_debug_index.xml` line 14 — confirms `odoo.__session_info__` injection before asset scripts

---
*Stack research for: Per-DB IndexedDB isolation (v1.6)*
*Researched: 2026-02-26*
