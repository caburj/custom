# Feature Research

**Domain:** AI/LLM agentic loop debugger — Odoo-native developer tool
**Researched:** 2026-02-20
**Confidence:** MEDIUM-HIGH (ecosystem tools well-documented; Odoo-native translation is original reasoning based on verified ecosystem patterns)

---

## Reference Ecosystem

Tools studied: LangSmith, Braintrust, Arize Phoenix, Langfuse. These are the gold standard for LLM observability and define what the domain expects. The Odoo AI Debugger translates these concepts into an Odoo-native module — no external infrastructure, data in ORM models, UI in OWL.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Trace capture** — one record per agentic loop run | Every LLM observability tool (LangSmith, Langfuse, Braintrust, Phoenix) organizes data around traces. Developers won't call it a debugger if it doesn't have this. | LOW | `ai.debug.trace` model. Already designed in PROJECT.md. |
| **Iteration records** — one record per LLM call within a loop | The loop runs 1–20 times per trace. Collapsing iterations loses the most critical diagnostic signal: which call went wrong. | LOW | `ai.debug.iteration` model. Already designed. |
| **Tool call records** — per-execution capture of name, args, result, success, duration | Every tool-call-capable agent debugger captures this. Without it, you can't tell what the agent actually did. | LOW | `ai.debug.tool.call` model. Already designed. |
| **Full LLM input capture** — exact messages array sent to the provider | The messages sent are often different from what you expect (system prompt injection, RAG context, previous turn history). Must see exactly what the LLM received. | LOW | `messages_sent` Json field on iteration. |
| **Raw LLM response capture** — provider JSON verbatim | Diagnosing malformed tool calls, unexpected stop reasons, or refusal messages requires the raw response, not a parsed summary. | LOW | `raw_response` Json field on iteration. |
| **Loop termination reason** — why the loop stopped | The three outcomes (final message, max iterations hit, confirmation pause) have completely different implications. Must be explicit. | LOW | Covered by `state` on trace + `final_message` on iteration + `triggered_confirmation` on tool call. |
| **Timing data** — duration_ms on trace, iteration, and tool call | Latency debugging is the most common first question ("why is this slow?"). All three tools studied expose per-span timing. | LOW | Fields already designed. |
| **Backend list + form views** — searchable history of all traces | Developers need post-mortem inspection without writing ORM queries. Standard Odoo views make traces first-class data. | LOW | Standard Odoo list/form/search views. No novel complexity. |
| **Enable/disable switch** — `ir.config_parameter` master toggle | Running full capture in a production environment with real users would be unacceptable overhead and a privacy risk. The switch must exist before anyone can use the module safely. | LOW | `ai_debugger.enabled` config param. |
| **Trace retention / auto-cleanup** — configurable TTL with scheduled deletion | Debug data accumulates fast (every AI interaction). Without TTL, the database fills up. All production observability tools have this (Langfuse, LangSmith). | LOW | `ai_debugger.retention_days` + scheduled action. |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Live real-time debug panel** — OWL UI updated via bus.bus as the loop runs | External tools (LangSmith, Langfuse) show traces only after completion. Watching the loop live — seeing tool calls appear one by one as they execute — is not available in any Odoo-native tool and is the core development-time value proposition. | HIGH | OWL component + bus.bus channel per session. Most complex part of the module. |
| **State diff viewer** — visual diff of `tools_context['state']` between iterations | State mutation across iterations is a primary source of bugs (a tool sets state incorrectly, corrupting all downstream calls). Phoenix and LangSmith show state, but not diffs. Showing exactly what changed each iteration is a direct debugging accelerant. | MEDIUM | JSON diff on `state_before` / `state_after`. Can use Python `deepdiff` or a simple JS renderer. |
| **Confirmation flow tracking** — explicit capture of pause/resume state | The Odoo `ai` module has a unique two-phase confirmation pattern (`tool_request_message`, `pending_tool_call_id`). External tools have no concept of this. Surfacing which tool triggered a confirmation pause and what the pending call ID is has no analogue in LangSmith/Langfuse. | LOW | `triggered_confirmation` + `confirmation_message` fields already designed. |
| **JSON tree renderer** — collapsible, syntax-highlighted inline JSON viewer | Raw JSON blobs (messages array, raw LLM response) are unreadable in a plain `<textarea>`. A custom OWL JSON tree component makes the data explorable without copy-pasting to an external viewer. | MEDIUM | OWL component. Reusable across message viewer and state diff. |
| **System prompt + RAG context capture** — full instructions and injected chunks per trace | LangSmith captures this as the first span's input. Odoo-native access to `_get_instructions()` and `_get_context_input()` output is the most direct way to answer "why did the agent say X?" | MEDIUM | Requires instrumentation at `_generate_next_response()` entry in addition to `_run_agentic_loop()`. |
| **Per-agent filter in history views** — filter traces by `ai.agent` | Comparing traces across agent configurations (e.g., GPT-4o vs Gemini, different system prompts) is a primary workflow. Standard OWL search + `domain` on `agent_id` makes this trivial. | LOW | Standard Odoo search view filter. Trivially added. |
| **Error surfacing** — explicit `state = 'error'` with exception capture | The loop can fail with a Python exception (provider timeout, malformed response). An `error` state with the exception message stored lets developers see failures without reading server logs. | LOW | Try/except in the inherited generator methods. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **HTTP-level LLM traffic interception** — proxy or monkey-patch the provider HTTP client | "I want to see the exact HTTP request/response." Sounds thorough. | Monkey-patching `requests` or `httpx` in Odoo is fragile, breaks with provider library updates, and risks intercepting unrelated traffic. MODEL.md explicitly rules this out. The Odoo model layer already captures everything needed. | Capture at the `ai.session` model layer via `_inherit`. The provider formats the data before sending; capture it there. Confidence: HIGH — Odoo inheritance gives full access without HTTP-layer hacks. |
| **Prompt editing / replay** — edit a captured trace's messages and re-run | LangSmith and Arize Phoenix both have this (Phoenix calls it "span replay"). Users will ask for it. | Requires UI to construct and fire a new `ai.session` run with modified inputs. Odoo's session lifecycle (`TransientModel`, tied to a chat channel) makes replay non-trivial — there is no "dry run" mode. Building this safely is a significant scope expansion for v1. | Defer to v2. For now, copy the messages JSON to use in manual testing. Add a "copy messages JSON" button as a stepping stone. |
| **Evaluation / scoring framework** — automated LLM-as-judge scoring of traces | LangSmith, Braintrust, and Langfuse all have this. It's the logical next step after tracing. | This is a separate product category (LLMOps eval pipeline). It requires prompt templates for judges, a scoring data model, dataset management, and experiment comparison. Out of scope for a single-developer debugger module. | Log `result` and `success` from tool calls. Let developers do qualitative review via the history views. Evaluation is v3+. |
| **Multi-instance / distributed tracing** — trace across multiple Odoo workers or instances | Sounds like proper observability. | The agentic loop in Odoo is single-process (one worker handles one request). Distributed tracing adds OpenTelemetry complexity that provides no value for the single-instance local development target. PROJECT.md explicitly out-of-scopes this. | If distributed tracing ever matters, bolt on OpenTelemetry export at the trace level. Build the data model cleanly so it can emit OTLP spans later. |
| **Real-time token streaming capture** — capture the LLM token stream mid-generation | "I want to see tokens as they appear." | Odoo's `generate_response` endpoint uses line-delimited JSON, not true SSE with token-level streaming. The `ai.session` model receives complete chunks, not individual tokens. There is no obvious hook for true per-token capture without modifying the provider layer. | Capture full response chunks at `provider._format_from_llm()` return. Iteration-level timing (duration_ms) tells you how long the LLM took to respond. Per-token streaming is false precision for debugging purposes. |
| **Mobile / responsive UI for the live panel** | Developers sometimes work on tablets. | The live debug panel is a developer tool. It shows raw JSON, state diffs, multi-column iteration cards. Responsive layout for this level of data density is a design rabbit hole. PROJECT.md explicitly out-of-scopes mobile. | Desktop-only with a minimum width. Enforce with CSS `min-width`. |

