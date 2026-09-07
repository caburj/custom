# Callback subagent debugger acceptance — 2026-09-06

## Selected-schema forwarding — 2026-09-07

`_prepare_subagent_session(tool_call, schema)` now forwards the selected delegation
schema unchanged while adding the existing parent trace link. Other debugger hooks
remain compatible with the audited core input-trust simplification.

The full **48 ai_debug tests passed**, zero failures/errors, on isolated database
`ai-debug-subagent-tests-0906a`, HTTP **22284**. Log:
`/tmp/ai-debug-schema-forward-final-tests-0907.log`. The test process exited normally.
The old fixture that invoked a callback synchronously within transport depended on
the removed post-transport acknowledgement guard. It was replaced with stale UUID,
valid submission, and duplicate submission checks asserting transport and debugger
facts occur exactly once. The first run's obsolete-fixture errors are recorded in
`/tmp/ai-debug-schema-forward-tests-0907.log`; no core guard was reinstated.

Existing delegation/reuse, helper linking, current-context correlation, atomic
retry/replay, terminal output, and standalone browser checks passed. Python syntax
and diff checks also passed. This increment changes only `models/ai_session.py`,
`tests/test_ai_debug_callback.py`, and this record under ai_debug. No commits,
Enterprise/test_ai_agent_loop edits, manual tests, or consumer restarts were made.

Verified Enterprise HEAD: `fe6eb930ae5b59d243ca62010e92b72ac5477020` plus its
uncommitted input-trust changes. Model/controller hashes stayed unchanged:

```text
ai/models/ai_session.py af3a5bb9a033e8c2e33db959d0a092ead5586c705960d0f6d7e25fcebbda3225
ai/controllers/thread.py 2c2d56effc6158df1cf8493c028e58fd0be37d8c949489d97562f2232b448f52
```

## Previous request storage API readaptation — 2026-09-07

Debugger overrides now match `_prepare_agent_request` and `_store_request`.
Obsolete `context_snapshot` and `refuse_all` forwarding is removed. Storage captures
fresh business context through the core bounded snapshot chain. A session-scoped,
transaction-local correlation override supplies only the private UUID/parent link
for that storage call; an explicitly empty override cannot inherit an old exchange.
Outside storage, own persisted correlation still preserves unchanged-context reuse.

**48 ai_debug tests passed**, zero failures/errors, on isolated database
`ai-debug-subagent-tests-0906a`, HTTP **22284**. Log:
`/tmp/ai-debug-store-api-tests-0907.log`. The process exited successfully. This is
the prior 45 tests plus combined terminal callback/synchronous output, typed
client empty-error/falsy-result handling without rerun, and failure to generate
new correlation without reusing the previous exchange. Existing image/helper,
parent-link, standalone asset/browser, and physical atomic retry tests also passed.
Python syntax and `git diff --check -- ai_debug` passed.

This increment changed only `models/ai_session.py`,
`tests/test_ai_debug_callback.py`, `tests/test_ai_debug_atomic.py`, and this record
within ai_debug. No frontend/core/test_ai_agent_loop edits, commits, manual tests,
or consumer **19969** restart were made. API adaptation is complete.

Verified Enterprise HEAD: `b0b3a01e845ab2db2d5f20866b0253080dacfd42` plus its
uncommitted simplification. Source hashes remained unchanged during testing:

```text
ai/models/ai_session.py 122d523a621900fa0e5a6889557ee90e0615c0d43b024f6004dd6945e9b5fc89
ai/controllers/thread.py b2f6dfb345f94e523cef80818b6163cdf856291fa3cfdee2ea186cca3b077d97
ai/utils/ai_utils.py 187b8b0f5578a1a040fa2c880f5060d5f0b7d58ae27b5f4affac81e69f8f8b27
```

## Previous event environment readaptation

The debugger follows the effective event environment for current business context.
Its `_get_request_context_snapshot` override calls the core/feature snapshot chain
first, then copies only this session's persisted private exchange UUID and parent
link. This lets core reuse unchanged context messages despite private debugger
metadata, without restoring old view/company values or copying a triggering
child's correlation. The omitted debugger-snapshot fallback also calls this fresh
snapshot builder. Existing atomic tests already use `_session_transaction`.

