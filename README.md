# Odoo Custom Addons

## test_ai_agent_loop — Callback-driven agent-loop tests

This test-only addon owns the callback-specific Python and Hoot coverage for
the Enterprise `ai` module. Install it on a disposable database to run the
focused callback suite:

```bash
cd /Users/joseph/.wt/worktrees/odoo/enterprise/master-ai-callback-driven-loop

odev -P core start -- \
  -d test-ai-agent-loop-durable-SUFFIX \
  -i test_ai_agent_loop \
  --test-enable \
  --test-tags /test_ai_agent_loop \
  --stop-after-init \
  --max-cron-threads=0 \
  --without-demo \
  --http-port=18469 \
  --gevent-port=18472
```

Replace `SUFFIX` with a fresh short value so the install runs on a disposable
database. Use `-u test_ai_agent_loop` instead of `-i` when intentionally
rerunning an already-installed test database.

The paired consumer/IAP fake-provider checkpoint is available separately:

```bash
cd /Users/joseph/.wt/worktrees/caburj/custom/master-ai-callback-driven-loop

/Users/joseph/.venvs/master/bin/python3 \
  test_ai_agent_loop/tests/harness/run_plain_callback_checkpoint.py \
  --scenario plain

/Users/joseph/.venvs/master/bin/python3 \
  test_ai_agent_loop/tests/harness/run_plain_callback_checkpoint.py \
  --scenario server-tool

/Users/joseph/.venvs/master/bin/python3 \
  test_ai_agent_loop/tests/harness/run_plain_callback_checkpoint.py \
  --scenario confirmation-tools

/Users/joseph/.venvs/master/bin/python3 \
  test_ai_agent_loop/tests/harness/run_plain_callback_checkpoint.py \
  --scenario question
```

## ai_debug — Live Tracer for the AI Agentic Loop

### Setup

1. **Add this directory to the addons path** when starting `odoo-bin`:

   ```bash
   ./odoo-bin --addons-path=odoo/addons,enterprise,custom
   ```

2. **Install the `ai_debug` module** (requires `ai_app` and `bus`):

   ```bash
   ./odoo-bin --addons-path=odoo/addons,enterprise,custom -d mydb -i ai_debug
   ```

3. **Navigate to** [`/ai-debug`](http://localhost:8069/ai-debug) in your browser.