---

## Feature Dependencies

```
[Trace capture model]
    └──required-by──> [Backend list/form views]
    └──required-by──> [Live real-time debug panel]
    └──required-by──> [State diff viewer]
    └──required-by──> [Error surfacing]

[Iteration records model]
    └──required-by──> [State diff viewer]  (needs state_before / state_after)
    └──required-by──> [JSON tree renderer] (renders messages_sent, raw_response)

[Tool call records model]
    └──required-by──> [Confirmation flow tracking]

[Enable/disable switch]
    └──must-precede──> [All capture features] (safety gate before any data is recorded)

[Live real-time debug panel]
    └──requires──> [bus.bus channel setup]
    └──requires──> [Trace capture model] (needs trace ID for channel name)
    └──enhances-with──> [JSON tree renderer]
    └──enhances-with──> [State diff viewer]

[System prompt + RAG context capture]
    └──requires──> [Trace capture model] (stored on ai.debug.trace)
    └──requires-instrumentation-at──> [_generate_next_response hook] (different from _run_agentic_loop hook)

[Trace retention / auto-cleanup]
    └──requires──> [Trace capture model] (nothing to clean without traces)
```

### Dependency Notes

- **Trace capture is the root dependency.** Everything else — views, live panel, state diff — flows from having a `ai.debug.trace` record.
- **Live panel depends on trace capture and bus.bus, not on iteration/tool records.** The panel can start working with a "trace opened" event and add iterations incrementally. This means the live panel can be built before iteration details are polished.
- **State diff requires both state_before and state_after fields.** These are set at the iteration level by the instrumentation. The diff viewer can only be built after the data model captures both snapshots.
- **Enable/disable must be respected before any instrumentation fires.** The inherited `_run_agentic_loop()` must check the config param at the top. This is trivially cheap and blocks accidental capture in production.
- **System prompt + RAG capture requires a separate instrumentation hook.** The `_generate_next_response()` method sits above `_run_agentic_loop()` in the call stack. Capturing system prompt requires inheriting or wrapping at that level, which is a separate `_inherit` override.

