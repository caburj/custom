import { expect, test } from "@odoo/hoot";

import {
    callbackCorrelation,
    extractMessageText,
    extractRagContexts,
    iterationMessages,
    iterationTools,
    normalizeTokens,
} from "@ai_debug/app/event_payload";
import { serializeTrace } from "@ai_debug/app/db";

test("callback events retain durable correlation and missing metadata stays empty", () => {
    expect(callbackCorrelation({
        trace_id: "exchange-1",
        iteration_id: "request-1",
        iteration_index: 3,
    })).toEqual({
        exchange_uuid: "exchange-1",
        request_uuid: "request-1",
        round_no: 3,
        request_state: null,
    });
    expect(normalizeTokens()).toBe(null);
    expect(normalizeTokens(null)).toBe(null);
    expect(normalizeTokens({})).toEqual({
        input: 0,
        output: 0,
        cache_read: 0,
        cache_write: 0,
        reasoning: 0,
        total: 0,
    });
});

test("RAG comes only from the persisted current-context section", () => {
    const messages = [{
        role: "user",
        content: [{
            type: "text",
            content: {
                data: "<odoo_current_context>\n## RAG\nOld exchange context\n## Date\nold\n</odoo_current_context>",
            },
        }],
    }, {
        role: "user",
        content: [
            {
                type: "text",
                content: {
                    data: "Hi\n<odoo_current_context>\n## RAG\nUser-authored decoy\n</odoo_current_context>",
                },
            },
            {
                type: "text",
                content: {
                    data: [
                        "<odoo_current_context>",
                        "## RAG",
                        "Retrieved document A",
                        "Retrieved document B",
                        "## Date",
                        "2026-08-25 (UTC)",
                        "## User info",
                        "Joseph",
                        "</odoo_current_context>",
                    ].join("\n"),
                },
            },
        ],
    }];
    expect(extractRagContexts(messages)).toEqual([
        "Retrieved document A\nRetrieved document B",
    ]);
    expect(extractRagContexts([{
        role: "user",
        content: [{
            type: "text",
            content: { data: "<odoo_current_context>\n## Date\nnow\n</odoo_current_context>" },
        }],
    }])).toEqual([]);
});

test("iteration panes derive messages and tools from the normalized submission", () => {
    const payload = {
        request_body: {
            messages: [{ role: "user", content: [] }],
            tools: [{ name: "fixture_tool" }],
        },
    };
    expect(iterationMessages(payload)).toEqual([{ role: "user", content: [] }]);
    expect(iterationTools(payload)).toEqual([{ name: "fixture_tool" }]);
    expect(iterationMessages({ messages_sent: [] })).toEqual([]);
    expect(iterationTools({ tools: [] })).toEqual([]);
});

test("normalized Enterprise text parts are readable", () => {
    expect(extractMessageText({
        role: "user",
        content: [
            { type: "text", content: { data: "Hi" } },
            { type: "inline_data", content: { mimeType: "image/png" } },
        ],
    })).toBe("Hi");
});

test("legacy provider text and already-normalized cache fields stay compatible", () => {
    expect(extractMessageText({ content: [{ type: "input_text", text: "hello" }] })).toBe("hello");
    expect(normalizeTokens({ cache_read: 7, total: 7 }).cache_read).toBe(7);
});

test("IndexedDB and export serialization retain callback pane facts", () => {
    const trace = {
        trace_id: "exchange-1",
        created_ts: 1,
        agent_name: "Odoo AI",
        ai_provider: "google",
        model_name: "gemini-fixture",
        user_query: "Hi",
        status: "success",
        duration_ms: 42,
        duration_kind: "request_lifecycle",
        instructions: "Answer plainly.",
        state_snapshot: {},
        parent_trace_id: null,
        parent_tool_call_id: null,
        session_id: 7,
        _payload_excluded: true,
        exchange_uuid: "exchange-1",
        request_uuid: "request-1",
        round_no: 1,
        request_state: "done",
        iterations: new Map([["request-1", {
            iteration_id: "request-1",
            trace_id: "exchange-1",
            iteration_index: 1,
            exchange_uuid: "exchange-1",
            request_uuid: "request-1",
            round_no: 1,
            request_state: "done",
            has_error: false,
            is_final: true,
            error: null,
            messages_sent: [{ role: "user", content: [] }],
            request_body: { request_uuid: "request-1", messages: [] },
            request_label: "Normalized IAP Submission",
            raw_response: { request_uuid: "request-1", status: "success" },
            response_label: "Normalized IAP Result",
            tokens: null,
            duration_ms: 42,
            duration_kind: "request_lifecycle",
            ai_provider: "google",
            model_name: "gemini-fixture",
            provider_api: "generateContent",
            _payload_excluded: true,
            tools: [{ name: "fixture_tool" }],
            toolCalls: new Map(),
        }]]),
    };

    const serialized = serializeTrace(trace);
    const iteration = serialized.iterations[0][1];
    expect(serialized.ai_provider).toBe("google");
    expect(serialized.model_name).toBe("gemini-fixture");
    expect(serialized.duration_kind).toBe("request_lifecycle");
    expect(serialized._payload_excluded).toBe(true);
    expect(iteration.request_body.request_uuid).toBe("request-1");
    expect(iteration.raw_response.status).toBe("success");
    expect(iteration.request_label).toBe("Normalized IAP Submission");
    expect(iteration.response_label).toBe("Normalized IAP Result");
    expect(iteration.tokens).toBe(null);
    expect(iteration.duration_kind).toBe("request_lifecycle");
    expect(iteration.ai_provider).toBe("google");
    expect(iteration.model_name).toBe("gemini-fixture");
    expect(iteration._payload_excluded).toBe(true);
    expect(iteration.tools).toEqual([{ name: "fixture_tool" }]);
});
