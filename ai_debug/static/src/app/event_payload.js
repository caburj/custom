/** @odoo-module **/

/**
 * @param {{input: number, cached_input: number, output: {text: number, image: number}, thought: number, web_search?: number}} usage
 * @param {string} provider
 */
export function normalizeUsage(usage, provider) {
    // Google reports thoughts separately; OpenAI includes them in output.text.
    const output =
        usage.output.text + usage.output.image + (provider === "google" ? usage.thought : 0);
    return {
        input: usage.input,
        output,
        cache_read: usage.cached_input,
        reasoning: usage.thought,
        output_text: usage.output.text - (provider === "openai" ? usage.thought : 0),
        output_image: usage.output.image,
        web_search: usage.web_search ?? null,
        total: usage.input + output,
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
