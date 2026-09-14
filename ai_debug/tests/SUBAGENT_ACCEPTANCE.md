## Combined thinking and callback loop — 2026-09-14

The target is the accumulated Enterprise feature, not the thinking commit alone:
`master-ai-callback-driven-loop-ref-thinking` at clean
`edd05e81114b64cbb9820361a02b7457cc3fd17e`, with thinking commit
`01bb371bb71` directly beneath the callback-loop commit. Compared the resulting
source to Enterprise `master-ai-callback-driven-loop-ref` (`f96657641dc`) and
inspected the lifecycle against the Custom parent's existing adaptation.

Custom `master-ai-callback-driven-loop-ref-thinking` already existed clean at
`48784cd968339d28fc2324a0479bc236186dcea9`; `wt parent` confirmed
`master-ai-callback-driven-loop-ref`. Reused that child. Its Custom parent remains
clean at the same commit. No branches were recreated or reparented.

The combined loop now emits `tool_status` before execution and intermediary tool
summaries, rather than update_thinking client commands. The debugger observes that
boundary, preserving exact request/tool identity. A separate tool_call_progress
event carries plain status/summary text without completing the tool or replacing
its business result. Both callback and synchronous paths are covered. Tool detail
shows escaped text; capture storage, export, hydration, and copied details retain
these fields. Synchronous iteration capture now uses the normalized complete
completion response so intermediary assistant text and provider metadata are not
lost when the loop yields tool calls separately. Existing nested child/web/image
links, post-commit rescue, callback signatures, and B9 resume behavior remain.

**38 selected tests passed, zero failures/errors, exit 0.** Final log:
`/tmp/ai-debug-thinking-0914-final.log`. Fresh isolated database:
`ai-debug-thinking-tests-0914`, HTTP 22284, gevent 22287, workers/cron disabled.
AI transport and completions were mocked. Added callback/direct thinking tests and
progress persistence checks; existing signed callback rollback/retry, fresh rescue,
subagent, image, search, and browser/asset tests passed. Desktop and mobile frontend
runs each passed **16 tests / 86 assertions**. Initial r1 had two test expectation
failures (added progress events and a mistaken method-versus-server-action search
argument mapping); the final run corrected both. AST/XML parsing and diff checks
passed. No manual/provider or full Website-builder acceptance is claimed.

Only this Custom child was edited. Enterprise and Custom parent checkouts remain
unchanged. Changes are uncommitted; no shared consumer was restarted.

Verified Enterprise SHA-256:

```text
ai/models/ai_session.py 6c40180c94ebba2e1cb5f279bbee9bc058f154a2abc693210a901b0d3c9537f3
ai/models/ai_tool.py 5a61f53d623179848b57bee3a53f29fbc1daf2e5e2784e971103b5d81260643a
ai/controllers/thread.py 2964056e5d2ff89cc311604fff152f407af248d7dcb259c4507ea9e6babddf1a
```

## Current -loop-ref post-commit lifecycle — 2026-09-13

Joseph requested this adaptation after B9 removed the unused internal
`resume_token` parameter, to align ai_debug with the actual current Enterprise
`master-ai-callback-driven-loop-ref` contracts. Enterprise began at `61f88352427`
plus the uncommitted B3–B9 changes, which were committed during this work as
`60d98bc6c163012d1af2010547789ca4b860d775`. The final Enterprise worktree is clean.
Community HEAD: `2b2c1b9b35ada1a723728d52bbc57cfef23f8a55`.
Custom HEAD remains `e8cc9ebd9ba7b6847b33e661109d5feec30cd6dd` plus the preserved
and adapted uncommitted debugger/harness changes.

Production instrumentation now requires `state` on `_save_and_submit_request`.
It records a prepared request when core saves intent and registers post-commit
submission. It no longer claims transport ran before the method returned.
Submission rescue finishes sessions in a fresh environment: `_finish_exchange`
opens an observation span when necessary, preserving child output, parent/tool
links, and parent continuation. Title rescue deletion closes from captured request
facts; successful title callbacks retain their separate completion path. Rescue
failures are reported as `request_failed`, because these model hooks do not receive
the original transport exception. Child output preserves core's actual message.
No callback receipt or result-consumed event is fabricated for submission rescue.

