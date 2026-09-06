import "@ai/../tests/mock_server/controllers/messaging_menu";
import "@ai_app/../tests/mock_server/controllers/messaging_menu";
import { defineLivechatModels, loadDefaultEmbedConfig } from "@im_livechat/../tests/livechat_test_helpers";
import { expirableStorage } from "@im_livechat/core/common/expirable_storage";
import { click, contains, insertText, setupChatHub, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { Command, getService, onRpc, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineLivechatModels();

test("an embedded guest answers a source-owned descendant prompt while the root stays busy", async () => {
    const pyEnv = await startServer();
    const livechatChannelId = await loadDefaultEmbedConfig();
    const guestId = pyEnv["mail.guest"].create({ name: "Visitor" });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ guest_id: guestId }),
        ],
        channel_type: "livechat", livechat_channel_id: livechatChannelId,
    });
    pyEnv["mail.message"].create({
        author_guest_id: guestId, body: "Help me choose.", model: "discuss.channel",
        res_id: channelId, message_type: "comment",
    });
    const agentMessageId = pyEnv["mail.message"].create({
        author_id: serverState.partnerId, body: "I have a question for you.",
        model: "discuss.channel", res_id: channelId, message_type: "comment",
    });
    expirableStorage.setItem("im_livechat.saved_state", JSON.stringify({
        store: { "discuss.channel": [{ id: channelId }] },
        persisted: true, livechatUserId: serverState.publicUserId,
    }));
    setupChatHub({ opened: [channelId] });
    await start({ authenticateAs: { ...pyEnv["mail.guest"].read(guestId)[0], _name: "mail.guest" } });
    const store = getService("mail.store");
    expect(store.self_guest.id).toBe(guestId);
    store.insert({
        "ai.agent": [{ id: 50, name: "Root Agent", partner_id: serverState.partnerId },
            { id: 51, name: "Colour Assistant" }],
        "discuss.channel": [{ id: channelId, ai_agent_id: 50 }],
        "ai.session": [
            { id: 100, channel_id: channelId, agent_id: 50, responseState: "running" },
            { id: 101, channel_id: channelId, agent_id: 51, parent_session_id: 100,
                responseState: "waiting_user", userInputRequest: {
                    type: "question", body: ["markup", "<p>Choose a colour.</p>"],
                    choices: [{ label: "Red", value: "red" }],
                    resumeToken: "guest-child-token",
                } },
        ],
    });
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params } = await request.json();
        expect(params.channel_id).toBe(channelId);
        expect(params.session_id).toBe(101);
        expect(params.request_uuid).toBe(undefined);
        expect(params.resume_token).toBe("guest-child-token");
        expect(params.response).toEqual({ kind: "question", value: ["red"] });
        expect.step("guest answered child");
        return { responseState: "idle" };
    });
    onRpc("/mail/message/post", () => {
        throw new Error("Foreground work must keep the guest composer busy");
    });
    await contains(".o_ai_user_input_request", { count: 1, text: "Colour Assistant" });
    await contains(".o_ai_user_input_request p", { text: "Choose a colour." });
    expect(store["mail.message"].get(agentMessageId).hasActions).toBe(false);
    await insertText(".o-mail-Composer-input", "Another root request");
    await contains(".o-mail-Composer button[name='send-message']:disabled");
    await press("Enter");
    await click(".o_ai_user_input_request button:contains('Red')");
    await expect.waitForSteps(["guest answered child"]);
    await contains(".o_ai_user_input_request", { count: 0 });
    expect(store["mail.message"].get(agentMessageId).hasActions).toBe(true);
    expect(store["ai.session"].get(100).responseState).toBe("running");
    await contains(".o-mail-Composer button[name='send-message']:disabled");
});