---

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to make the module useful as a debugging tool.

- [ ] **Trace capture** (`ai.debug.trace`) — one record per agentic loop run with agent, model, total duration, iteration count, termination state
- [ ] **Iteration records** (`ai.debug.iteration`) — one per LLM call with full messages sent, raw response, state snapshots, timing
- [ ] **Tool call records** (`ai.debug.tool.call`) — per-execution with name, args, result, success, timing, confirmation flags
- [ ] **Enable/disable config param** — master switch checked before any capture; safe to deploy
- [ ] **Trace retention / auto-cleanup** — scheduled action with configurable TTL; required before first real use
- [ ] **Backend list + form views** — searchable, filterable trace history; usable immediately for post-mortem inspection
- [ ] **Error surfacing** — `state = 'error'` with exception message; makes failures visible without reading server logs

### Add After Validation (v1.x)

Features to add once core instrumentation is confirmed working.

- [ ] **Live real-time debug panel** — OWL component subscribing to bus.bus; add once data model is proven correct; this is where most development time will go
- [ ] **State diff viewer** — JSON diff rendered in the live panel and history form; add once live panel exists
- [ ] **JSON tree renderer** — collapsible JSON for messages and raw responses; add alongside live panel for UX quality
- [ ] **System prompt + RAG context capture** — hook into `_generate_next_response()`; straightforward addition once the instrumentation pattern is established

### Future Consideration (v2+)

Features to defer until core is validated.

