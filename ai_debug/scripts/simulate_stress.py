# ai_debug/scripts/simulate_stress.py
#
# Stress-test simulation for ai_debug frontend viewer.
# Generates fake threads/loops/iterations/tool_calls with bus notifications.
#
# Usage:
#   odev eval ai_debug/scripts/simulate_stress.py
#   ODEV_THREADS=10 ODEV_SPEED=0 odev eval ai_debug/scripts/simulate_stress.py
#
# Config (ODEV_* env vars):
#   THREADS        (default 300)  — number of threads
#   SPEED          (default 1)    — speed multiplier; 0 = burst mode
#   MIN_LOOPS      (default 10)   — min loops per thread
#   MAX_LOOPS      (default 50)   — max loops per thread
#   MIN_ITERATIONS (default 2)    — min iterations per loop
#   MAX_ITERATIONS (default 20)   — max iterations per loop
#   MIN_TOOLS      (default 1)    — min tool calls per iteration
#   MAX_TOOLS      (default 10)   — max tool calls per iteration
#   USER_ID        (default 2)    — target user for bus notifications (2 = admin)
#   SUBAGENT_RATIO (default 0)    — probability [0,1] that a tool call spawns a sub-agent
#                                   (set > 0 to generate nested-thread demo data)
#   MAX_DEPTH      (default 2)    — max nesting depth for sub-agents (0 = no sub-agents)

import random
import time
import uuid

from odoo import fields

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_l = locals()

THREADS = int(_l.get('threads', 300))
SPEED = float(_l.get('speed', 1))
MIN_LOOPS = int(_l.get('min_loops', 10))
MAX_LOOPS = int(_l.get('max_loops', 50))
MIN_ITERATIONS = int(_l.get('min_iterations', 2))
MAX_ITERATIONS = int(_l.get('max_iterations', 20))
MIN_TOOLS = int(_l.get('min_tools', 1))
MAX_TOOLS = int(_l.get('max_tools', 10))
USER_ID = int(_l.get('user_id', 2))
SUBAGENT_RATIO = float(_l.get('subagent_ratio', 0))
MAX_DEPTH = int(_l.get('max_depth', 2))

# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------
THREAD_NAMES = [
    "Analyze Q1 revenue report",
    "Fix invoice tax calculation",
    "Create purchase order workflow",
    "Debug bank reconciliation",
    "Update employee payroll rules",
    "Generate aged receivable report",
    "Configure multi-currency setup",
    "Review inventory valuation",
    "Automate expense approval",
    "Set up intercompany transactions",
    "Fix journal entry imbalance",
    "Create custom financial dashboard",
    "Debug payment matching algorithm",
    "Update chart of accounts structure",
    "Reconcile bank statement differences",
    "Set up analytic accounting tags",
    "Fix depreciation schedule calculation",
    "Create vendor bill automation",
    "Debug POS closing entry errors",
    "Configure tax return template",
]

SUB_AGENT_NAMES = [
    "tax_expert",
    "invoice_validator",
    "report_builder",
    "data_analyst",
    "document_classifier",
    "inventory_auditor",
    "payment_matcher",
    "fx_rate_lookup",
    "vendor_researcher",
    "compliance_reviewer",
]

USER_QUERIES = [
    "What's the total receivable for partner Azure Interior?",
    "Create a credit note for invoice INV/2025/0042",
    "Show me the balance sheet as of December 31",
    "Why is the bank reconciliation off by 1,500?",
    "Generate an aged payable report grouped by vendor",
    "Update the tax rate for domestic sales to 21%",
    "Create a recurring journal entry for monthly rent",
    "What are the top 10 overdue invoices?",
    "Reconcile all unmatched bank statement lines",
    "Show me the profit and loss for Q3 2025",
    "Create a purchase order for 500 units of product A",
    "What's the current inventory valuation for warehouse WH/Stock?",
    "Fix the exchange rate difference on invoice INV/2025/0188",
    "Generate a cash flow forecast for next quarter",
    "Show me all draft invoices older than 30 days",
]