The B9 internal resume signature and `automatic` forwarding are retained. The
controller continues to own browser resume-token validation. The harness reads
request UUID from persisted session status; status no longer reads removed
`request_phase`. The checkpoint asserts raw `loop_state` start acknowledgement,
forwards signed json2 callback bodies, replays the complete signed body, and
expects separate prepared/result iterations. Debugger-owned `responseState`
arguments are internal event helpers, not controller acknowledgement fields;
their consumers were inspected and their contract was retained. Webhook secrets
and callback signatures are explicitly redacted.

**36 selected tests passed, zero failures/errors, exit 0**. Final log:
`/tmp/ai-debug-ref-0913-final.log`. Fresh isolated DB:
`ai-debug-ref-contract-tests-0913`, HTTP 22284, gevent 22287, workers/cron disabled.
All AI transport/completion calls were mocked. Tests cover real post-commit rescue
in fresh transactions for root, follow-up, child and title credit failures, generic
transport failure, signed callback rollback/retry, deferred follow-up submission,
normal nested child delivery, web/image tool traces, resume configuration,
secret redaction, and existing browser/asset checks. The desktop frontend suite
also passed 15 tests / 80 assertions. AST parsing of all 10 debugger/test/harness
Python files and `git diff --check` passed.

Earlier r1/r2 attempts on the old `ai-debug-subagent-tests-0906a` database did not
provide acceptance: dependency drift skipped ai_debug, then stale views blocked
installation. A fresh database resolved the fixture problem; r3 and the final run
passed. The paired standalone IAP checkpoint received source-contract updates but
was not executed. It still depends on the separately deferred
`test_ai_agent_loop` IAP harness and its configured IAP checkouts; no end-to-end
paired-IAP acceptance is claimed. No manual/provider testing, shared server
restart, Enterprise edits, worktree operations, or commits were performed.

Verified Enterprise source SHA-256 values:

```text
ai/models/ai_session.py e9f54bf20eed8edd4127cf6296e6a89bb1917d7072a88454a10cd8afb6d175c6
ai/controllers/thread.py fb66d5492df41811620b9d800fcc70739ecddf29fc0e70641bc1f2b76da7898d
ai/utils/types.py 6616bfc42123014bffa0740b17049970412047c73bbc50e11e7238cc7500dd67
```

## Reference branch credit rejection — 2026-09-10

Custom `master-ai-callback-driven-loop-ref` was created with `wt fork` from
`master-ai-callback-driven-loop` at `e8cc9ebd9ba7b6847b33e661109d5feec30cd6dd`.
The paired Enterprise `master-ai-callback-driven-loop-ref` is at
`2c8ddf107a2bd81d4e3f344f9c6e01e4407d2e2d` plus uncommitted changes in
`ai/models/ai_session.py`, `ai/models/ai_tool.py`, and
`ai_app/models/ir_actions_server.py`.

Enterprise now handles insufficient credits during submission: ordinary sessions
finish immediately, rejected title sessions are deleted, and a rejected new child
returns a tool error before a pending child marker is registered. It also retains
`cron_id` in request context. The earlier insufficient-credit source issue recorded
below is fixed in this paired working tree.

The debugger captures the saved request at core's response-state publication before
transport can reject it. Each submission gets its own observation context so a
failed follow-up closes the correct request once, retaining the exact parent/tool
link and child output. Deleted title traces close from captured facts. Immediate
rejections emit a failed terminal with `insufficient_credit` without inventing a
received callback. The existing trace reducer keeps completed progress when older
round events arrive afterward; no frontend changes were needed.

