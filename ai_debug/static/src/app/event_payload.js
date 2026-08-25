/** @odoo-module **/

export function normalizeTokens(tokens) {
    return {
        input: tokens?.input ?? 0,
        output: tokens?.output ?? 0,
        cache_read: tokens?.cached ?? tokens?.cache_read ?? 0,
        cache_write: tokens?.cache_write ?? 0,
        reasoning: tokens?.reasoning ?? 0,
        total: tokens?.total ?? 0,
    };
}

export function extractMessageText(message) {
    if (typeof message?.content === "string") {
        return message.content;
    }
    if (Array.isArray(message?.content)) {
        return message.content
            .map((part) => {
                if (typeof part?.text === "string") {
                    return part.text;
                }
                if (part?.type === "text" && typeof part.content?.data === "string") {
                    return part.content.data;
                }
                return "";
            })
            .filter(Boolean)
            .join("\n");
    }
    if (Array.isArray(message?.parts)) {
        return message.parts
            .filter((part) => typeof part?.text === "string")
            .map((part) => part.text)
            .join("\n");
    }
    return "";
}

export function callbackCorrelation(payload) {
    return {
        exchange_uuid: payload.exchange_uuid ?? payload.trace_id ?? null,
        request_uuid: payload.request_uuid ?? payload.iteration_id ?? null,
        round_no: payload.round_no ?? payload.iteration_index ?? null,
        request_state: payload.request_state ?? payload.state ?? null,
    };
}