**45 tests passed**, zero failures/errors, on isolated database
`ai-debug-subagent-tests-0906a`, HTTP **22284**. Log:
`/tmp/ai-debug-event-context-final-tests-0906.log`. This is the prior 42 tests plus
three regressions for unchanged-context reuse, fresh event view/bounded values,
and delegated/helper context changes with stable exact parent links. The first
run exposed two new fixtures attempting to change immutable request intent; those
fixtures now set initial context through normal request preparation.

Only `models/ai_session.py`, `tests/test_ai_debug_callback.py`, and this evidence
record changed for this increment. No Enterprise/test_ai_agent_loop changes,
commits, frontend edits, manual tests, or consumer **19969** restart were made.

Verified Enterprise HEAD: `cf8e54ce3e86eed76ccf320d38287bcc44ab8d5d` plus its
uncommitted environment simplification. Model/controller hashes remained stable:

```text
ai/models/ai_session.py 9822214e6131b8a2e76b9601f92edb16829463441d4de9bb8d75fb9fc572cfb4
ai/controllers/thread.py 832718606a906feaf8c9ece3f8665e9d8df43513bbacecf64c79daa6554dc6e0
```

## Previous explicit child-result readaptation

Enterprise no longer stores `ai.session.exchange_result`. The debugger captures
`_finish_exchange`'s returned `child_result` in the matching transaction-local
observer context and retains its existing `exchange_result` trace/export property.
The merge observer forwards `_merge_child_result(child, result)`. No debugger ORM
read or atomic SQL snapshot references the removed field.

All **42 ai_debug tests passed again**, zero failures/errors, on isolated database
`ai-debug-subagent-tests-0906a`, HTTP port **22284**. Log:
`/tmp/ai-debug-local-child-result-tests-0906.log`. The test process exited normally.
The updated regressions verify exact returned/captured child results and separate
completed-leaf versus declined-ancestor results across atomic HTTP retry/replay.
Existing helper, image, browser, isolation, and asset tests also passed.

This increment changes only `models/ai_session.py`,
`tests/test_ai_debug_callback.py`, `tests/test_ai_debug_atomic.py`, and this record
within `ai_debug`. It makes no frontend changes, Enterprise/test_ai_agent_loop
edits, commits, manual tests, or port **19969** consumer changes.

Verified Enterprise HEAD is `dd3c24a9176839b01676c8747b124049dd73254a` plus the
uncommitted field removal. Source SHA-256 values stayed unchanged during testing:

```text
ai/models/ai_session.py 54baba95f294cd4297a4742f716bcd44c3ac4c31c61513dc9d40b3ccd6d62e13
ai/controllers/thread.py 2617f51b5b4bfa56ed49c723baa0c72322a261d01d8229469a41fcf6ae1be3ac
ai_app/models/ai_session.py fceca9c2c78515b1a28346790f6755c8fe138d3025cd2117ee05e85b9a0f4775
ai/utils/types.py 4beb72d88a88d4aa1c0081edf409b5e48d74512d433baad545d89fd6f89d250d
```

## Previous loop simplification readaptation

The debugger now follows the simplified Enterprise continuation path: helper
callbacks apply their effects and advance the parent directly, without a later
helper merge. Transaction-local nested observer contexts select the matching
session, so parent tool facts and final output stay separate from helper facts.
The same child-application observer surrounds delegated merges and direct helper
continuations. There are no new persisted fields or business checkpoints.

The tool observer forwards `previous_results` to the shared executor. Finalization
forwards `content` and `status`, and submission observation wraps the actual
`_submit_prepared_request` with the existing request-identity/phase fence.
The browser context merge fix remains in place.

Automated verification: **42 ai_debug tests passed**, zero failures/errors, on the
separate database `ai-debug-subagent-tests-0906a`, HTTP port **22284**. The test
process exited successfully. Log: `/tmp/ai-debug-simplification-tests-0906.log`.
This includes:

- Consecutive helpers in one batch: exact parent request/tool links, retained
  completed prefix, no duplicate tool completion, silent callback replay.
- Direct web-source/image application, independent parent/helper final output,
  failed helper and parent outcomes, and actual submission acknowledgement races.
