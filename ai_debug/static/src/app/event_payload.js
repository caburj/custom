/** @odoo-module **/

export function normalizeTokens(tokens) {
    if (!tokens || typeof tokens !== "object" || Array.isArray(tokens)) {
        return null;
    }
    return {
        input: tokens?.input ?? 0,
        output: tokens?.output ?? 0,
        cache_read: tokens?.cached ?? tokens?.cache_read ?? 0,
        cache_write: tokens?.cache_write ?? 0,
        reasoning: tokens?.reasoning ?? 0,
        total: tokens?.total ?? 0,
    };
}

export function iterationMessages(payload) {
    return payload?.messages_sent
        ?? payload?.request_body?.messages
        ?? payload?.message_summary
        ?? [];
}

export function iterationTools(payload) {
    return payload?.tools ?? payload?.request_body?.tools ?? [];
}

export function extractRagContexts(messages) {
    const latestUserMessage = [...(messages || [])]
        .reverse()
        .find((message) => message?.role === "user");
    if (!latestUserMessage) {
        return [];
    }
    const contextPart = [...(latestUserMessage.content || [])]
        .reverse()
        .find((part) => (
            part?.type === "text"
            && typeof part.content?.data === "string"
            && part.content.data.trimStart().startsWith("<odoo_current_context>")
        ));
    if (!contextPart) {
        return [];
    }
    const contexts = [];
    const text = contextPart.content.data.trimStart();
    let cursor = 0;
    while (cursor < text.length) {
        const contextStart = text.indexOf("<odoo_current_context>", cursor);
        if (contextStart < 0) break;
        const contentStart = contextStart + "<odoo_current_context>".length;
        const closingTag = text.indexOf("</odoo_current_context>", contentStart);
        const contextEnd = closingTag < 0 ? text.length : closingTag;
        const context = text.slice(contentStart, contextEnd);
        const rag = context.match(
            /(?:^|\n)## RAG[ \t]*\n([\s\S]*?)(?=\n## (?:Date|User info|Current active companies|Current view|Current record data)[ \t]*\n|$)/
        );
        if (rag?.[1]?.trim()) {
            contexts.push(rag[1].trim());
        }
        cursor = closingTag < 0
            ? text.length
            : closingTag + "</odoo_current_context>".length;
    }
    return contexts;
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
