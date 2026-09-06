import {
    click,
    contains,
    insertText,
    setupChatHub,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";

import { Command, onRpc, serverState } from "@web/../tests/web_test_helpers";
import { defineAIModels } from "@ai/../tests/ai_test_helpers";

describe.current.tags("desktop");
defineAIModels();

const INPUT_REQUEST_SELECTOR = ".o_ai_user_input_request";
const REQUEST_UUID = "00000000-0000-4000-8000-000000000051";
const RESUME_TOKEN = "callback-question-token";

async function startPendingQuestion(overrides = {}) {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "AI Agent" });
    const aiAgentId = pyEnv["ai.agent"].create({
        name: "AI Agent",
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
        response_state: "waiting_user",
        user_input_request: {
            allowFreeText: false,
            choices: [
                { label: "Draft", value: "Draft" },
                { label: "Send", value: "Send" },
            ],
            multiSelect: false,
            resumeToken: RESUME_TOKEN,
            type: "question",
            ...overrides,
        },
    });
    pyEnv["mail.message"].create({
        author_id: partnerId,
        body: "Which option should be used?",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
    });
    setupChatHub({ opened: [channelId] });
    await start();
    await contains(INPUT_REQUEST_SELECTOR);
}

function expectPendingInteractionResume(expectedResponse, step) {
    onRpc("/ai/generate_response", () => {
        throw new Error("Callback questions must not use the synchronous response route");
    });
    onRpc("/ai/resume_pending_interaction", async (request) => {
        const { params } = await request.json();
        expect(params.request_uuid).toBe(undefined);
        expect(params.resume_token).toBe(RESUME_TOKEN);
        expect(params.response).toEqual(expectedResponse);
        expect.step(step);
        return { request_uuid: REQUEST_UUID, responseState: "running" };
    });
}

test("server-hydrated single choice resumes through the pending-interaction route", async () => {
    expectPendingInteractionResume(
        { kind: "question", value: ["Draft"] },
        "single answer resumed"
    );
    await startPendingQuestion();

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Draft')`);

    await expect.waitForSteps(["single answer resumed"]);
    await contains(INPUT_REQUEST_SELECTOR, { count: 0 });
});

test("free text resumes with one structured value", async () => {
    expectPendingInteractionResume(
        { kind: "question", value: ["Antwerp"] },
        "free text resumed"
    );
    await startPendingQuestion({ allowFreeText: true });

    await insertText(
        `${INPUT_REQUEST_SELECTOR} input[placeholder='Something else']`,
        "Antwerp"
    );
    await press("Enter");

    await expect.waitForSteps(["free text resumed"]);
});

test("multi-select resumes in displayed choice order", async () => {
    expectPendingInteractionResume(
        { kind: "question", value: ["Red", "Blue"] },
        "multi answer resumed"
    );
    await startPendingQuestion({
        choices: [
            { label: "Red", value: "Red" },
            { label: "Green", value: "Green" },
            { label: "Blue", value: "Blue" },
        ],
        multiSelect: true,
    });

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Blue')`);
    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Red')`);
    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Confirm')`);

    await expect.waitForSteps(["multi answer resumed"]);
});

test("skip settles through the token-fenced pending-interaction route", async () => {
    expectPendingInteractionResume({ kind: "skip" }, "skip resumed");
    await startPendingQuestion();

    await click(`${INPUT_REQUEST_SELECTOR} button:contains('Skip')`);

    await expect.waitForSteps(["skip resumed"]);
    await contains(INPUT_REQUEST_SELECTOR, { count: 0 });
});
