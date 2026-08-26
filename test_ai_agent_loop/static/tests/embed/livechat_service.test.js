import { LivechatService } from "@im_livechat/embed/common/livechat_service";

import { expect, test } from "@odoo/hoot";

test("AI livechat session parameters contain the agent ID, not its Store record", () => {
    const livechat = Object.create(LivechatService.prototype);
    livechat.store = {
        livechat_rule: {
            ai_agent_id: { id: 42 },
        },
    };

    const params = livechat.getSessionExtraParams(undefined, {});

    expect(params).toEqual({ ai_agent_id: 42 });
    expect(() => JSON.stringify(params)).not.toThrow();
});
