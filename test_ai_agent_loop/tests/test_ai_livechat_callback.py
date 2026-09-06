# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy
import json
from unittest.mock import patch

import requests

from odoo import Command, http
from odoo.addons.mail.tools.discuss import Store
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .test_ai_session_subagents import tool_call


def accept_submitted_request(_connection, _route, _payload, **_kwargs):
    return None


@tagged("post_install", "-at_install")
class TestAILivechatCallback(HttpCase):
    def _post_completion_callback(self, payload):
        with self.allow_requests(all_requests=True):
            response = requests.post(
                f"{self.base_url()}/ai/completion_result_ready",
                json=payload,
                timeout=12,
            )
        self.assertNotIn("Cookie", response.request.headers)
        return response

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

    def test_cors_session_advance_and_pending_interaction_routes_create_guest_session_and_durable_exchange(self):
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
        # CORS must still use the guest, even when the browser has admin cookies.
        self.authenticate('admin', 'admin')

        with patch(
            "odoo.addons.ai.models.ai_session.call_odoo_ai_transport",
            side_effect=accept_submitted_request,
        ) as submit:
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
        request_uuid = acknowledgement["request_uuid"]
        self.assertEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.request_phase, "submitted")
        self.assertEqual(session.loop_state, "waiting_model")
        origin_message = self.env["mail.message"].browse(message_id)
        self.assertEqual(session.request_guest_id, origin_message.author_guest_id)
        self.assertEqual(session.request_user_id, self.env.ref('base.public_user'))
        self.assertEqual(submit.call_args.args[1], "1/get_completions")
        submitted_payload = submit.call_args.args[2]
        self.assertEqual(submitted_payload["webhook_url"], session.request_callback_url)
        self.assertIs(submitted_payload["llm_retry"], False)
        self.assertNotIn("callback_url", submitted_payload)
        with self.registry.cursor() as cr:
            self.env(cr=cr)["ai.session"].sudo().browse(session.id).state = {
                "available_tools": [client_tool.id],
            }

        original_continue = self.registry['ai.session']._continue
        observed = {}

        def observe_guest_environment(session, request_uuid):
            request_env = http.request.env
            observed.update({
                'actor_uid': request_env.uid,
                'guest_id': request_env.context['guest'].id,
                'default_environment': request_env.transaction.default_env is request_env,
                'sudo': request_env.su,
            })
            return original_continue(session, request_uuid)

        with patch.object(
            self.registry['ai.session'], '_continue',
            autospec=True, side_effect=observe_guest_environment,
        ):
            callback_response = self._post_completion_callback({
                "request_uuid": request_uuid,
                "llm_result": {
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
                },
                "llm_error": False,
            })
        self.assertEqual(callback_response.status_code, 200)
        self.assertIsNone(callback_response.json())
        self.assertEqual(observed['actor_uid'], session.request_user_id.id)
        self.assertEqual(observed['guest_id'], session.request_guest_id.id)
        self.assertTrue(observed['default_environment'])
        self.assertFalse(observed['sudo'])

        self.env.invalidate_all()
        self.assertEqual(session.loop_state, "waiting_client_result")
        resume_token = session.resume_token

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
            "odoo.addons.ai.models.ai_session.call_odoo_ai_transport",
            side_effect=accept_submitted_request,
        ):
            resume_response = self.url_open(
                "/ai/cors/resume_pending_interaction",
                json=self.build_rpc_payload({
                    "guest_token": guest_token,
                    "channel_id": channel_id,
                    "session_id": session.id,
                    "resume_token": resume_token,
                    "response": {
                        "kind": "client_error",
                        "value": "Unavailable in the livechat bundle",
                    },
                }),
                headers={"Origin": "https://example.com"},
            )
        self.assertEqual(resume_response.status_code, 200)
        self.assertEqual(resume_response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(resume_response.json()["result"]["responseState"], "running")

        self.env.invalidate_all()
        self.assertEqual(session.loop_state, "waiting_model")
        self.assertEqual(session.request_phase, "submitted")
        self.assertEqual(session.request_round, 2)
        self.assertNotEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.request_user_id, self.env.ref('base.public_user'))
        self.assertEqual(session.request_guest_id, origin_message.author_guest_id)

    def test_same_origin_guest_session_advance_route_creates_livechat_session(self):
        agent = self.env["ai.agent"].create({"name": "Same-Origin Livechat Agent"})
        channel_id, guest_token, message_id = self._create_livechat_message(agent)
        cookie_name = self.env["mail.guest"]._cookie_name
        self.opener.cookies.set(cookie_name, guest_token)

        with patch(
            "odoo.addons.ai.models.ai_session.call_odoo_ai_transport",
            side_effect=accept_submitted_request,
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

    def _assert_guest_subagent_reply(self, interaction_kind, *, cors):
        diagnostic = self.env['ir.actions.server'].create({
            'name': 'Guest reply actor', 'ai_tool_name': 'guest_reply_actor',
            'ai_tool_description': 'Report the executing guest authority.',
            'ai_tool_schema': '{"type":"object","properties":{},"required":[]}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code', 'use_in_ai': True,
            'code': "ai['result'] = {'user_id': env.uid, 'sudo': env.su, 'guest_id': env.context['guest'].id}",
        })
        forbidden_name = f'Guest forbidden contact {diagnostic.id}'
        if interaction_kind == 'question':
            interactive_tool = self.env.ref('ai.ir_actions_server_ask_user_question')
            args = {'question': 'Which guest option?', 'choices': ['Guest option A', 'Guest option B'],
                    'multi_select': False, 'allow_free_text': False}
            response_value = ['Guest option A']
            expected_label = 'Guest option A'
        else:
            interactive_tool = self.env['ir.actions.server'].create({
                'name': 'Guest reply confirmation', 'ai_tool_name': 'guest_reply_confirmation',
                'ai_tool_description': 'Request confirmation before attempting a restricted operation.',
                'ai_tool_schema': '{"type":"object","properties":{},"required":[]}',
                'model_id': self.env.ref('ai.model_ai_tool').id,
                'state': 'code', 'use_in_ai': True,
                'code': f"""
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {{
        'type': 'confirmation', 'body': 'Approve this guest operation?',
        'choices': [{{'label': 'Approve guest operation', 'value': 'confirm_once'}}],
    }}
else:
    env['res.partner'].create({{'name': {forbidden_name!r}}})
    ai['result'] = 'Unexpected privileged effect'
""",
            })
            args = {}
            response_value = 'confirm_once'
            expected_label = 'Approve guest operation'
        agent = self.env['ai.agent'].create({
            'name': f'Guest {interaction_kind} coordinator', 'skill_ids': [Command.clear()],
        })
        agent.allowed_agent_ids = agent
        channel_id, guest_token, message_id = self._create_livechat_message(agent)
        self.env.invalidate_all()
        channel = self.env['discuss.channel'].browse(channel_id)
        guest = self.env['mail.message'].browse(message_id).author_guest_id
        wrong_guest = self.env['mail.guest'].create({'name': 'Different reply guest'})
        wrong_token = wrong_guest._format_auth_cookie()
        cookie_name = self.env['mail.guest']._cookie_name
        if cors:
            # The CORS route must retain guest authority even with admin cookies.
            self.authenticate('admin', 'admin')
        else:
            self.authenticate(None, None)
            self.opener.cookies.set(cookie_name, guest_token)
        route_prefix = '/ai/cors' if cors else '/ai'
        guest_args = {'guest_token': guest_token} if cors else {}
        with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                   side_effect=accept_submitted_request):
            started = self.url_open(f'{route_prefix}/start_session_advance', json=self.build_rpc_payload({
                **guest_args, 'channel_id': channel_id, 'mail_message_id': message_id,
            }))
            self.assertNotIn('error', started.json())
            root_uuid = started.json()['result']['request_uuid']
            launched = self._post_completion_callback({
                'request_uuid': root_uuid, 'llm_error': False,
                'llm_result': {'status': 'success', 'result': {'role': 'assistant', 'content': [
                    tool_call('start_session', f'child-{index}', agent_id=agent.id, message=f'Guest work {index}')
                    for index in (1, 2)
                ]}},
            })
            self.assertEqual(launched.status_code, 200)
        self.env.invalidate_all()
        root = self.env['ai.session'].sudo().search([('request_uuid', '=', root_uuid)])
        children = self.env['ai.session'].sudo().search([('parent_session_id', '=', root.id)], order='id')
        self.assertEqual(len(children), 2)
        first, sibling = children
        with self.registry.cursor() as cr:
            self.env(cr=cr)['ai.session'].sudo().browse(children.ids).state = {
                'available_tools': (interactive_tool | diagnostic).ids,
            }
        for child in children:
            waiting = self._post_completion_callback({
                'request_uuid': child.request_uuid, 'llm_error': False,
                'llm_result': {'status': 'success', 'result': {'role': 'assistant', 'content': [
                    tool_call(interactive_tool.ai_tool_name, f'interaction-{child.id}', **args),
                    tool_call(diagnostic.ai_tool_name, f'actor-{child.id}'),
                ]}},
            })
            self.assertEqual(waiting.status_code, 200)
        self.env.invalidate_all()
        source_uuid, source_token = first.request_uuid, first.resume_token
        source_pending = copy.deepcopy(first.pending_tool_call)
        sibling_pending = copy.deepcopy(sibling.pending_tool_call)
        sibling_token, sibling_uuid = sibling.resume_token, sibling.request_uuid
        root_pending = copy.deepcopy(root.pending_tool_call)
        before_messages = channel.message_ids
        observed = []
        resume = self.registry['ai.session']._resume_pending_interaction

        def observe_reply_actor(session, *args, **kwargs):
            request_env = http.request.env
            observed.append((session.id, request_env.uid, request_env.su, request_env.context['guest'].id))
            return resume(session, *args, **kwargs)

        payload = {
            'channel_id': channel_id, 'session_id': first.id,
            'resume_token': source_token,
            'response': {'kind': interaction_kind, 'value': response_value},
        }
        with (
            mute_logger('odoo.http'),
            patch.object(self.registry['ai.session'], '_resume_pending_interaction', observe_reply_actor),
            patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                  side_effect=accept_submitted_request) as submit,
        ):
            if not cors:
                self.opener.cookies.set(cookie_name, wrong_token)
            denied = self.url_open(f'{route_prefix}/resume_pending_interaction', json=self.build_rpc_payload({
                **payload, **({'guest_token': wrong_token} if cors else {}),
            }))
            self.assertIn('error', denied.json())
            self.env.invalidate_all()
            self.assertEqual(channel.message_ids, before_messages)
            self.assertEqual(first.pending_tool_call, source_pending)
            self.assertEqual(sibling.pending_tool_call, sibling_pending)
            self.assertFalse(observed)
            submit.assert_not_called()
            if not cors:
                self.opener.cookies.set(cookie_name, guest_token)
            answered = self.url_open(f'{route_prefix}/resume_pending_interaction', json=self.build_rpc_payload({
                **payload, **guest_args,
            }))
            self.assertNotIn('error', answered.json())
            self.assertEqual(answered.json()['result']['responseState'], 'running')
            submit.assert_called_once()
        self.env.invalidate_all()
        public = self.env.ref('base.public_user')
        self.assertEqual(observed, [(first.id, public.id, False, guest.id)])
        self.assertEqual(first.request_user_id, public)
        self.assertEqual(first.request_guest_id, guest)
        self.assertEqual(first.loop_state, 'waiting_model')
        self.assertNotEqual(first.request_uuid, source_uuid)
        self.assertEqual(answered.json()['result']['request_uuid'], first.request_uuid)
        self.assertEqual(sibling.pending_tool_call, sibling_pending)
        self.assertEqual((sibling.request_uuid, sibling.resume_token), (sibling_uuid, sibling_token))
        self.assertEqual(root.pending_tool_call, root_pending)
        self.assertEqual(root.request_uuid, root_uuid)
        replies = (channel.message_ids - before_messages).filtered(lambda message: message.author_guest_id == guest)
        self.assertEqual(len(replies), 1)
        self.assertIn(expected_label, replies.body)
        self.assertFalse(replies.author_id)
        tool_results = [part for message in first.request_payload['messages'] for part in message['content']
                        if part.get('type') == 'tool_result']
        actor_result = json.loads(tool_results[-1]['result'][0]['text'])
        self.assertEqual(actor_result, {'user_id': public.id, 'sudo': False, 'guest_id': guest.id})
        if interaction_kind == 'confirmation':
            self.assertFalse(tool_results[0]['success'])
            self.assertFalse(self.env['res.partner'].search([('name', '=', forbidden_name)]))
        else:
            self.assertTrue(tool_results[0]['success'])

        # Another model round makes a consumed interaction older than one predecessor.
        with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                   side_effect=accept_submitted_request) as submit:
            progressed = self._post_completion_callback({
                'request_uuid': first.request_uuid, 'llm_error': False,
                'llm_result': {'status': 'success', 'result': {'role': 'assistant', 'content': [
                    tool_call(diagnostic.ai_tool_name, f'later-actor-{first.id}'),
                ]}},
            })
            self.assertEqual(progressed.status_code, 200)
            submit.assert_called_once()
        self.env.invalidate_all()
        current_uuid = first.request_uuid
        before_events, before_messages = first.event_ids, channel.message_ids
        with (
            patch.object(self.registry['ai.session'], '_resume_pending_interaction') as resume,
            patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport') as submit,
        ):
            replay = self.url_open(f'{route_prefix}/resume_pending_interaction',
                                   json=self.build_rpc_payload({**payload, **guest_args}))
        self.assertEqual(replay.json().get('result'), {
            'request_uuid': current_uuid, 'responseState': 'running',
        }, replay.text)
        resume.assert_not_called()
        submit.assert_not_called()
        self.env.invalidate_all()
        self.assertEqual(first.event_ids, before_events)
        self.assertEqual(channel.message_ids, before_messages)
        self.assertEqual(sibling.pending_tool_call, sibling_pending)

    def test_same_origin_guest_subagent_question_reply_keeps_guest_authority(self):
        self._assert_guest_subagent_reply('question', cors=False)

    def test_cors_guest_subagent_confirmation_reply_keeps_guest_authority(self):
        self._assert_guest_subagent_reply('confirmation', cors=True)
