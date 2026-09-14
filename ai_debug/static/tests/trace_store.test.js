import { expect, test } from "@odoo/hoot";
import { reduceTraceEvent, parentTool, collectSidebarNodes, hydrateTrace } from "@ai_debug/app/trace_store";
import { serializeTrace } from "@ai_debug/app/db";

function event(traces, type, values = {}) {
    return reduceTraceEvent(traces, { type, trace_id: "parent", ...values });
}
function iteration(traces, values = {}) {
    return event(traces, "iteration", { iteration_id: "r1", request_uuid: "r1", round_no: 1, phase: "prepared", ...values });
}
function tool(traces, type = "tool_call_started", values = {}) {
    return event(traces, type, { iteration_id: "r1", request_uuid: "r1", round_no: 1,
        tool_call_id: "r1-call", call_id: "call", tool_name: "delegate", ...values });
}
function child(traces, values = {}) {
    return event(traces, "new_trace", { trace_id: "child", session_id: 2,
        parent_trace_id: "parent", parent_session_id: 1,
        parent_request_uuid: "r1", parent_tool_call_id: "r1-call", ...values });
}

test("prepared iteration is updated in place without discarding tools or received result on replay", () => {
    const traces = new Map();
    iteration(traces, { request_body: { messages: ["submitted"], tools: ["delegate"] } });
    tool(traces);
    const iter = traces.get("parent").iterations.get("r1");
    iteration(traces, { phase: "result_received", raw_response: { status: "success" } });
    iteration(traces, { raw_response: null });
    expect(traces.get("parent").iterations.size).toBe(1);
    expect(iter.toolCalls.size).toBe(1);
    expect(iter.raw_response).toEqual({ status: "success" });
    expect(iter.phase).toBe("result_received");
    expect(iter.messages_sent).toEqual(["submitted"]);
    expect(iter.tokens).toBe(null);
    expect(iter.duration_ms).toBe(null);
});

test("child updates remain captured and visible before parent arrives, then nest on the exact tool", () => {
    const traces = new Map();
    const captured = child(traces);
    iteration(traces, { trace_id: "child", raw_response: { status: "success" }, phase: "result_received" });
    event(traces, "loop_end", { trace_id: "child", phase: "child_settled", termination_reason: "success" });
    expect(collectSidebarNodes(traces)[0].id).toBe("child");
    expect(parentTool(traces, captured)).toBe(null);
    event(traces, "new_trace", { session_id: 1 });
    tool(traces);
    expect(parentTool(traces, captured).tc.tool_call_id).toBe("r1-call");
    const nodes = collectSidebarNodes(traces).filter((node) => node.type === "trace");
    expect(nodes.map((node) => [node.id, node.depth])).toEqual([["parent", 0], ["child", 1]]);
    expect(captured.status).toBe("success");
    expect(captured.iterations.get("r1").raw_response).toEqual({ status: "success" });
});

test("durable linkage never falls back to a reused raw call ID in another round or session", () => {
    const traces = new Map();
    event(traces, "new_trace", { session_id: 1 });
    tool(traces);
    tool(traces, "tool_call_started", { iteration_id: "r2", request_uuid: "r2", round_no: 2, tool_call_id: "r2-call" });
    const captured = child(traces, { parent_request_uuid: "r2", parent_tool_call_id: "r2-call" });
    expect(parentTool(traces, captured).iteration.iteration_id).toBe("r2");
    expect(parentTool(traces, { ...captured, parent_tool_call_id: "call" })).toBe(null);
    expect(parentTool(traces, { ...captured, parent_session_id: 99 })).toBe(null);
    expect(parentTool(traces, { ...captured, parent_request_uuid: "missing" })).toBe(null);
    const legacy = { parent_trace_id: "parent", parent_tool_call_id: "call" };
    expect(parentTool(traces, legacy).iteration.iteration_id).toBe("r1");
});

test("completion before starts creates partial ancestors and late starts never regress completion", () => {
    const traces = new Map();
    tool(traces, "tool_call_completed", { result: "done", success: true, status: "completed" });
    const trace = traces.get("parent");
    const tc = trace.iterations.get("r1").toolCalls.get("r1-call");
    expect(trace.partial).toBe(true);
    tool(traces);
    tool(traces, "tool_call_completed", { triggered_confirmation: true, status: "waiting_confirmation" });
    expect(tc.status).toBe("completed");
    expect(tc.result).toBe("done");
    event(traces, "loop_end", { phase: "completed", termination_reason: "success" });
    event(traces, "new_trace", { agent_name: "Parent", request_state: "waiting_model" });
    expect(trace.partial).toBe(false);
    expect(trace.status).toBe("success");
    expect(trace.phase).toBe("completed");
});

test("confirmation remains pending until completion and keeps confirmation context", () => {
    const traces = new Map();
    tool(traces, "tool_call_completed", { status: "waiting_confirmation", triggered_confirmation: true,
        confirmation_message: "Continue?", success: true });
    const tc = traces.get("parent").iterations.get("r1").toolCalls.get("r1-call");
    expect(tc.status).toBe("waiting_confirmation");
    tool(traces);
    expect(tc.status).toBe("waiting_confirmation");
    tool(traces, "tool_call_completed", { status: "completed", result: "accepted", success: true });
    expect(tc.status).toBe("completed");
    expect(tc.triggered_confirmation).toBe(true);
    expect(tc.confirmation_message).toBe("Continue?");
});

