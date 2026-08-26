# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo import Command
from odoo.addons.mail.tools.discuss import Store
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestAILivechatCallback(HttpCase):
    def _create_livechat_message(self, agent):
        livechat_channel = self.env["im_livechat.channel"].create({
            "name": "Callback Livechat Channel",
            "rule_ids": [Command.create({"ai_agent_id": agent.id})],
        })
        session_data = self.make_jsonrpc_request("/im_livechat/cors/get_session", {
            "ai_agent_id": agent.id,
            "channel_id": livechat_channel.id,
            "persisted": True,
        })
        guest_token = session_data["store_data"]["Store"]["guest_token"]
        message_data = self.make_jsonrpc_request("/im_livechat/cors/message/post", {
            "guest_token": guest_token,
            "thread_model": "discuss.channel",
            "thread_id": session_data["channel_id"],
            "post_data": {
                "body": "Hi",
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
            },
        })
        return session_data["channel_id"], guest_token, message_data["message_id"]

    def test_cors_session_advance_and_pending_interaction_routes_create_guest_session_and_durable_request(self):
        client_tool = self.env["ir.actions.server"].create({
            "name": "Callback Livechat Client Tool",
            "ai_tool_name": "callback_livechat_client_tool",
            "ai_tool_description": "Return a browser command for the callback test.",
            "ai_tool_schema": '{"type": "object", "properties": {}, "required": []}',
            "model_id": self.env.ref("ai.model_ai_tool").id,
            "state": "code",
            "use_in_ai": True,
            "code": """
ai['result'] = {
    'client_tool': {
        'name': 'callback_livechat_browser_value',
        'params': {'key': 'answer'},
    },
}
""",
        })
        skill = self.env["ai.skill"].create({
            "name": "Callback Livechat Client Skill",
            "tool_ids": [Command.set(client_tool.ids)],
        })
        agent = self.env["ai.agent"].create({
            "name": "Callback Livechat Agent",
            "skill_ids": [Command.set(skill.ids)],
        })
        channel_id, guest_token, message_id = self._create_livechat_message(agent)

        self.env.invalidate_all()
        self.assertFalse(self.env["ai.session"].sudo().search([
            ("channel_id", "=", channel_id),
        ]))

        with patch(
            "odoo.addons.ai.controllers.thread.call_odoo_ai_transport",
            return_value={"status": "queued"},
        ):
            response = self.url_open(
                "/ai/cors/start_session_advance",
                json=self.build_rpc_payload({
                    "guest_token": guest_token,
                    "channel_id": channel_id,
                    "mail_message_id": message_id,
                }),
                headers={"Origin": "https://example.com"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        acknowledgement = response.json()["result"]
        self.assertEqual(acknowledgement["responseState"], "running")

        self.env.invalidate_all()
        session = self.env["ai.session"].sudo().search([
            ("channel_id", "=", channel_id),
        ])
        self.assertEqual(len(session), 1)
        stored_session = Store().add(
            session, "_store_session_fields",
        )._build_result()["ai.session"][0]
        self.assertEqual(stored_session["channel_id"], channel_id)
        session_request = self.env["ai.session.request"].sudo().search([
            ("session_id", "=", session.id),
        ])
        self.assertEqual(len(session_request), 1)
        self.assertEqual(session_request.request_uuid, acknowledgement["request_uuid"])
        self.assertEqual(session_request.state, "waiting_iap")
        origin_message = self.env["mail.message"].browse(message_id)
        self.assertEqual(session_request.guest_id, origin_message.author_guest_id)
        with self.registry.cursor() as cr:
            self.env(cr=cr)["ai.session"].sudo().browse(session.id).state = {
                "available_tools": [client_tool.id],
            }

        result = {
            "request_uuid": session_request.request_uuid,
            "status": "success",
            "result": {
                "role": "assistant",
                "content": [{
                    "type": "tool_call",
                    "call_id": "livechat-client-tool",
                    "name": client_tool.ai_tool_name,
                    "args": {},
                }],
            },
        }
        with patch(
            "odoo.addons.ai.controllers.thread.call_odoo_ai_transport",
            return_value=result,
        ):
            self.make_jsonrpc_request("/ai/completion_result_ready", {
                "request_uuid": session_request.request_uuid,
            })

        self.env.invalidate_all()
        self.assertEqual(session_request.state, "waiting_input")
        resume_token = session_request.resume_token

        preflight_response = self.url_open(
            "/ai/cors/resume_pending_interaction",
            method="OPTIONS",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(preflight_response.status_code, 204)
        self.assertEqual(
            preflight_response.headers["Access-Control-Allow-Origin"], "*",
        )

        with patch(
            "odoo.addons.ai.controllers.thread.call_odoo_ai_transport",
            return_value={"status": "queued"},
        ):
            resume_response = self.url_open(
                "/ai/cors/resume_pending_interaction",
                json=self.build_rpc_payload({
                    "guest_token": guest_token,
                    "channel_id": channel_id,
                    "request_uuid": session_request.request_uuid,
                    "resume_token": resume_token,
                    "response": {"error": "Unavailable in the livechat bundle"},
                }),
                headers={"Origin": "https://example.com"},
            )
        self.assertEqual(resume_response.status_code, 200)
        self.assertEqual(resume_response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(resume_response.json()["result"]["responseState"], "running")

        self.env.invalidate_all()
        self.assertEqual(session_request.state, "done")
        self.assertEqual(self.env["ai.session.request"].sudo().search_count([
            ("session_id", "=", session.id),
        ]), 2)

    def test_same_origin_guest_session_advance_route_creates_livechat_session(self):
        agent = self.env["ai.agent"].create({"name": "Same-Origin Livechat Agent"})
        channel_id, guest_token, message_id = self._create_livechat_message(agent)
        cookie_name = self.env["mail.guest"]._cookie_name
        self.opener.cookies.set(cookie_name, guest_token)

        with patch(
            "odoo.addons.ai.controllers.thread.call_odoo_ai_transport",
            return_value={"status": "queued"},
        ):
            response = self.url_open(
                "/ai/start_session_advance",
                json=self.build_rpc_payload({
                    "channel_id": channel_id,
                    "mail_message_id": message_id,
                }),
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("error", response.json())
        self.assertEqual(response.json()["result"]["responseState"], "running")
        self.env.invalidate_all()
        self.assertEqual(self.env["ai.session"].sudo().search_count([
            ("channel_id", "=", channel_id),
        ]), 1)