- [ ] **Prompt replay / re-run** — requires designing a safe "re-execute with modified input" flow; significant scope
- [ ] **Export to OTLP / OpenTelemetry** — would allow piping traces to Jaeger, Grafana, etc.; only useful if the module outlives local development
- [ ] **Evaluation / scoring** — LLM-as-judge scoring of captured traces; a separate product category

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Trace capture model | HIGH | LOW | P1 |
| Iteration records model | HIGH | LOW | P1 |
| Tool call records model | HIGH | LOW | P1 |
| Enable/disable switch | HIGH | LOW | P1 |
| Trace retention / auto-cleanup | HIGH | LOW | P1 |
| Backend list + form views | HIGH | LOW | P1 |
| Error surfacing | HIGH | LOW | P1 |
| Live real-time debug panel | HIGH | HIGH | P1 (v1.x — core differentiator) |
| State diff viewer | HIGH | MEDIUM | P2 |
| JSON tree renderer | MEDIUM | MEDIUM | P2 |
| System prompt + RAG capture | MEDIUM | LOW | P2 |
| Confirmation flow tracking | MEDIUM | LOW | P2 (fields already in model) |
| Per-agent filter in history | LOW | LOW | P2 (trivial to add) |
| Prompt replay / re-run | MEDIUM | HIGH | P3 |
| OTLP export | LOW | HIGH | P3 |
| Evaluation / scoring | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

| Feature | LangSmith | Arize Phoenix | Langfuse | Odoo AI Debugger (this module) |
|---------|-----------|---------------|----------|-------------------------------|
| Trace / span hierarchy | Yes — full tree | Yes — graph visualization | Yes — trace > span > observation | Yes — trace > iteration > tool call |
| Real-time streaming view | Yes (live updates) | Partial | No (post-completion) | Yes via bus.bus — unique advantage |
| State diff across iterations | No | No | No | Yes — differentiator |
| Tool call capture | Yes | Yes | Yes | Yes |
| Loop termination reason | Partial (stop reason) | Partial | Partial | Yes — explicit (final message / max iterations / confirmation pause) |
| Confirmation pause tracking | No | No | No | Yes — unique to Odoo AI module |
| Backend ORM queryable data | No (external SaaS) | No (external) | Yes (self-hosted) | Yes — standard Odoo models |
| No external infrastructure | No | No (requires Phoenix server) | No (requires Langfuse server) | Yes — installs as standard Odoo module |
| Evaluation / scoring | Yes | Yes | Yes | No (explicitly out of scope for v1) |
| Prompt replay | Yes | Yes (span replay) | No | No (v2+) |
| Cost tracking | Yes | Yes | Yes | No — not applicable (local dev target; no billing data) |

---

## Sources

- [LangSmith Observability — langchain.com](https://www.langchain.com/langsmith/observability) — MEDIUM confidence (official product page, marketing-adjacent)
- [Debugging Deep Agents with LangSmith — blog.langchain.com](https://blog.langchain.com/debugging-deep-agents-with-langsmith/) — MEDIUM confidence (official blog)
- [Arize Phoenix docs — arize.com](https://arize.com/docs/phoenix) — MEDIUM confidence (official docs)
- [Langfuse data model — langfuse.com](https://langfuse.com/docs/observability/data-model) — HIGH confidence (official OSS docs)
- [Langfuse observability overview — langfuse.com](https://langfuse.com/docs/observability/overview) — HIGH confidence (official OSS docs)
- [Braintrust observability tools — braintrust.dev](https://www.braintrust.dev/articles/best-ai-observability-tools-2026) — LOW confidence (vendor-written comparison)
- [LLM observability best practices 2025 — getmaxim.ai](https://www.getmaxim.ai/articles/llm-observability-best-practices-for-2025/) — LOW confidence (third-party blog)
- [Odoo bus.bus real-time communication — cybrosys.com](https://www.cybrosys.com/blog/how-to-setup-real-time-communication-in-odoo-using-bus-service) — MEDIUM confidence (Odoo ecosystem blog; pattern verified against known Odoo source structure)
- PROJECT.md — HIGH confidence (direct project specification, verified against enterprise `ai` module source)
- ai_debugger.md — HIGH confidence (detailed design spec derived from reading actual source code)

---

*Feature research for: AI/LLM agentic loop debugger (Odoo-native module)*
*Researched: 2026-02-20*