test("old round application updates its tool without regressing the next prepared request", () => {
    const traces = new Map();
    iteration(traces);
    iteration(traces, { iteration_id: "r2", request_uuid: "r2", round_no: 2 });
    event(traces, "request_state", { iteration_id: "r1", request_uuid: "r1", round_no: 1,
        phase: "child_applied", tool_call_id: "r1-call", child_session_id: 2, child_request_uuid: "child-r1" });
    const trace = traces.get("parent");
    expect(trace.request_uuid).toBe("r2");
    expect(trace.round_no).toBe(2);
    expect(trace.phase).toBe("prepared");
    const tc = trace.iterations.get("r1").toolCalls.get("r1-call");
    expect(tc.child_phase).toBe("child_applied");
    expect(tc.child_session_id).toBe(2);
    expect(tc.child_request_uuid).toBe("child-r1");
});

test("refresh and export retain active phases, helper identity and unresolved links", () => {
    const traces = new Map();
    const trace = child(traces, { trace_kind: "web_search", trace_label: "Web Search" });
    tool(traces, "tool_call_completed", { trace_id: "child", status: "waiting_confirmation", triggered_confirmation: true });
    event(traces, "request_state", { trace_id: "child", iteration_id: "r1", request_uuid: "r1", round_no: 1,
        phase: "result_consumed", state: "waiting_interaction", request_phase: "submitted" });
    const record = JSON.parse(JSON.stringify(serializeTrace(trace)));
    const restored = hydrateTrace(record);
    expect(restored.status).toBe("running");
    expect(restored.phase).toBe("result_consumed");
    expect(restored.parent_request_uuid).toBe("r1");
    expect(restored.parent_session_id).toBe(1);
    expect(restored.trace_label).toBe("Web Search");
    expect(restored.iterations.get("r1").toolCalls.get("r1-call").status).toBe("waiting_confirmation");
    const reloaded = new Map([["child", restored]]);
    expect(collectSidebarNodes(reloaded).map((node) => node.id)).toEqual(["child"]);
    event(reloaded, "loop_end", { trace_id: "child", phase: "child_settled", termination_reason: "success",
        exchange_result: { status: "completed", message: "answer", attachments: [7], sources: ["source"] },
        final_output: { content: [{ type: "text", content: { data: "answer" } }] } });
    const exported = serializeTrace(restored);
    expect(exported.exchange_result.attachments).toEqual([7]);
    expect(exported.final_output.content[0].content.data).toBe("answer");
    expect(exported.phase).toBe("child_settled");
    expect(exported.termination_reason).toBe("success");
});

test("a late lower phase cannot replace consumed state and a new request can start after it", () => {
    const traces = new Map();
    iteration(traces);
    event(traces, "request_state", { iteration_id: "r1", request_uuid: "r1", round_no: 1,
        phase: "result_consumed", state: "waiting_subagents" });
    event(traces, "request_state", { iteration_id: "r1", request_uuid: "r1", round_no: 1,
        phase: "submitted", state: "waiting_model" });
    expect(traces.get("parent").request_state).toBe("waiting_subagents");
    tool(traces, "tool_call_started", { iteration_id: "r2", request_uuid: "r2", round_no: 2, tool_call_id: "r2-call" });
    iteration(traces, { iteration_id: "r2", request_uuid: "r2", round_no: 2, request_state: "waiting_model" });
    expect(traces.get("parent").phase).toBe("prepared");
    expect(traces.get("parent").request_state).toBe("waiting_model");
});


test("child application does not freeze the parent interaction phase", () => {
    const traces = new Map();
    const state = { request_uuid: "r1", iteration_id: "r1", round_no: 1, phase: "result_consumed" };
    event(traces, "request_state", { ...state, state: "waiting_answer" });
    tool(traces, "request_state", { phase: "child_applied", state: "waiting_answer" });
    event(traces, "request_state", { ...state, state: "waiting_confirmation" });
    expect(traces.get("parent").request_state).toBe("waiting_confirmation");
    expect(traces.get("parent").iterations.get("r1").request_state).toBe("waiting_confirmation");
});


test("thinking progress stays on its tool and survives persistence without completing it", () => {
    const traces = new Map();
    iteration(traces);
    tool(traces);
    tool(traces, "tool_call_progress", { tool_status: "Searching records" });
    tool(traces, "tool_call_progress", { summary: "Searched <records>" });
    const tc = traces.get("parent").iterations.get("r1").toolCalls.get("r1-call");
    expect(tc.status).toBe("running");
    expect(tc.result).toBe(null);
    tool(traces, "tool_call_completed", { result: "Business result", success: true });
    const restored = hydrateTrace(serializeTrace(traces.get("parent")));
    const saved = restored.iterations.get("r1").toolCalls.get("r1-call");
    expect(saved.tool_status).toBe("Searching records");
    expect(saved.summary).toBe("Searched <records>");
    expect(saved.result).toBe("Business result");
    expect(saved.status).toBe("completed");
});