- Physical HTTP atomic retry/replay for nested delegation and image effects,
  using committed Bus rows and independent database readers.
- Existing synchronous tools, observer failure isolation, standalone browser
  mount, asset boundaries, and internal-user access checks.

No frontend edits or manual tests were made for this increment. The core task
owns native verification and its port **19969** consumer; this adaptation did not
restart it. Native evidence below belongs to the preceding implementation.
Enterprise and `test_ai_agent_loop` changes remain owned by the core task;
`ai_debug` changes remain unstaged and uncommitted.

Verified Enterprise HEAD: `dd3c24a9176839b01676c8747b124049dd73254a` plus its
uncommitted simplification. Production SHA-256 values before/after verification:

```text
ai/models/ai_session.py faf3b07750991381d7cd43731655dde3d94f75bb131cb2c0756f4a0d927ca17c
ai/controllers/thread.py 6bf9a8f82339ba689f52a53e8093932f7bbac23bf25d5ed7facb755f31c811e3
ai_app/models/ai_session.py fceca9c2c78515b1a28346790f6755c8fe138d3025cd2117ee05e85b9a0f4775
```

## Previous atomic transaction readaptation

The current Enterprise working tree commits callback receipt, continuation,
ancestor delivery, and automatic confirmations in one `_lock_and_commit` block.
The existing debugger model hooks and transactional Bus rows remain compatible.
No frontend or correlation change was needed for this incremental adaptation.

A new regression reproduced an observer-isolation defect: flushing the pending
`request_result` inside a failing non-flushing savepoint removed its database
value while leaving ORM state clean. `_ai_debug_try` now constructs Odoo's default
ORM-aware savepoint before catching observer errors. Pending business writes are
flushed before the observer rollback boundary, ORM state is restored on observer
failure, and business flush conflicts propagate to native retry. No commit is
introduced.

Current automated evidence: **39 ai_debug tests passed** in the full suite,
plus **one focused business-flush retry test passed**. The two new physical HTTP
tests inject a concurrency failure after the callback has applied its effects,
verify independent database readers still see the unchanged baseline, then prove
one accepted retry and silent replay. They cover nested delivery through two
parent edges and image attachment creation together with actual Bus rows.

- Reproduced pre-fix failure: `/tmp/ai-debug-atomic-isolation-before.log`.
- Full suite: `/tmp/ai-debug-atomic-backend.log`.
- Additional retry guard: `/tmp/ai-debug-atomic-flush-retry-final.log`.
- Python syntax and `git diff --check` passed.
- No frontend changes in this increment; standalone mount and asset checks ran
  in the current full suite. Earlier Hoot evidence is recorded separately below.

Tested Enterprise base remains `6ce5e9be46a05effc66a5826b241bbc704c53bea`, with
uncommitted atomic implementation. Production source SHA-256:

```text
ai/controllers/thread.py bfc09998a19d8f50c7b53e386b10bfa02d5f56a2c84b5cd1e3acab25677e5c0c
ai/models/ai_session.py 155869a87f54c0084c02bcad953841620ede1c2c6ee927471bebe9598e544b59
```

### Current native revalidation

An Astra/high agent ran the native checks against the restarted consumer, using
fresh channel **6** (AI Debug Atomic 0906c), existing agents 7/6, and the same
consumer/IAP databases and ports. The loaded controller/model hashes match those
above. Three native user interactions exercised concurrent delegation, a worker
question, search/image helpers, refresh during the waiting state, and reuse of
the same research worker through `continue_session`.

- Sessions **6–11** are ready with no pending markers. Fresh IAP jobs **14–28**
  are done with no provider/callback error and first-attempt counters of one.
- The debugger restored the waiting root/research worker and settled image
  worker from IndexedDB after refresh, then continued capturing their updates.
- The selected new roots and descendants exported as **eight successful traces**
  to `/Users/joseph/Downloads/ai-debug-traces-2026-09-06.json`. Primary inspection
  independently verified all **six exact parent edges** against the parent's
  request iteration and tool UUID. The reused worker has a distinct exchange.
- Image attachment **355** loads at **1024×1024** (JPEG, **434174 bytes**) in the
  final native message **343**. This attempt did not reproduce the earlier
  image omission recorded in the historical section below.
