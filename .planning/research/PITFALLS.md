# Pitfalls Research

**Domain:** Adding per-DB IndexedDB scoping to an existing single-database OWL app (ai_debug v1.6)
**Researched:** 2026-02-26
**Confidence:** HIGH (grounded in direct codebase inspection of ai_debug db.js, app.js, Odoo IndexedDB utility, and session_info source)

This document supersedes the v1.5 PITFALLS.md for v1.6 planning. V1.5 pitfalls are resolved and confirmed. This document focuses exclusively on the new surface area: scoping the `ai_debug_traces` IndexedDB instance by Odoo database name so developers on a multi-DB Odoo instance see isolated trace stores.

---

## Critical Pitfalls

### Pitfall 1: Module-Level IDB Singleton Created Before `session.db` Is Available

**What goes wrong:**
`db.js` creates the IDB instance at module scope:

```js
const DB_NAME = "ai_debug_traces";
const DB_VERSION = 1;
const idb = new IndexedDB(DB_NAME, DB_VERSION);
idb._tables.add(STORE);
```

`new IndexedDB(name, version)` immediately calls `this.mutex.exec(() => this._checkVersion(version))` in its constructor, which queues an IDB open. This happens at module parse/evaluate time — before `onWillStart`, before `AiDebugApp` is mounted, and before `session.db` is readable via any async path.

If the new design derives `DB_NAME` from `session.db`, that value must be available at the point `new IndexedDB(...)` is called. The question is: is `session.db` synchronously available at module evaluation time?

The Odoo `session` object (`@web/session`) is populated from `odoo.__session_info__`, which the server injects into the HTML before the bundle executes. The source is `session.js`:

```js
export const session = odoo.__session_info__ || {};
```

This is a synchronous assignment. `session.db` IS available at module evaluation time for any page served with `auth='user'`. The `/ai-debug` route uses `auth='user'`, so `session.db` will be present. The safe, correct approach is:

```js
import { session } from "@web/session";
const DB_NAME = `ai_debug_${session.db}`;
```

The risk is if `session.db` is `undefined` (unauthenticated context, test harness, or future route change). This produces `DB_NAME = "ai_debug_undefined"` — a valid IDB name that silently co-mingles all such sessions into one garbage store.

**Why it happens:**
Developers either (a) treat `session.db` as async and unnecessarily defer construction to `onWillStart` with a dynamic DB name — introducing a lifecycle race — or (b) read it synchronously but forget the `undefined` fallback risk.

**How to avoid:**
Read `session.db` synchronously in `db.js` at module evaluation time. Add a `|| "unknown"` fallback as insurance against unauthenticated contexts. Do not introduce an async DB name resolution path — it unnecessarily complicates the existing serial `onWillStart` ordering.

**Warning signs:**
- DevTools Application > Storage > IndexedDB shows `ai_debug_undefined` instead of `ai_debug_<dbname>`
- After switching Odoo databases in the same browser, traces from DB A appear in DB B's app
- Console shows `indexedDB.open("ai_debug_undefined", ...)` in network panel

**Phase to address:** The single implementation phase. This is the core change — get the name right before writing any other code.

---

### Pitfall 2: Orphaned Old IDB Databases Accumulate Silently on Developer Machines

**What goes wrong:**
Before v1.6, all developers on any Odoo DB share one IDB instance named `ai_debug_traces`. After v1.6 ships, each DB gets its own instance: `ai_debug_aaa`, `ai_debug_bbb`, etc. The old `ai_debug_traces` instance is never deleted — it just sits in the browser, consuming storage, forever.

For any developer who ran v1.5 and upgrades to v1.6: their browser retains `ai_debug_traces` with all their old traces. The new per-DB instances start empty. The old traces are effectively invisible to the new app without a migration step.

