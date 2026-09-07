import { setupChatHub, start, startServer } from "@mail/../tests/mail_test_helpers";
import { before, beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    Command,
    getService,
    MockServer,
    mockService,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";
import { defineAIModels } from "@ai/../tests/ai_test_helpers";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");
defineAIModels();

function withAITool(name, handler) {
    before(() => {
        const tools = registry.category("ai.client_tools");
        tools.add(name, handler);
        return () => tools.remove(name);
    });
}

let channelId;
let sessionId;
beforeEach(async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Agent Partner" });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "Agent Partner",
        partner_id: partnerId,
    });
    channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "ai_chat",
        ai_agent_id: aiAgentId,
    });
    sessionId = pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "waiting_user",
    });
});

test("Callback bus dispatches a one-way show_view command", async () => {
    let receivedAction;
    let receivedOptions;
    mockService("action", {
        async doAction(action, options) {
            receivedAction = action;
            receivedOptions = options;
            expect.step("show_view");
        },
    });
    setupChatHub({ opened: [channelId] });
    await start();

    const [channel] = MockServer.env["discuss.channel"].read(channelId);
    MockServer.env["bus.bus"]._sendone(channel, "ai.session/client_tools", {
        channel_id: channelId,
        commands: [{
            name: "show_view",
            oneway: true,
            params: {
                action: {
                    type: "ir.actions.act_window",
                    name: "Customers",
                    res_model: "res.partner",
                    views: [[false, "list"]],
                    help: "<p>No customers</p>",
                },
                options: { viewType: "list" },
            },
        }],
    });

    await expect.waitForSteps(["show_view"]);
    expect(receivedAction.res_model).toBe("res.partner");
    expect(String(receivedAction.help).includes("No customers")).toBe(true);
    expect(receivedOptions.viewType).toBe("list");
});

test("Persisted blocking client command resumes a falsy result once", async () => {
    const responseDeferred = Promise.withResolvers();
    withAITool("callback_falsy_value", async () => {
        expect.step("client tool");
        return false;
    });
    onRpc("/ai/generate_response", () => {
        throw new Error("Callback client tools must not use the synchronous response route");
    });
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params } = await request.json();
        expect(params.response).toEqual({ kind: "client_result", value: false });
        expect(params.resume_token).toBe("blocking-client-token");
        expect("current_view_info" in params).toBe(true);
        expect.step("result resumed");
        return await responseDeferred.promise;
    });
    setupChatHub({ opened: [channelId] });
    await start();
    const session = getService("mail.store")["ai.session"].get(sessionId);

    session.clientToolRequest = {
        name: "callback_falsy_value",
        params: {},
        resumeToken: "blocking-client-token",
    };
    session.responseState = "waiting_client";
    session.syncAiSessionState();

    expect(session.channel_id.isAiGenerating).toBe(true);

    await expect.waitForSteps(["client tool", "result resumed"]);
    responseDeferred.resolve({ responseState: "running" });
    await responseDeferred.promise;
    expect.verifySteps([]);
});

test("Non-consumed blocking client acknowledgement keeps the command for retry", async () => {
    let execution = 0;
    let resume = 0;
    withAITool("callback_retry", async () => {
        expect.step(`client tool ${++execution}`);
        return "done";
    });
    onRpc("/ai/resume_pending_interaction", () => {
        expect.step(`resume ${++resume}`);
        return resume === 1
            ? { responseState: "waiting_client", interactionConsumed: false }
            : { responseState: "running" };
    });
    setupChatHub({ opened: [channelId] });
    await start();
    const session = getService("mail.store")["ai.session"].get(sessionId);

    session.clientToolRequest = {
        name: "callback_retry",
        params: {},
        resumeToken: "blocking-client-retry-token",
    };

    await expect.waitForSteps(["client tool 1", "resume 1"]);
    await animationFrame();
    expect(session.clientToolRequest.resumeToken).toBe("blocking-client-retry-token");

    await session.processPendingClientTool();

    await expect.waitForSteps(["client tool 2", "resume 2"]);
    expect(session.clientToolRequest).toBe(false);
});

test("Persisted blocking client command resumes an execution error", async () => {
    withAITool("callback_client_failure", async () => {
        expect.step("client tool failed");
        throw new Error("Browser command failed");
    });
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params } = await request.json();
        expect(params.response).toEqual({
            kind: "client_error",
            value: "Browser command failed",
        });
        expect.step("error resumed");
        return { responseState: "running" };
    });
    setupChatHub({ opened: [channelId] });
    await start();
    const session = getService("mail.store")["ai.session"].get(sessionId);

    session.clientToolRequest = {
        name: "callback_client_failure",
        params: {},
        resumeToken: "blocking-client-error-token",
    };

    await expect.waitForSteps(["client tool failed", "error resumed"]);
});

test("A client without the handler leaves the blocking command pending", async () => {
    onRpc("/ai/resume_pending_interaction", () => {
        expect.step("unexpected resume");
    });
    setupChatHub({ opened: [channelId] });
    await start();
    const session = getService("mail.store")["ai.session"].get(sessionId);

    session.clientToolRequest = {
        name: "unavailable_livechat_tool",
        params: {},
        resumeToken: "unavailable-client-tool-token",
    };

    expect(Boolean(session.channel_id.thread)).toBe(true);
    await session.processPendingClientTool();
    expect(session._runningClientToolToken).toBe(undefined);
    expect(session.clientToolRequest.resumeToken).toBe("unavailable-client-tool-token");
    expect.verifySteps([]);
});
