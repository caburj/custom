import { expect, test } from "@odoo/hoot";

import {
    callbackCorrelation,
    extractMessageText,
    normalizeTokens,
} from "@ai_debug/app/event_payload";

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
    expect(normalizeTokens()).toEqual({
        input: 0,
        output: 0,
        cache_read: 0,
        cache_write: 0,
        reasoning: 0,
        total: 0,
    });
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