The broader ongoing problem: if a developer creates and drops many Odoo databases (common in development), each spawns an orphaned IDB instance named `ai_debug_<droppedDb>`. `indexedDB.databases()` (Chrome 71+, Firefox 126+, Safari 15+) can enumerate them, but the app has no automatic cleanup path.

**Why it happens:**
IDB instances are not tied to application lifetime — they persist until explicitly deleted or the browser clears site data. Renaming the logical database by changing the IDB name string leaves the old instance untouched. There is no IDB-side event for "application changed its store name."

**How to avoid:**
For the one-time v1.5 -> v1.6 migration: add a startup step in `onWillStart` that checks for the old `ai_debug_traces` IDB. If it exists and the new per-DB instance is empty, copy records from the old store into the new one then delete the old DB. This is ~15 lines and significantly improves the upgrade experience.

Approach using `indexedDB.databases()`:
1. Call `indexedDB.databases()` if available (check with `typeof indexedDB.databases === 'function'`)
2. Look for an entry named `"ai_debug_traces"` in the returned list
3. If found and new per-DB store is empty: open old DB, read all records, write into new DB, then delete old DB
4. Log success to console

For ongoing orphan accumulation: document in `db.js` that `indexedDB.deleteDatabase("ai_debug_<dbname>")` can be run from the browser console. Do not build automatic cleanup — it risks deleting traces from a DB the developer temporarily cannot connect to.

**Warning signs:**
- Developer switches to v1.6 and sees empty trace list — old traces still visible in DevTools Application > Storage > IndexedDB under `ai_debug_traces`
- DevTools shows multiple `ai_debug_*` databases accumulating as new Odoo DBs are created and dropped
- Storage quota warnings in environments with many test databases

**Phase to address:** The single implementation phase, as a secondary concern after the core name change. The migration logic is optional but strongly recommended.

---

### Pitfall 3: DB Version Collision Silently Wipes All Stored Traces

**What goes wrong:**
The Odoo `IndexedDB` utility uses a two-level versioning scheme: a custom `__DBVersion__` object store that holds an application-managed version number, and the native IDB `version` integer. The `_checkVersion()` method in the utility is all-or-nothing: if the stored version does not match the expected version, it calls `_deleteDatabase()` and recreates the database. There is no migration path, no warning to the user, no backup.

For ai_debug, this is dangerous because IDB is the sole persistence layer. An accidental `DB_VERSION` bump during v1.6 development (e.g., thinking "I changed the name, maybe I should bump the version") would delete all existing traces on every developer machine on their next page load. No error is shown — the app starts fresh.

This also applies to future versions: once the naming convention is locked at `ai_debug_<dbname>`, changing the name format is equivalent to creating a brand-new database (old data is simply orphaned, not deleted — but also not accessible).

**Why it happens:**
Developers conflate "I changed how the DB is identified" (the name) with "I changed the DB schema" (which requires a version bump). The schema — one object store named `traces` with trace_id as the key — is unchanged by v1.6. Only the name changes. No version bump is needed or correct.

**How to avoid:**
Do not increment `DB_VERSION` in v1.6. The value stays at `1`. Add a comment on the `DB_VERSION` constant explaining when it should be bumped: "Increment only when the `traces` object store structure changes (added/removed object stores). Adding or removing fields within the JSON blob does NOT require a version bump — as demonstrated by v1.5 token fields."

Lock the naming convention in a code comment: "DB name format is ai_debug_<odoo-db-name>. This format is locked after v1.6 — changing it is equivalent to abandoning all users' stored traces."

**Warning signs:**
- `DB_VERSION` constant is `2` or higher in the v1.6 diff
- The diff includes a version bump without any object store creation or deletion
- Developer machines start with empty trace lists after upgrading

**Phase to address:** The single implementation phase. Lock the version number and name format in the same commit.

---

### Pitfall 4: `idb._tables.add(STORE)` Must Be Preserved After Any Refactoring

**What goes wrong:**
The current `db.js` has this immediately after creating the IDB instance:

