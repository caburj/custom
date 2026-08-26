import {
    contains,
    insertText,
    setupChatHub,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";

import {
    Command,
    getService,
    onRpc,
    patchWithCleanup,
    serverState,
    withUser,
} from "@web/../tests/web_test_helpers";
import { rpc } from "@web/core/network/rpc";
import { defineAIModels } from "@ai/../tests/ai_test_helpers";
import { DiscussChannel as AIDiscussChannel } from "@ai/../tests/mock_server/mock_models/discuss_channel";

describe.current.tags("desktop");
defineAIModels();

test("running acknowledgement blocks new input until Store delivers the final state", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Agent Partner" });
    const agentUserId = pyEnv["res.users"].create({ partner_id: partnerId });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "Agent Partner",
        partner_id: partnerId,
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "ai_chat",
        ai_agent_id: aiAgentId,
    });
    const sessionId = pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "idle",
    });
    onRpc("/ai/start_session_advance", () => {
        expect.step("start session advance");
        return { responseState: "running" };
    });
    onRpc("/ai/generate_response", () => {
        throw new Error("AI chat must not use the synchronous response route");
    });
    setupChatHub({ opened: [channelId] });
    await start();
    await contains(".o-mail-ChatWindow");
    await insertText(".o-mail-ChatWindow .o-mail-Composer-input", "First message");
    await press("Enter");
    await expect.waitForSteps(["start session advance"]);

    const store = getService("mail.store");
    const session = store["ai.session"].get(sessionId);
    await insertText(".o-mail-ChatWindow .o-mail-Composer-input", "Duplicate");
    await contains(".o-mail-Composer button[name='send-message']:disabled");
    await contains(".o-mail-ChatWindow-typing", { text: "Thinking" });
    await press("Enter");
    expect.verifySteps([]);

    await withUser(agentUserId, () =>
        rpc("/mail/message/post", {
            post_data: { body: "Agent reply", message_type: "comment" },
            thread_id: channelId,
            thread_model: "discuss.channel",
        })
    );
    session.responseState = "idle";
    session.syncAiSessionState();

    await contains(".o-mail-ChatWindow", { text: "Agent reply" });
    await contains(".o-mail-Composer button[name='send-message']:enabled");
    await contains(".o-mail-ChatWindow-typing", { count: 0 });
});

test("livechat starts a callback-driven response", async () => {
    patchWithCleanup(AIDiscussChannel.prototype, {
        _ai_agent_channel_types() {
            return ["ai_chat", "livechat"];
        },
    });
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Agent Partner" });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "Agent Partner",
        partner_id: partnerId,
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "livechat",
        ai_agent_id: aiAgentId,
    });
    onRpc("/ai/start_session_advance", async (request) => {
        const { params } = await request.json();
        expect(params.mail_message_id).toBeOfType("number");
        expect.step("start session advance");
        return { responseState: "running" };
    });
    onRpc("/ai/generate_response", () => {
        throw new Error("Livechat must not use the synchronous response route");
    });
    setupChatHub({ opened: [channelId] });
    await start();

    const thread = getService("mail.store")["mail.thread"].get({
        id: channelId,
        model: "discuss.channel",
    });
    expect(thread.channel.ai_session_ids).toHaveLength(0);
    await thread.post("Hello from livechat");

    await expect.waitForSteps(["start session advance"]);
    await contains(".o-mail-ChatWindow-typing");

    const sessionId = pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "idle",
    });
    getService("mail.store").insert({
        "ai.session": [{ id: sessionId, channel_id: channelId, responseState: "idle" }],
    });

    expect(thread.channel.ai_session_ids).toHaveLength(1);
    await contains(".o-mail-ChatWindow-typing", { count: 0 });
});

test("session advance starts naming an initially empty AI chat", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Agent Partner" });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "Agent Partner",
        partner_id: partnerId,
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "ai_chat",
        ai_agent_id: aiAgentId,
    });
    pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "idle",
    });
    onRpc("/ai/start_session_advance", () => {
        expect.step("start session advance");
        return {
            responseState: "running",
        };
    });
    onRpc("/ai/compute_channel_name", () => {
        expect.step("compute_channel_name");
        return "Named callback chat";
    });
    setupChatHub({ opened: [channelId] });
    await start();
    await contains(".o-mail-ChatWindow");

    await insertText(".o-mail-ChatWindow .o-mail-Composer-input", "Name this chat");
    await press("Enter");

    await expect.waitForSteps(["start session advance", "compute_channel_name"]);
});

test("definitive session-advance error releases the optimistic submission latch", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Agent Partner" });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "Agent Partner",
        partner_id: partnerId,
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "ai_chat",
        ai_agent_id: aiAgentId,
    });
    pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "idle",
    });
    onRpc("/ai/start_session_advance", () => {
        throw new Error("Definitive session-advance failure");
    });
    setupChatHub({ opened: [channelId] });
    await start();

    const channel = getService("mail.store")["discuss.channel"].get(channelId);
    channel.isAiSubmitting = true;
    channel.isAiGenerating = true;
    await expect(
        channel.requestAiSessionAdvance("/ai/start_session_advance", {
            mail_message_id: 1,
        })
    ).rejects.toThrow("Definitive session-advance failure");

    expect(channel.isAiSubmitting).toBe(false);
    expect(channel.isAiGenerating).toBe(false);
});

test("session-advance transport failure releases the optimistic submission latch", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Agent Partner" });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "Agent Partner",
        partner_id: partnerId,
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "ai_chat",
        ai_agent_id: aiAgentId,
    });
    pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "idle",
    });
    setupChatHub({ opened: [channelId] });
    await start();
    patchWithCleanup(rpc, {
        _rpc: async () => {
            throw new TypeError("Network error");
        },
    });

    const channel = getService("mail.store")["discuss.channel"].get(channelId);
    channel.isAiSubmitting = true;
    channel.isAiGenerating = true;

    await expect(
        channel.requestAiSessionAdvance("/ai/start_session_advance", {
            mail_message_id: 1,
        })
    ).rejects.toThrow("Network error");

    expect(channel.isAiSubmitting).toBe(false);
    expect(channel.isAiGenerating).toBe(false);
});
