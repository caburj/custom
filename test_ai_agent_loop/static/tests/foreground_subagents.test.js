import { defineAIModels } from "@ai/../tests/ai_test_helpers";
import { click, contains, insertText, setupChatHub, start, startServer } from "@mail/../tests/mail_test_helpers";
import { before, describe, expect, test } from "@odoo/hoot";
import { press, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Command, getService, onRpc, serverState } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");
defineAIModels();
const INPUT = ".o_ai_user_input_request";

function question(label, token) {
    return {
        type: "question",
        body: ["markup", `<p>${label}</p>`],
        choices: [{ label: "Use the suggestion", value: "suggestion" }],
        allowFreeText: true,
        requestUuid: `request-${token}`,
        resumeToken: token,
    };
}

async function startForeground() {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Root Agent" });
    const agentId = pyEnv["ai.agent"].create({ name: "Root Agent", partner_id: partnerId });
    const childAgentId = pyEnv["ai.agent"].create({ name: "Research Assistant" });
    const channelId = pyEnv["discuss.channel"].create({
        channel_type: "ai_chat",
        ai_agent_id: agentId,
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
    });
    const rootId = pyEnv["ai.session"].create({
        channel_id: channelId, agent_id: agentId, response_state: "running",
    });
    const childIds = [0, 1].map(() => pyEnv["ai.session"].create({
        channel_id: channelId, agent_id: childAgentId,
        parent_session_id: rootId, response_state: "running",
    }));
    pyEnv["mail.message"].create({
        author_id: serverState.partnerId, body: "Research this for me.",
        model: "discuss.channel", res_id: channelId, message_type: "comment",
    });
    setupChatHub({ opened: [channelId] });
    await start();
    const sessions = getService("mail.store")["ai.session"];
    const root = sessions.get(rootId);
    const children = childIds.map((id) => sessions.get(id));
    return { root, children, channel: root.channel_id };
}

test("a visible descendant question survives a sibling arrival and answers the exact source", async () => {
    const { root, children: [older, first], channel } = await startForeground();
    channel.ai_session_ids = [first, older, root];
    expect(channel.aiRootSession).toBe(root);
    first.userInputRequest = question("First child question", "first");
    first.responseState = "waiting_user";
    await contains(`${INPUT} p`, { text: "First child question" });
    await contains(INPUT, { text: "Research Assistant" });
    await insertText(`${INPUT} input`, "Keep this draft");

    older.userInputRequest = question("Waiting sibling question", "older");
    older.responseState = "waiting_user";
    await animationFrame();
    await contains(INPUT, { count: 1 });
    expect(queryOne(`${INPUT} input`).value).toBe("Keep this draft");
    expect(channel.aiInputSession).toBe(first);
    await contains(`.o-mail-Message ${INPUT}`, { count: 0 });
    await contains(`${INPUT} p`, { text: "First child question" });

    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params } = await request.json();
        expect(params.channel_id).toBe(channel.id);
        expect(params.session_id).toBe(first.id);
        expect(params.request_uuid).toBe("request-first");
        expect(params.resume_token).toBe("first");
        expect(params.response).toEqual({ kind: "question", value: ["Keep this draft"] });
        expect.step("first child answered");
        return { responseState: "running" };
    });
    await press("Enter");
    await expect.waitForSteps(["first child answered"]);
    await contains(`${INPUT} p`, { text: "Waiting sibling question" });
    expect(queryOne(`${INPUT} input`).value).toBe("");
    expect(channel.aiInputSession).toBe(older);
    expect(older.userInputRequest.resumeToken).toBe("older");
    expect(root.responseState).toBe("running");
    expect(channel.isAiGenerating).toBe(true);
});

test("a rotated source request resets its form and survives the previous acknowledgement", async () => {
    const { children: [, child] } = await startForeground();
    const acknowledgement = Promise.withResolvers();
    onRpc("/ai/resume_pending_interaction", () => acknowledgement.promise);
    child.userInputRequest = question("Original question", "original");
    await contains(INPUT);
    await insertText(`${INPUT} input`, "Original draft");
    await press("Enter");
    child.userInputRequest = question("Next question", "next");
    await contains(`${INPUT} p`, { text: "Next question" });
    expect(queryOne(`${INPUT} input`).value).toBe("");
    acknowledgement.resolve({ responseState: "waiting_user" });
    await animationFrame();
    expect(child.userInputRequest.resumeToken).toBe("next");
    await contains(`${INPUT} button:contains('Use the suggestion'):enabled`);
});

test("a descendant client effect uses the root browser and updates only its source", async () => {
    const tools = registry.category("ai.client_tools");
    let channel;
    before(() => {
        tools.add("foreground_client_effect", (thread) => {
            expect(thread).toBe(channel.thread);
            expect.step("root browser effect");
            return false;
        });
        return () => tools.remove("foreground_client_effect");
    });
    const foreground = await startForeground();
    channel = foreground.channel;
    const { root, children: [child, sibling] } = foreground;
    sibling.userInputRequest = question("Sibling still waiting", "sibling");
    sibling.responseState = "waiting_user";
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params } = await request.json();
        expect(params.session_id).toBe(child.id);
        expect(params.request_uuid).toBe("client-request");
        expect(params.resume_token).toBe("client-token");
        expect(params.response).toEqual({ kind: "client_result", value: false });
        expect.step("child result submitted");
        return { responseState: "idle" };
    });
    child.clientToolRequest = {
        name: "foreground_client_effect", params: {},
        requestUuid: "client-request", resumeToken: "client-token",
    };
    await expect.waitForSteps(["root browser effect", "child result submitted"]);
    await animationFrame();
    expect(child.responseState).toBe("idle");
    expect(child.clientToolRequest).toBe(false);
    expect(root.responseState).toBe("running");
    expect(channel.isAiGenerating).toBe(true);
    await contains(`${INPUT} p`, { text: "Sibling still waiting" });
});