MODEL_NAMES = [
    "claude-sonnet-4-20250514",
    "claude-haiku-4-20250514",
    "gpt-4o",
    "gemini-2.0-flash",
]

PROVIDER_NAMES = [
    "anthropic",
    "anthropic",
    "openai",
    "google",
]

TOOL_NAMES = [
    "execute_python",
    "search_records",
    "create_record",
    "update_record",
    "search_read",
    "get_report",
    "send_message",
    "browse_website",
]

TOOL_ARGS_TEMPLATES = {
    "execute_python": [
        {"code": "env['res.partner'].search_count([('is_company', '=', True)])"},
        {"code": "env['account.move'].search([('state', '=', 'posted')]).mapped('amount_total')"},
        {"code": "sum(env['account.move.line'].search([('account_id.name', '=', 'Receivable')]).mapped('balance'))"},
    ],
    "search_records": [
        {"model": "res.partner", "domain": [["is_company", "=", True]], "limit": 10},
        {"model": "account.move", "domain": [["state", "=", "draft"]], "limit": 20},
        {"model": "product.product", "domain": [["qty_available", ">", 0]]},
    ],
    "create_record": [
        {"model": "account.move", "values": {"partner_id": 7, "move_type": "out_invoice"}},
        {"model": "purchase.order", "values": {"partner_id": 12, "date_order": "2025-06-01"}},
    ],
    "update_record": [
        {"model": "res.partner", "id": 42, "values": {"phone": "+1-555-0199"}},
        {"model": "account.move", "id": 101, "values": {"ref": "Updated reference"}},
    ],
    "search_read": [
        {"model": "account.move.line", "domain": [["parent_state", "=", "posted"]], "fields": ["name", "balance"], "limit": 50},
        {"model": "res.partner", "domain": [], "fields": ["name", "email", "total_due"], "limit": 10},
    ],
    "get_report": [
        {"report_name": "account.report_invoice", "record_id": 42},
        {"report_name": "account.report_partnerledger", "partner_id": 7},
    ],
    "send_message": [
        {"model": "mail.channel", "res_id": 1, "body": "Here is the report you requested."},
        {"model": "discuss.channel", "res_id": 5, "body": "I've updated the invoice as requested."},
    ],
    "browse_website": [
        {"url": "/my/invoices", "extract": "table"},
        {"url": "/my/account", "extract": "balance"},
    ],
}

TOOL_RESULTS = {
    "execute_python": ["42", "150432.50", "[10200.00, 8500.00, 3200.00]", "True", "{'total': 25680.00}"],
    "search_records": ["Found 42 records", "Found 7 records", "Found 183 records", "No records found"],
    "create_record": ["Created record #1042", "Created record #2087", "Created record #558"],
    "update_record": ["Updated 1 record", "Updated successfully"],
    "search_read": [
        '[{"name": "INV/2025/0001", "balance": 1500.00}, {"name": "INV/2025/0002", "balance": 3200.00}]',
        '[{"name": "Azure Interior", "email": "azure@example.com", "total_due": 15000.00}]',
    ],
    "get_report": ["Report generated successfully (PDF, 45KB)", "Report generated successfully (PDF, 128KB)"],
    "send_message": ["Message sent", "Message posted to channel"],
    "browse_website": ['{"table": [["INV001", "$1,500"], ["INV002", "$3,200"]]}', '{"balance": "$25,680.00"}'],
}

OUTPUT_MESSAGES = [
    "I'll search for the relevant records to answer your question.",
    "Let me look up the account balances for this period.",
    "I need to check the journal entries to understand the discrepancy.",
    "Let me create the required document with the specified parameters.",
    "I'll run a query to get the current totals.",
    "Looking at the transaction history to identify the issue.",
    "Let me verify the tax configuration before making changes.",
    "I'll check the reconciliation status for these entries.",
    "Running the calculation to determine the correct amounts.",
    "Let me pull up the relevant report data.",
    "I found the records. Let me analyze the results.\n\n```python\ntotals = env['account.move.line'].read_group(\n    [('parent_state', '=', 'posted')],\n    ['balance:sum'],\n    ['account_id'],\n)\n```\n\nThe query shows 3 account groups with balances.",
    "Here's what I found:\n\n- **Receivables:** $45,200.00\n- **Payables:** $32,100.00\n- **Net:** $13,100.00\n\nLet me verify with the subledger.",
    "The reconciliation difference comes from two unmatched lines:\n\n| Date | Reference | Amount |\n|------|-----------|--------|\n| 03/15 | PAY/001 | $750.00 |\n| 03/22 | PAY/002 | $750.00 |\n\nTotal difference: $1,500.00",
]