- Provider-output deviations: the rendered ESA link opens an ESA error page;
  the reused worker ran another web search despite the no-new-search instruction,
  creating helper session 11. Debugger capture/reuse is verified, while those
  requested output/path details did not pass. This is not MX01–MX10 coverage.

Current chat:

http://ai-debug-subagent-live-0906a.localhost:22169/odoo/discuss?active_id=discuss.channel_6&scoped_ai_agent_id=7

The same debugger URL and restart commands at the end of this document apply.
Use the database-specific localhost hostname for the current consumer URL in
`configure`/`check`.

## Previous subagent adaptation evidence

The following records the preceding callback implementation. Its live results
and counts are historical and are not substitutes for the atomic revalidation.

Implementation is in Custom `master-ai-callback-driven-loop-subagent`, based on
`0b8bd2b4d6997fbf0f3c4db03180fb349d936f36`. Enterprise is the corresponding
subagent worktree at `6ce5e9be46a05effc66a5826b241bbc704c53bea` plus its existing
uncommitted callback changes. Existing `test_ai_agent_loop` diffs were untouched.
No Enterprise changes or commits were made by this adaptation.

## Behavior

- Observe durable request preparation, receipt, reduction, and terminal settlement
  using the current Enterprise methods and typed interaction responses.
- Link each delegated/helper exchange by parent trace, session, request UUID,
  and deterministic tool UUID. Reusing a worker creates a fresh exchange.
- Distinguish child settlement from its accepted application to the parent.
  Suppress replay/no-change facts and preserve transactional private Bus delivery.
- Show partial and out-of-order traces immediately, then attach to exact parents.
  Save every captured event through existing IndexedDB, including waiting states.
  Only events observed while the debugger is open are captured; no backfill.
- Expose bounded source links, terminal outcomes, and attachment metadata. Preserve
  existing image-preview limits and exclude unsupported binary/provider continuity.

## Automated evidence

Latest combined run: **36 ai_debug tests**, plus desktop and mobile Hoot wrappers
(**38 Odoo cases, zero failures/errors**). Each Hoot suite executed **15 tests,
80 assertions**. Includes replay, parallel/reused children, web/image application,
attachment rollback, typed resume, supersession, decline/failure, optional debugger
failure isolation, binary filtering, private Bus, and standalone asset/page checks.

- Combined log: `/tmp/ai-debug-subagent-final-combined-0906a.log`.
- Final overflow-link assertion: one test passed, log
  `/tmp/ai-debug-subagent-final-payload.log`.
- Final standalone label/page checks: two tests passed, log
  `/tmp/ai-debug-subagent-final-page.log`.
- XML/manifest parsing and `git diff --check` passed.

Reproduce against the already initialized test DB:

```bash
/Users/joseph/.venvs/master/bin/python3 \
  /Users/joseph/.wt/worktrees/odoo/odoo/master-ai-callback-driven-loop/odoo-bin \
  -d ai-debug-subagent-tests-0906a \
  --addons-path /Users/joseph/.wt/worktrees/odoo/odoo/master-ai-callback-driven-loop/addons,/Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop-subagent,/Users/joseph/.wt/worktrees/caburj/custom/master-ai-callback-driven-loop-subagent \
  -u web,ai_debug --stop-after-init --test-enable \
  --test-tags '/ai_debug,/web:WebSuite.test_unit_desktop[@ai_debug],/web:MobileWebSuite.test_unit_mobile[@ai_debug]' \
  --http-port=22179 --gevent-port=22182 --workers=0 --max-cron-threads=0
```

The legacy `tests/harness/run_callback_checkpoint.py` was not used: it still
assumes the former callback/IAP contract. The native evidence below uses the
current launcher and real providers.

## Native and persisted evidence

Live database `ai-debug-subagent-live-0906a`, channel 3, Coordinator agent 7,
Worker agent 6, admin actor 2. Three user interactions in one fresh chat:

1. Start two workers in one batch. A asks a structured ESA/NASA question and then
   searches the chosen organization's news; B independently generates a green mug.
2. Refresh the debugger while A is waiting and B has completed; choose ESA in the
   native question UI. Saved roots/children restore, then receive later updates.
