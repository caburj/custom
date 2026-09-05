import { aiModels } from "@ai/../tests/ai_test_helpers";
import { AIAgent } from "@ai/../tests/mock_server/mock_models/ai_agent";
import { AiAgentPanel } from "@ai_app/discuss/core/web/ai_agent_panel/ai_agent_panel";
import { click, contains, insertText, startServer } from "@mail/../tests/mail_test_helpers";
import { advanceTime, animationFrame, describe, expect, test } from "@odoo/hoot";
import { defineModels, fields, models, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";

class PanelAgent extends AIAgent {
    skill_ids = fields.Many2many({ relation: "ai.skill" });
    custom_skill_ids = fields.Many2many({ relation: "ai.skill" });
    _views = {
        form: `<form>
            <field name="name"/><field name="subtitle"/><field name="image_128"/>
            <field name="system_prompt"/><field name="skill_ids"/>
            <field name="allowed_agent_ids" widget="many2many_tags"/>
            <field name="custom_skill_ids" widget="many2many_tags"/>
        </form>`,
    };
}

class AISkill extends models.ServerModel {
    _name = "ai.skill";
    name = fields.Char();
    is_native_skill = fields.Boolean();
}

defineModels({ ...aiModels, AIAgent: PanelAgent, AISkill });
describe.current.tags("desktop");

test("the native agent Skills panel edits and autosaves allowed agents", async () => {
    const pyEnv = await startServer();
    const first = pyEnv["ai.agent"].create({ name: "First assistant" });
    const second = pyEnv["ai.agent"].create({ name: "Second assistant" });
    const root = pyEnv["ai.agent"].create({
        name: "Coordinator", allowed_agent_ids: [first],
    });
    await mountWithCleanup(AiAgentPanel, {
        props: { agent: { id: root, update() {} } },
    });
    await click(".o_ai_agent_panel_tab:contains('Skills')");
    await contains("label[for='allowed_agent_ids']", { text: "Allowed Agents" });
    await contains("[name='allowed_agent_ids']", { text: "First assistant" });
    await click("label[for='allowed_agent_ids']");
    expect(document.activeElement.id).toBe("allowed_agent_ids");
    onRpc("ai.agent", "web_save", () => expect.step("allowed agents saved"));
    await insertText("#allowed_agent_ids", "Second assistant");
    await click(".o-autocomplete--dropdown-item:contains('Second assistant')");
    await advanceTime(600);
    await expect.waitForSteps(["allowed agents saved"]);
    await animationFrame();
    expect(pyEnv["ai.agent"].read(root, ["allowed_agent_ids"])[0].allowed_agent_ids).toEqual([
        first, second,
    ]);
    await contains("[name='allowed_agent_ids']", { text: "Second assistant" });
});
