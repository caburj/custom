import {
    click,
    contains,
    setupChatHub,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";

import {
    Command,
    getService,
    mockService,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";
import { defineAIModels } from "@ai/../tests/ai_test_helpers";

describe.current.tags("desktop");
defineAIModels();

const INPUT_REQUEST_SELECTOR = ".o_ai_user_input_request";
const REQUEST_UUID = "00000000-0000-4000-8000-000000000041";
const RESUME_TOKEN = "callback-resume-token";

async function startPendingConfirmation() {
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
    const sessionId = pyEnv["ai.session"].create({
        agent_id: aiAgentId,
        channel_id: channelId,
        response_state: "waiting_user",
        user_input_request: {
            allowFreeText: false,
            choices: [
                { label: "Yes, do it", value: "confirm_once" },
                { label: "Yes, always approve in this chat", value: "auto_confirm" },
                { label: "No, I want something else", value: "decline" },
            ],
            multiSelect: false,
            requestUuid: REQUEST_UUID,
            resumeToken: RESUME_TOKEN,
            type: "confirmation",
        },
    });
    pyEnv["mail.message"].create({
        author_id: partnerId,
        body: "Create the contact?",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
    });
    setupChatHub({ opened: [channelId] });
    await start();
    await contains(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it')`);
    return { channelId, sessionId };
}

test("server-hydrated durable confirmation submits only its token and choice once", async () => {
    const responseDeferred = Promise.withResolvers();
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params: body } = await request.json();
        expect(body.channel_id).toBeOfType("number");
        expect(body.request_uuid).toBe(REQUEST_UUID);
        expect(body.resume_token).toBe(RESUME_TOKEN);
        expect(body.response).toEqual({ value: "confirm_once" });
        expect("response_value" in body).toBe(false);
        expect("tool_name" in body).toBe(false);
        expect("tool_args" in body).toBe(false);
        expect("call_id" in body).toBe(false);
        expect("user_id" in body).toBe(false);
        expect.step("resume");
        return await responseDeferred.promise;
    });
    await startPendingConfirmation();

    const firstClick = click(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it')`);
    await contains(`${INPUT_REQUEST_SELECTOR} button:disabled`, { count: 3 });
    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it'):disabled`);
    await expect.waitForSteps(["resume"]);

    responseDeferred.resolve({
        request_uuid: "00000000-0000-4000-8000-000000000042",
        responseState: "running",
    });
    await firstClick;
    await contains(INPUT_REQUEST_SELECTOR, { count: 0 });
});

test("declining a durable confirmation uses the tokenized resume route", async () => {
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params: body } = await request.json();
        expect(body.request_uuid).toBe(REQUEST_UUID);
        expect(body.resume_token).toBe(RESUME_TOKEN);
        expect(body.response).toEqual({ value: "decline" });
        expect.step("decline resumed");
        return {
            request_uuid: REQUEST_UUID,
            responseState: "idle",
        };
    });
    await startPendingConfirmation();

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('No, I want something else')`);

    await expect.waitForSteps(["decline resumed"]);
    await contains(INPUT_REQUEST_SELECTOR, { count: 0 });
});

test("failed durable resume keeps the confirmation available", async () => {
    mockService("notification", {
        add(message, options) {
            expect(message).toBe("The confirmation was rejected");
            expect(options.type).toBe("danger");
            expect.step("failure shown");
        },
    });
    onRpc("/ai/resume_pending_interaction", () => {
        throw new Error("The confirmation was rejected");
    });
    await startPendingConfirmation();

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it')`);

    await expect.waitForSteps(["failure shown"]);
    await contains(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it'):enabled`);
});

test("non-consumed durable resume keeps the confirmation available for retry", async () => {
    let attempt = 0;
    onRpc("/ai/resume_pending_interaction", () => {
        attempt++;
        expect.step(`resume ${attempt}`);
        return attempt === 1
            ? {
                  request_uuid: REQUEST_UUID,
                  responseState: "waiting_user",
                  interactionConsumed: false,
              }
            : {
                  request_uuid: REQUEST_UUID,
                  responseState: "running",
              };
    });
    await startPendingConfirmation();

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it')`);

    await expect.waitForSteps(["resume 1"]);
    await contains(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it'):enabled`);

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it')`);

    await expect.waitForSteps(["resume 2"]);
    await contains(INPUT_REQUEST_SELECTOR, { count: 0 });
});

test("a rotated sequential confirmation survives the stale resume acknowledgement", async () => {
    const responseDeferred = Promise.withResolvers();
    onRpc("/ai/resume_pending_interaction", () => responseDeferred.promise);
    const { sessionId } = await startPendingConfirmation();

    const firstClick = click(`${INPUT_REQUEST_SELECTOR} button:contains('Yes, do it')`);
    const session = getService("mail.store")["ai.session"].get(sessionId);
    session.userInputRequest = {
        allowFreeText: false,
        choices: [
            { label: "Approve second tool", value: "confirm_once" },
            { label: "Decline second tool", value: "decline" },
        ],
        multiSelect: false,
        requestUuid: REQUEST_UUID,
        resumeToken: "rotated-resume-token",
        type: "confirmation",
    };
    responseDeferred.resolve({
        request_uuid: REQUEST_UUID,
        responseState: "waiting_user",
    });

    await firstClick;
    await contains(`${INPUT_REQUEST_SELECTOR} button:contains('Approve second tool')`);
    expect(session.userInputRequest.resumeToken).toBe("rotated-resume-token");
});