**38 selected tests passed, zero failures/errors**, process exit **0**. Log:
`/tmp/ai-debug-ref-0910-r1.log`. This includes four new credit-rejection regressions,
physical HTTP rollback/retry tests, existing subagent/search/image coverage, and
browser checks (15 frontend tests, 80 assertions). The isolated database was
`ai-debug-subagent-tests-0906a`, HTTP **22284**, gevent **22287**, with workers and
cron disabled and AI transport/completions mocked. Expected observer/wakeup errors
were injected by isolation tests. No live-provider/manual acceptance is claimed.

Only this Custom child was edited. The Custom parent and Enterprise working trees
were preserved. Adaptation changes remain uncommitted; no shared consumer was
restarted.

Verified Enterprise source SHA-256 values:

```text
ai/models/ai_session.py f8740f4163014f92b84dd22fc054dd5fd53cf12bc4022b2e5920a5eca6c393ca
ai/models/ai_tool.py ad15be99f11ad39dab511ccff62e1041a0ef90e56858ad17c5cc0c04e65ec0a2
ai_app/models/ir_actions_server.py 21407a80e76cf8f57fa327f6072863b10c6515646c691cd0c7a1f19812c7cfd0
```

## Current callback submission and delivery — 2026-09-10

Adapted to clean Enterprise `2c8ddf107a2bd81d4e3f344f9c6e01e4407d2e2d`
on `master-ai-callback-driven-loop`. The debugger now observes
`_save_and_submit_request` and callback results passed directly into
`_continue_agent_loop` / `_continue_channel_name`. It no longer reads removed
request phase/result or continuation fields. Submission occurs inside the core
transaction; trace phases describe observed events rather than a request ledger.

Ordinary start/continue-session tools supply the exact parent tool identity.
Child traces keep that link across subsequent model rounds and start a new trace
when reused for another exchange. Direct nested child delivery captures the exact
result received by the parent. Title traces close from captured facts after core
deletes their temporary session. Synchronous web search and image generation
remain nested beneath their invoking tool, with normalized requests and responses.

**34 selected tests passed, zero failures/errors**, process exit **0**. Log:
`/tmp/ai-debug-current-main-0910-final2.log`. Isolated database:
`ai-debug-subagent-tests-0906a`; HTTP **22284**, gevent **22287**. Coverage includes
physical HTTP callback rollback/retry and persisted Bus/image evidence, nested
child delivery, multi-round child identity and reuse, title-session deletion,
client-result/configuration forwarding, tool-final response preservation, observer
failure isolation, private Bus access, and standalone browser/asset checks.
AI transport/completions were mocked; this is not live-provider/manual acceptance.

Core no longer fences a repeated callback for the same terminal request UUID.
The HTTP tests check unknown-UUID rejection rather than asserting the removed
replay contract. Transport is attempted within each retried transaction; only the
successful transaction's business state and trace events survive.

Independent source finding: Enterprise's insufficient-credit handler in
`_save_and_submit_request` still calls removed `_store_request_result`. This path
is not repaired or masked by ai_debug and remains an Enterprise issue.

Preserved the preexisting context-refresh regression and unrelated
`test_ai_agent_loop` edits. Changes remain uncommitted. No Enterprise edits or
shared-consumer restarts; running consumers need a Python reload to use these hooks.

Verified Enterprise source SHA-256 values:

```text
ai/models/ai_session.py 8f2139ff90afe535a40fa65842f57f41baec313491a0a49c92107fb57017a6ce
ai/controllers/thread.py 2270eadb0722291c12edade8ae0049fb115f2af40a64e681eb355ffa960cb580
ai/models/ai_tool.py 1a1ef89c23eeb9cc8519991f4dd11688d7912cc2f98766bc9c0cf1503660f3a6
```

## Current callback entry points — 2026-09-09

Adapted to Enterprise `e7cb08f790f896d0cf4e31aead1e0584c65b50c5` on
`master-ai-callback-driven-loop`. The controller now stores callback results and
calls `_continue_agent_loop` / `_continue_channel_name` directly. The debugger
observes those handlers and controller-triggered pending-tool aborts, forwards
resume configuration, and captures terminal root/subagent content at
`_finish_exchange`. Removed the obsolete `_continue` hook, suffix field/argument,
and durable web/image/Website helper assumptions.