LOOP_OUTPUT_MESSAGES = [
    "<p>Based on my analysis, the total receivable is <strong>$45,200.00</strong> across 23 open invoices.</p>",
    "<p>I've created the credit note <strong>CN/2025/0042</strong> with the reversed amounts.</p>",
    "<p>The bank reconciliation difference of $1,500 is caused by two unmatched payments from March.</p>",
    "<p>The report has been generated and is available in the Accounting dashboard.</p>",
    "<p>I've updated the configuration as requested. The changes will apply to new transactions.</p>",
    "<p>Here's a summary of the aged receivables:</p><ul><li>Current: $12,000</li><li>1-30 days: $8,500</li><li>31-60 days: $3,200</li><li>60+ days: $1,500</li></ul>",
]

SYSTEM_INSTRUCTIONS = (
    "You are an AI accounting assistant for Odoo. You help users with financial "
    "queries, report generation, and accounting operations. Use the available tools "
    "to search records, create documents, and run calculations. Always verify data "
    "before making changes."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def maybe_sleep(min_ms, max_ms):
    """Sleep for a random duration in [min_ms, max_ms] adjusted by SPEED.
    No-op when SPEED == 0 (burst mode). Returns actual sleep ms."""
    if SPEED == 0:
        return random.randint(min_ms, max_ms)
    delay_ms = random.randint(min_ms, max_ms)
    time.sleep(delay_ms / 1000.0 / SPEED)
    return delay_ms


def random_call_id():
    return "call_" + uuid.uuid4().hex[:24]


def random_tool():
    name = random.choice(TOOL_NAMES)
    args = random.choice(TOOL_ARGS_TEMPLATES[name])
    result = random.choice(TOOL_RESULTS[name])
    return name, args, result


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

user = env['res.users'].browse(USER_ID)
Thread = env['ai.debug.thread']
Loop = env['ai.debug.loop']
Iteration = env['ai.debug.iteration']
ToolCall = env['ai.debug.tool.call']
cr = env.cr

# Sample up to 5 ``use_in_ai=True`` server actions to attach to iterations
# (so the "Available Tools" tab has something to show). If no such actions
# exist in the DB, the list stays empty and iterations are created with no
# available tools -- the tab renders its "No tools provided" fallback.
# The referenced rows aren't shipped in the bus payload anymore: the client
# lazy-loads them via ``store.ensureLazyField`` when the tab is opened.
_ai_tools = env['ir.actions.server'].search([('use_in_ai', '=', True)])
SAMPLED_TOOLS = _ai_tools[:5]
SAMPLED_TOOL_IDS = SAMPLED_TOOLS.ids
if not SAMPLED_TOOL_IDS:
    print("(note: no ir.actions.server with use_in_ai=True -- Available Tools tab will be empty)")

total_loops = 0
total_iterations = 0
total_tool_calls = 0
total_subagents = 0
sim_start = time.monotonic()


def simulate_thread(t_idx, parent_tool_call_db_id=None, parent_thread_id=None,
                    depth=0):
    """Simulate one thread end-to-end, optionally nested under a parent tool call.

    At depth > 0, loop/iteration/tool counts are scaled down so sub-agents stay
    small. After each tool call, rolls the SUBAGENT_RATIO dice (halved at deeper
    depths) to recursively spawn a nested thread.
    """
    global total_loops, total_iterations, total_tool_calls, total_subagents

    session_id = str(uuid.uuid4())
    is_subagent = depth > 0
    if is_subagent:
        agent_name = random.choice(SUB_AGENT_NAMES)
        thread_name = agent_name
    else:
        agent_name = 'Stress Test Agent'
        thread_name = random.choice(THREAD_NAMES)

    # Scale counts down at deeper nesting: /2 at depth 1, /4 at depth 2, etc.
    scale = 2 ** depth
    t_min_loops = max(1, MIN_LOOPS // scale)
    t_max_loops = max(t_min_loops, MAX_LOOPS // scale)
    t_min_iters = max(1, MIN_ITERATIONS // scale)
    t_max_iters = max(t_min_iters, MAX_ITERATIONS // scale)
    t_min_tools = max(1, MIN_TOOLS // scale) if is_subagent else MIN_TOOLS
    t_max_tools = max(t_min_tools, MAX_TOOLS // scale) if is_subagent else MAX_TOOLS

    # -- Create thread --
    thread = Thread.create({
        'session_id': session_id,
        'name': thread_name,
        'user_id': user.id,
    })
    if SPEED:
        user._bus_send("AI_DEBUG_NEW_THREAD", {
            'id': thread.id,
            'session_id': session_id,
            'name': thread_name,
            'agent_id': None,
            'agent_name': agent_name,
            'user_id': user.id,
            'user_name': user.name,
            'loop_count': 0,
            'parent_thread_id': parent_thread_id,
        })
    cr.commit()

    num_loops = random.randint(t_min_loops, t_max_loops)

    for l_idx in range(1, num_loops + 1):
        model_idx = random.randrange(len(MODEL_NAMES))
        model_name = MODEL_NAMES[model_idx]
        provider_name = PROVIDER_NAMES[model_idx]
        input_message = random.choice(USER_QUERIES)
        loop_start = time.monotonic()

        # -- Create loop --
        # Subagent threads link every loop back to the parent tool call that
        # triggered it; in the stress sim we only have one parent call to
        # attribute, so attach all loops to it. Production code links each
        # follow-up loop to its own continue_session call.
        loop = Loop.create({
            'thread_id': thread.id,
            'parent_tool_call_id': parent_tool_call_db_id,
            'model_name': model_name,
            'instructions': SYSTEM_INSTRUCTIONS,
            'input_message': input_message,
            'is_running': True,
            'start_time': fields.Datetime.now(),
        })
        if SPEED:
            user._bus_send("AI_DEBUG_NEW_LOOP", {
                'id': loop.id,
                'thread_id': thread.id,
                'session_id': session_id,
                'parent_tool_call_id': parent_tool_call_db_id,
                'agent_id': None,
                'agent_name': agent_name,
                'model_name': model_name,
                'provider': provider_name,
                'instructions': SYSTEM_INSTRUCTIONS,
                'input_message': input_message,
                'is_running': True,
                'start_time': fields.Datetime.now().isoformat(),
            })
        cr.commit()

        num_iterations = random.randint(t_min_iters, t_max_iters)

        for i_idx in range(1, num_iterations + 1):
            is_final = (i_idx == num_iterations)
            tokens_in = random.randint(500, 8000)
            tokens_cached = random.randint(0, int(tokens_in * 0.8))
            tokens_out = random.randint(50, 2000)
            output_message = random.choice(OUTPUT_MESSAGES)
            num_tools = random.randint(t_min_tools, t_max_tools)
            iter_duration = maybe_sleep(500, 1250)

            # -- Create iteration --
            iteration = Iteration.create({
                'loop_id': loop.id,
                'sequence': i_idx,
                'messages_delta': (
                    [{"role": "user", "content": input_message}] if i_idx == 1 else []
                ),
                'raw_response': {"model": model_name, "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}},
                'output_message': output_message,
                'tokens_in': tokens_in,
                'tokens_cached': tokens_cached,
                'tokens_out': tokens_out,
                'duration_ms': iter_duration,
                'available_tool_ids': [(6, 0, SAMPLED_TOOL_IDS)],
            })
            if SPEED:
                user._bus_send("AI_DEBUG_ITERATION", {
                    'id': iteration.id,
                    'loop_id': loop.id,
                    'sequence': i_idx,
                    'messages_delta': (
                        [{"role": "user", "content": input_message}] if i_idx == 1 else []
                    ),
                    'raw_response': {"model": model_name},
                    'output_message': output_message,
                    'tokens_in': tokens_in,
                    'tokens_cached': tokens_cached,
                    'tokens_out': tokens_out,
                    'duration_ms': iter_duration,
                    'has_tool_calls': num_tools > 0,
                    'is_final': is_final,
                    'provider': provider_name,
                    'available_tool_ids': SAMPLED_TOOL_IDS,
                })
            cr.commit()

            # -- Create tool calls --
            for _ in range(num_tools):
                tool_name, tool_args, tool_result = random_tool()
                call_id = random_call_id()

                tc_record = ToolCall.create({
                    'iteration_id': iteration.id,
                    'call_id': call_id,
                    'name': tool_name,
                    'arguments': tool_args,
                })
                if SPEED:
                    user._bus_send("AI_DEBUG_TOOL_CALL_STARTED", {
                        'id': tc_record.id,
                        'iteration_id': iteration.id,
                        'loop_id': loop.id,
                        'call_id': call_id,
                        'tool_name': tool_name,
                        'name': tool_name,
                        'tool_id': False,
                        'arguments': tool_args,
                    })
                cr.commit()

                tc_duration = maybe_sleep(50, 350)

                tc_record.write({
                    'result': tool_result,
                    'duration_ms': tc_duration,
                })
                if SPEED:
                    user._bus_send("AI_DEBUG_TOOL_CALL_COMPLETED", {
                        'id': tc_record.id,
                        'iteration_id': iteration.id,
                        'loop_id': loop.id,
                        'call_id': call_id,
                        'name': tool_name,
                        'result': tool_result,
                        'success': True,
                        'duration_ms': tc_duration,
                    })
                cr.commit()
                total_tool_calls += 1

                # -- Maybe spawn a sub-agent for this tool call --
                # Halve probability at each deeper level to avoid explosion.
                if depth < MAX_DEPTH and SUBAGENT_RATIO > 0:
                    p = SUBAGENT_RATIO / (2 ** depth)
                    if random.random() < p:
                        total_subagents += 1
                        simulate_thread(
                            t_idx=t_idx,
                            parent_tool_call_db_id=tc_record.id,
                            parent_thread_id=thread.id,
                            depth=depth + 1,
                        )

            total_iterations += 1

        # -- Finalize loop --
        loop_duration = int((time.monotonic() - loop_start) * 1000)
        output_html = random.choice(LOOP_OUTPUT_MESSAGES)
        loop.write({
            'is_running': False,
            'output_message': output_html,
            'termination_reason': 'success',
            'duration_ms': loop_duration,
        })
        if SPEED:
            user._bus_send("AI_DEBUG_LOOP_END", {
                'id': loop.id,
                'thread_id': thread.id,
                'is_running': False,
                'output_message': output_html,
                'termination_reason': 'success',
                'error_message': False,
                'duration_ms': loop_duration,
                'iteration_count': num_iterations,
            })
        cr.commit()
        total_loops += 1

    return num_loops


print(f"Starting stress simulation: {THREADS} threads, speed={SPEED}")
print(f"Loops/thread: {MIN_LOOPS}-{MAX_LOOPS}, Iterations/loop: {MIN_ITERATIONS}-{MAX_ITERATIONS}, Tools/iteration: {MIN_TOOLS}-{MAX_TOOLS}")
if SUBAGENT_RATIO > 0:
    print(f"Sub-agents: ratio={SUBAGENT_RATIO}, max_depth={MAX_DEPTH}")
print()

for t_idx in range(1, THREADS + 1):
    num_loops = simulate_thread(t_idx)
    elapsed = time.monotonic() - sim_start
    print(f"Thread {t_idx}/{THREADS} done ({num_loops} loops) — {elapsed:.1f}s elapsed")

elapsed = time.monotonic() - sim_start
print()
print(f"Simulation complete in {elapsed:.1f}s")
print(f"  Threads:    {THREADS} roots + {total_subagents} sub-agents")
print(f"  Loops:      {total_loops}")
print(f"  Iterations: {total_iterations}")
print(f"  Tool calls: {total_tool_calls}")