```js
const idb = new IndexedDB(DB_NAME, DB_VERSION);
idb._tables.add(STORE);
```

The comment in `db.js` explains why: `_tables` is what `_execute()` uses in `onupgradeneeded` to know which object stores to create. Without this call, `loadAllTraces()` (which uses `idb.execute()` directly rather than `idb.read()`/`idb.write()`) will not trigger `traces` object store creation on a fresh IDB instance. The store simply will not exist.

The consequences: `loadAllTraces()` hits the `!db.objectStoreNames.contains(STORE)` guard and returns `[]`. `writeTrace()` also hits the same guard and silently no-ops. The app appears to work but traces are never persisted. No error is thrown.

If v1.6 refactors the `idb` construction into a factory function or moves the construction site, this line must travel with it.

**Why it happens:**
This is a quirk of the Odoo `IndexedDB` utility: only `read()`, `write()`, and `getAllKeys()` auto-register tables via `this._tables.add(table)`. Direct `execute()` calls do not. The `db.js` author correctly worked around this — but the invariant is invisible from call sites and easy to lose during refactoring.

**How to avoid:**
If the constructor call is moved, keep `idb._tables.add(STORE)` as the next line with the comment intact. Better: wrap both in a factory function that cannot be called without the table registration:

```js
function createIDB(dbName) {
    const db = new IndexedDB(dbName, DB_VERSION);
    // Required: direct execute() calls don't auto-register tables.
    // Without this, the traces store won't exist on a fresh DB.
    db._tables.add(STORE);
    return db;
}
```

**Warning signs:**
- Fresh installation shows empty trace list that never populates even after running an AI session
- DevTools Application > IndexedDB shows the database exists but contains only `__DBVersion__` object store, no `traces` store
- Traces appear in the reactive store in memory but disappear on page refresh

**Phase to address:** The single implementation phase — if the construction site is touched at all, verify `_tables.add` is preserved.

---

### Pitfall 5: Async DB Name Resolution Breaks the `onWillStart` Serial Ordering

**What goes wrong:**
The existing `onWillStart` in `app.js` has a carefully maintained serial chain:

```
probeIDB() -> set ephemeralMode -> loadAllTraces() -> hydrateTrace() for each record -> promote orphans
```

This chain works because everything runs in serial within the `onWillStart` async function, and OWL blocks the first render until `onWillStart` resolves. Bus subscriptions are set up in `onMounted`, which fires after the first render, so no bus events are delivered during hydration.

If someone introduces an async DB name resolution step before `probeIDB()` — for example, fetching the DB name from the server via `orm.call()` instead of reading `session.db` — and that async call takes more than a few hundred milliseconds, the startup latency becomes user-visible. Worse, if the async resolution is incorrectly placed outside `onWillStart` (e.g., in `setup()`), the IDB instance may not be ready when `onWillStart` tries to use it.