Current Enterprise runs web search and image generation synchronously inside
tools. Those calls retain company/view context and nest beneath the exact parent
request/tool, using existing debugger IDs without reading the parent's restricted
session through a non-admin tool environment. Their normalized prompts/options
and responses are inspectable. A tool's synthetic final message gets a distinct
iteration so it cannot overwrite the original model tool-call response.

**48 selected tests passed, zero failures/errors**, process exit **0**. Log:
`/tmp/ai-debug-current-main-0909-final.log`. Isolated database:
`ai-debug-subagent-tests-0906a`; HTTP **22284**, gevent **22287**. Tests include
actual HTTP callback rollback/retry/replay with persisted Bus/image evidence,
foreground-child delivery, nested synchronous search/image tools, non-admin
linking, channel titles, configuration forwarding, private Bus access, and the
standalone browser/asset checks. Removed tests targeted continuation types that
no longer exist; their applicable tracing/transaction assertions were replaced
with current-tool coverage. Earlier r1/r2 runs failed on test adapter/schema
mistakes; r3 and the final run passed. No live-provider/manual acceptance claimed.

Preserved the preexisting context-refresh test edit and unrelated
`test_ai_agent_loop` changes. Only ai_debug files changed here; no commits,
Enterprise edits, or shared-consumer restarts. Running consumers still need to
reload this Python code before using the updated debugger.

Verified Enterprise source SHA-256 values:

```text
ai/models/ai_session.py 74f4c9bd6dc966e1decba59fd3de6df55b0e1dcfd01d19404af5ef330abfc51b
ai/controllers/thread.py b3acaa97e4acf68151197422e1ae029dbb2dbb77b7a2bc45e6e9ae5f864e50e8
```

## Website placeholder image continuations — 2026-09-07

Website placeholder children now use the tool call identity already carried by
`ir.actions.server._ai_tool_run` to build their parent trace link. They are
prepared inside `apply_html_to_page`, before its client wait is persisted, so
reading the parent's pending call could select an earlier tool. Ordinary image
and web-search helpers retain their existing suspended-tool linking.

The regression runs two same-name page calls with two image children each. It
checks exact parent request/tool links, success and failure, silent callback
replay, image URL results, and no parent completion or `child_applied` event until
browser acknowledgement. Existing fixtures now configure tools through linked,
loaded skills so the current core tool-context rebuild retains them.

**51 selected tests passed, zero failures/errors**, including the real Website
regression (ai_website installed), normal image/helper tracing, physical HTTP
atomic retry/replay, and standalone browser checks. Isolated database:
`ai-debug-subagent-tests-0906a`, HTTP **22284**, gevent **22287**. Log:
`/tmp/ai-debug-website-images-suite-r2-0907.log`. Process exit: **0**.
Earlier logs `ai-debug-website-images-focused-0907.log` and
`ai-debug-website-images-suite-0907.log` expose the obsolete direct-tool fixture
setup; those runs failed and are not acceptance evidence. Python AST parsing and
`git diff --check -- ai_debug` passed. No provider or manual tests were run, no
shared consumers were restarted, and no commits were made.

Enterprise HEAD was `28110c9b77ffec23de622671c603a0223f193b6b` plus the image
migration's uncommitted changes. Relevant source SHA-256 values at completion:

```text
ai/models/ai_session.py be725bbfe2d087ce375e8438490023e9e01c87c6da6efa529c372b402e0eedaf
ai/models/ai_tool.py f1fd805cd30ba8e5d131c0c35dcd6f33f8015b81b067850ec50a09fcf029d35f
ai_website/models/ai_website_service.py b199aa428653ee9fdcd82ff7a787a9b6f9637c7b281d6e35dca8b66f48a19c62
ai_website/models/ai_session.py 069d005798d3a08dae0f2258ec88127ee3c1fef7697397737959eca3bab6ecfe
```

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