3. Continue the existing research worker, requesting a one-sentence summary with
   no new searches. Actual emitted tool was `continue_session(session_id=2)`.

All five durable sessions are ready with no pending child markers. **13 IAP jobs
are done**. The initial search/image scenario used 10 jobs with zero provider or
callback errors. Models were Gemini 3.5 Flash Lite and Gemini 3.1 Flash Image.

IndexedDB contains **seven successful traces**: two root exchanges, two distinct
exchanges for the reused Worker A, Worker B, and separate image/search helpers.
Exact parent request/tool identity differs between the reused worker exchanges.
The initial four traces survived refresh while the root was active; search and
final events then extended the hydrated records. No debugger browser errors.
This is focused debugger acceptance, not a claim that MX01–MX10 all ran.

The source link is retained in the search helper's normalized result. Image
attachment **353** exists (JPEG, **385965 bytes**) and is accessible to admin.
Worker B's IndexedDB outcome retains attachment ID 353 and
`/web/image/ir.attachment/353/raw`; its oversized preview is excluded as intended.

**Enterprise presentation limitation observed:** the image reached Worker B's
exchange result and the root's tool-result history, but the Coordinator returned
text only. Final message 337 has no attachment or image markup. Enterprise
`_post_ai_response` attaches only inline media in the final response. The debugger
preserves the generated attachment reference; this adaptation does not alter
Enterprise's final-response behavior. The ESA source link renders in native chat.

## Running stack and handoff

The dedicated tmux sessions remain running:
`ai-debug-subagent-consumer`, `ai-debug-subagent-iap-http`, and
`ai-debug-subagent-iap-evented`. The databases are already initialized and linked.
`x ai-callback check` passed HTTP/WebSocket, raw JSON2 callback, identities,
endpoint/credit configuration, and broker readiness.

Open the captured debugger in the same browser origin used for acceptance:

http://ai-debug-subagent-live-0906a.localhost:22169/ai-debug?db=ai-debug-subagent-live-0906a

Native chat:

http://ai-debug-subagent-live-0906a.localhost:22169/odoo/discuss?active_id=discuss.channel_3&scoped_ai_agent_id=7

To restart after stopping these dedicated processes, run each server command in
its own terminal. Both IAP processes need the configured provider-key environment.

```bash
/Users/joseph/clones/caburj/x/x ai-callback consumer \
  --worktree /Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop-subagent \
  --db ai-debug-subagent-live-0906a --consumer-port 22169

/Users/joseph/clones/caburj/x/x ai-callback iap-http \
  --worktree /Users/joseph/.wt/worktrees/odoo/iap-apps/saas-19.4-odoo-ai-async-no-https-cwg-juc \
  --db ai-debug-subagent-iap-0906a --iap-port 22170

/Users/joseph/clones/caburj/x/x ai-callback configure \
  --consumer-worktree /Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop-subagent \
  --iap-worktree /Users/joseph/.wt/worktrees/odoo/iap-apps/saas-19.4-odoo-ai-async-no-https-cwg-juc \
  --consumer-db ai-debug-subagent-live-0906a --iap-db ai-debug-subagent-iap-0906a \
  --consumer-url http://ai-debug-subagent-live-0906a.localhost:22169 --iap-url http://127.0.0.1:22170 \
  --iap-gevent-port 22173

/Users/joseph/clones/caburj/x/x ai-callback iap-evented \
  --worktree /Users/joseph/.wt/worktrees/odoo/iap-apps/saas-19.4-odoo-ai-async-no-https-cwg-juc \
  --db ai-debug-subagent-iap-0906a --iap-gevent-port 22173

/Users/joseph/clones/caburj/x/x ai-callback check \
  --consumer-worktree /Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop-subagent \
  --iap-worktree /Users/joseph/.wt/worktrees/odoo/iap-apps/saas-19.4-odoo-ai-async-no-https-cwg-juc \
  --consumer-db ai-debug-subagent-live-0906a --iap-db ai-debug-subagent-iap-0906a \
  --consumer-url http://ai-debug-subagent-live-0906a.localhost:22169 --iap-url http://127.0.0.1:22170 \
  --iap-gevent-url http://127.0.0.1:22173
```