This pitfall is unlikely if `session.db` is used (it's synchronous), but likely if a developer does not know `session.db` is synchronous and reaches for an async alternative.

**Why it happens:**
Developers unfamiliar with how Odoo injects `__session_info__` assume `session.db` requires an async lookup (like `lazy_session` or an ORM call). `session.db` does not — it is available synchronously before the bundle even executes.

**How to avoid:**
Use `import { session } from "@web/session"` and read `session.db` at module evaluation time in `db.js`. No async resolution needed. The serial ordering in `onWillStart` is preserved without changes. Document this decision in `db.js`:

```js
// session.db is synchronously available (populated from odoo.__session_info__
// before the bundle runs). No async lookup needed.
import { session } from "@web/session";
const DB_NAME = `ai_debug_${session.db || "unknown"}`;
```

**Warning signs:**
- `onWillStart` duration increases by hundreds of milliseconds
- DB name resolution uses `await orm.call(...)` or `await rpc(...)`
- IDB construction happens inside a Promise chain rather than synchronously at module level

**Phase to address:** The single implementation phase — avoid by choosing the synchronous `session.db` path from the start.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip one-time v1.5->v1.6 IDB migration | Simpler v1.6 implementation | Developers see empty trace list after upgrade; old `ai_debug_traces` accumulates forever | Never — migration is ~15 lines and prevents a confusing UX regression |
| Inline `ai_debug_` prefix as a string literal | Fewer constants | Name format locked in a string literal; harder to grep or enforce consistency | Never — define `const DB_PREFIX = "ai_debug_"` as a named constant |
| Use `session.db` without a fallback guard | Cleaner code | `DB_NAME = "ai_debug_undefined"` if page somehow loaded without session | Acceptable for v1.6 (auth='user' guarantees session); add `|| "unknown"` as insurance |
| Bump `DB_VERSION` when only the name changes | "Feels right" during a DB change | Full silent data deletion on every user machine on next load | Never |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `@web/session` import | Treating `session.db` as async or unavailable at module level | `session` is a synchronous export from `odoo.__session_info__`; read `session.db` directly at module evaluation time |
| Odoo `IndexedDB` utility `_checkVersion` | Assuming version mismatch triggers migration | It triggers full deletion with no warning; never bump `DB_VERSION` without an actual object store schema change |
| `indexedDB.databases()` for orphan detection | Assuming universal availability | Chrome 71+, Firefox 126+, Safari 15+ only; always check `typeof indexedDB.databases === "function"` before calling |
| `idb.execute()` vs `idb.read()`/`idb.write()` | Using `execute()` for custom queries without registering the table | Either use high-level `read`/`write`/`getAllKeys` (auto-register), or call `idb._tables.add(STORE)` before the first `execute()` |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Migration reads entire old DB into memory at once | OOM on machines with thousands of old traces | Batch-read in chunks of 100; acceptable for ai_debug typical usage | At ~10,000 large traces (~100MB) — unlikely for a developer tool |
| Running orphan DB detection on every page load | Visible startup latency | Run migration check once, mark complete with a flag in the new DB | Negligible for ai_debug; `indexedDB.databases()` is fast |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Not sanitizing `session.db` before using in IDB name | Malicious DB names could theoretically create confusing IDB entries | Odoo DB names follow PostgreSQL identifier rules (alphanumeric + underscore, max 63 chars); no sanitization needed for Odoo-issued names; document the assumption |
| Assuming IDB data is private to the current OS user | All browser profiles on the same machine share the IDB namespace for the same origin | ai_debug is a developer tool; cross-user IDB access on shared machines is a known limitation, not a bug to fix in v1.6 |

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No migration from old `ai_debug_traces` | Developer thinks traces were lost after upgrade | Migrate old traces into new per-DB store in `onWillStart`; log "Migrated N traces from ai_debug_traces" to console |
| Adding a visible "Current DB: aaa" label to the UI | Unnecessary UI noise — developer always knows which DB they're on | No UI change needed; per-DB scoping is transparent by design (confirmed in PROJECT.md milestone goal) |
| Deleting orphan databases automatically at startup | Could delete traces from a DB the developer wants but is temporarily unable to reach | Only migrate; never auto-delete DBs other than the explicit old-name one-time migration |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **DB name:** DevTools Application > Storage > IndexedDB shows `ai_debug_<actualDbName>`, not `ai_debug_traces` or `ai_debug_undefined`
- [ ] **Isolation:** Open /ai-debug in two browser tabs each logged into a different Odoo DB; confirm each tab's DevTools shows a separate IDB instance with separate trace records
- [ ] **_tables.add preserved:** Clear all browser storage, load fresh, generate one AI trace, then confirm `traces` object store exists in DevTools (not just `__DBVersion__`)
- [ ] **DB_VERSION unchanged:** Final git diff shows `DB_VERSION` still set to `1`
- [ ] **Ephemeral mode still works:** Private browsing mode still shows amber ephemeral badge — `probeIDB()` still correctly detects IDB unavailability
- [ ] **Old DB orphan handled:** Manually create `ai_debug_traces` with a record in DevTools before testing v1.6; confirm migration or at minimum the new per-DB instance is unaffected
- [ ] **session.db fallback:** Confirm `DB_NAME` does not include the string "undefined" on any code path

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| DB_NAME resolves to `ai_debug_undefined` | MEDIUM | Fix `session.db` read and redeploy; run `indexedDB.deleteDatabase("ai_debug_undefined")` in browser console to clean up; traces from that session are lost |
| `_tables.add` forgotten — traces not persisted | MEDIUM | Fix bug and redeploy; in-memory traces visible until refresh are lost on reload; no recovery |
| DB_VERSION bumped accidentally — all traces deleted | HIGH | Roll back the version bump and redeploy; lost traces must be re-generated; no recovery |
| v1.5 orphan `ai_debug_traces` not migrated | LOW | Developer runs `indexedDB.deleteDatabase("ai_debug_traces")` in console once they've accepted the loss; or implement migration retroactively |
| Per-DB IDB instance accumulation from dropped DBs | LOW | Developer runs `indexedDB.databases().then(dbs => ...)` in console to enumerate and delete stale `ai_debug_*` instances |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Module-level singleton with undefined DB name | Implementation: name change | DevTools shows `ai_debug_<dbname>`, not `ai_debug_undefined` or `ai_debug_traces` |
| Orphaned old `ai_debug_traces` | Implementation: migration | After v1.5->v1.6 upgrade, old traces appear in new per-DB instance; old DB deleted from DevTools |
| DB_VERSION bumped accidentally | Implementation: version lock | Final diff shows `DB_VERSION = 1` unchanged |
| `_tables.add` dropped during refactor | Implementation: invariant preservation | Fresh install creates `traces` object store on first load (check DevTools) |
| Async DB name resolution breaking onWillStart | Implementation: design choice | Use synchronous `session.db` — no async path introduced, startup latency unchanged |

## Sources

- Direct codebase inspection: `ai_debug/static/src/app/db.js` — module-level singleton pattern, `_tables.add` requirement, `DB_VERSION = 1` history
- Direct codebase inspection: `ai_debug/static/src/app/app.js` — `onWillStart` serial ordering: `probeIDB` -> `loadAllTraces` -> hydrate -> promote orphans
- Direct codebase inspection: `odoo/addons/web/static/src/core/utils/indexed_db.js` — `_checkVersion` full-delete behavior; `_execute` `onupgradeneeded` creates stores from `_tables`; only `read`/`write`/`getAllKeys` auto-register tables
- Direct codebase inspection: `odoo/addons/web/static/src/session.js` — `export const session = odoo.__session_info__ || {}` (synchronous, no async)
- Direct codebase inspection: `odoo/addons/web/models/ir_http.py` — `session_info` dict includes `"db": self.env.cr.dbname`; served via `webclient_rendering_context()` used by the `/ai-debug` controller
- Direct codebase inspection: `odoo/addons/web/static/src/webclient/user_menu/user_menu.js` — `this.dbName = session.db` (confirms `session.db` is the standard field name in Odoo JS)
- Direct codebase inspection: `odoo/addons/point_of_sale/static/src/app/services/data_service.js` — POS reference pattern for per-DB IDB scoping using `odoo.info?.db`
- Known tech debt from PROJECT.md: `_applyImport does not run orphan-promotion pass`, `CSS depth tint caps at 4 levels` — unrelated to v1.6, not addressed here
- MDN Web Docs on `indexedDB.databases()`: available in Chrome 71+, Firefox 126+, Safari 15+

---
*Pitfalls research for: per-DB IndexedDB isolation (ai_debug v1.6)*
*Researched: 2026-02-26*
