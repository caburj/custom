# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy
from contextlib import nullcontext
from threading import current_thread
from unittest.mock import patch

import requests
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request as WerkzeugRequest

from odoo import api, Command, http
from odoo.exceptions import MissingError
from odoo.http.requestlib import Request as HttpRequest
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.iap import InsufficientCreditError
from odoo.addons.ai.controllers.thread import AIThreadController
from odoo.addons.ai.utils.ai_utils import (
    get_odoo_ai_connection_data,
    IAP_TRANSPORT_TIMEOUT,
    UserInputResponse,
)

from .common import apply_iap_result


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
    }


def accept_submitted_request(_connection, _route, _payload, **_kwargs):
    return None


@tagged('post_install', '-at_install')
class TestAISessionLoopHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, cls.env.uid, {})
            agent = env['ai.agent'].create({
                'name': 'Callback HTTP Test Agent',
                'system_prompt': 'Answer plainly.',
            })
            agent.skill_ids = env['ai.skill'].create({
                'name': 'Callback HTTP Business Records',
                'instructions': 'Create and update test contacts when requested.',
                'tool_ids': [Command.set([
                    env.ref('ai.ir_actions_server_create_records').id,
                    env.ref('ai.ir_actions_server_update_records').id,
                ])],
            })
            channel = agent._create_ai_chat_channel('Callback HTTP Test')
            session = env['ai.session'].sudo().create({
                'agent_id': agent.id,
                'channel_id': channel.id,
            })
            other_user = new_test_user(
                env,
                login='callback_confirmation_other',
                groups='base.group_user',
            )
            cls.agent_id = agent.id
            cls.channel_id = channel.id
            cls.session_id = session.id
            cls.other_user_id = other_user.id
        cls.agent = cls.env['ai.agent'].browse(cls.agent_id)
        cls.channel = cls.env['discuss.channel'].browse(cls.channel_id)
        cls.ai_session = cls.env['ai.session'].sudo().browse(cls.session_id)

    def _post_committed_prompt(self, body):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            return env['discuss.channel'].browse(self.channel_id).message_post(
                body=body, message_type='comment',
            ).id

    def _start_session_advance(self, message, **params):
        return self.url_open(
            '/ai/start_session_advance',
            json=self.build_rpc_payload({
                'channel_id': self.channel.id,
                'mail_message_id': message.id,
                **params,
            }),
        )

    def _post_completion_callback(self, payload):
        with self.allow_requests(all_requests=True):
            response = requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json=payload,
                timeout=12,
            )
        self.assertNotIn('Cookie', response.request.headers)
        return response

    def _get_session(self, session_id):
        self.env.invalidate_all()
        return self.env['ai.session'].sudo().browse(session_id)

    def _submit_prepared(self, prepared):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            return env['ai.session'].browse(prepared['session_id'])._submit_prepared_request(prepared['request_uuid'])

    def _create_committed_prepared_session(self, label, *, auto_confirm=False):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            channel = env['ai.agent'].browse(
                self.agent_id,
            )._create_ai_chat_channel(label)
            session = env['ai.session'].sudo().create({
                'agent_id': self.agent_id,
                'channel_id': channel.id,
                'auto_confirm': auto_confirm,
            })
            if auto_confirm:
                session.state = {'available_tools': [
                    env.ref('ai.ir_actions_server_create_records').id,
                    env.ref('ai.ir_actions_server_update_records').id,
                ]}
            message = channel.message_post(body=label, message_type='comment')
            session._prepare_model_request(
                message._convert_to_parts(),
                context_snapshot={
                    'allowed_company_ids': env.companies.ids,
                    'active_company_ids': env.companies.ids,
                },
            )
            return {
                'session_id': session.id,
                'request_uuid': session.request_uuid,
                'request_webhook_token': session.request_webhook_token,
                'request_payload': session.request_payload,
                'event_count': len(session.event_ids),
            }

    def _create_committed_confirmation(self, label='HTTP Confirmed Contact', *, context_snapshot=None):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            channel = env['ai.agent'].browse(self.agent_id)._create_ai_chat_channel(label)
            session = env['ai.session'].sudo().create({
                'agent_id': self.agent_id,
                'channel_id': channel.id,
            })
            tool = env.ref('ai.ir_actions_server_create_records')
            session.state = {'available_tools': [tool.id]}
            message = channel.message_post(body=label, message_type='comment')
            context_snapshot = context_snapshot or {
                'active_company_ids': env.companies.ids,
                'allowed_company_ids': env.companies.ids,
            }
            session = session.with_context(context_snapshot)
            session._prepare_model_request(
                message._convert_to_parts(),
                context_snapshot=context_snapshot,
            )
            request_uuid = session.request_uuid
            apply_iap_result(session, request_uuid, {
                'request_uuid': request_uuid,
                'status': 'success',
                'result': {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'http-create-contact',
                        'name': tool.ai_tool_name,
                        'args': {
                            'explanation': f'Create {label}?',
                            'model_name': 'res.partner',
                            'preview_menu_id': False,
                            'values': [{
                                'field_values': [{
                                    'field': 'name',
                                    'value': label,
                                }],
                            }],
                        },
                    }],
                },
            })
            return {
                'channel_id': channel.id,
                'session_id': session.id,
                'request_uuid': request_uuid,
                'resume_token': session.resume_token,
                'label': label,
            }

    def _resume_pending_confirmation(self, confirmation, **overrides):
        values = {
            'channel_id': confirmation['channel_id'],
            'session_id': confirmation['session_id'],
            'resume_token': confirmation['resume_token'],
            'response': {
                'kind': 'confirmation',
                'value': UserInputResponse.CONFIRM_ONCE,
            },
        }
        values.update(overrides)
        return self.url_open(
            '/ai/resume_pending_interaction',
            json=self.build_rpc_payload(values),
        )

    def _create_contact_tool_call(self, label, call_id):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        return {
            'type': 'tool_call',
            'call_id': call_id,
            'name': tool.ai_tool_name,
            'args': {
                'explanation': f'Create {label}.',
                'model_name': 'res.partner',
                'preview_menu_id': False,
                'values': [{'field_values': [{
                    'field': 'name',
                    'value': label,
                }]}],
            },
        }

    def test_callback_restores_request_and_default_environment_on_same_cursor(self):
        prepared = self._create_committed_prepared_session(
            'Request actor environment',
        )
        original_continue = self.registry['ai.session']._continue
        observed = {}

        def observe_callback_environment(session, request_uuid):
            request_env = http.request.env
            observed.update({
                'same_cursor': session.env.cr is request_env.cr,
                'default_environment': request_env.transaction.default_env is request_env,
                'actor_uid': request_env.uid,
                'sudo': request_env.su,
                'context': dict(request_env.context),
            })
            return original_continue(session, request_uuid)

        with patch.object(
            self.registry['ai.session'], '_continue',
            autospec=True, side_effect=observe_callback_environment,
        ):
            response = self._post_completion_callback({
                'request_uuid': prepared['request_uuid'],
                'llm_result': {'status': 'success', 'result': assistant_text('Actor restored')},
                'llm_error': False,
            })

        self.assertEqual(response.status_code, 200)
        session = self._get_session(prepared['session_id'])
        self.assertTrue(observed['same_cursor'])
        self.assertTrue(observed['default_environment'])
        self.assertFalse(observed['sudo'])
        self.assertEqual(observed['actor_uid'], session.request_user_id.id)
        self.assertEqual(
            observed['context'], session.request_context,
        )

    def test_callback_rechecks_actor_company_before_storing_result(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            company = env['res.company'].create({'name': 'Revoked callback company'})
            env.user.company_ids = [Command.link(company.id)]
            channel = env['ai.agent'].browse(self.agent_id)._create_ai_chat_channel('Revoked callback')
            session = env['ai.session'].sudo().create({
                'agent_id': self.agent_id,
                'channel_id': channel.id,
            })
            message = channel.message_post(body='Revoked callback', message_type='comment')
            context_snapshot = {
                'allowed_company_ids': [company.id],
                'active_company_ids': [company.id],
            }
            session._prepare_model_request(
                message._convert_to_parts(), context_snapshot=context_snapshot,
            )
            prepared = {'session_id': session.id, 'request_uuid': session.request_uuid}
            env.user.company_ids = [Command.unlink(company.id)]

        with mute_logger('odoo.http'):
            response = self._post_completion_callback({
                'request_uuid': prepared['request_uuid'],
                'llm_result': {'status': 'success', 'result': assistant_text('Must not be stored')},
                'llm_error': False,
            })

        self.assertNotEqual(response.status_code, 200)
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertFalse(session.request_result)

    def test_actor_env_restores_caller_without_ending_transaction(self):
        cr = self.env.cr
        actor_id = self.env.ref('base.user_admin').id
        caller_id = self.env.ref('base.public_user').id
        guest_id = self.env['mail.guest'].create({'name': 'Actor transaction guest'}).id
        previous_default_env = cr.transaction.default_env
        builder = EnvironBuilder(path='/ai/completion_result_ready', method='POST')
        incoming_request = HttpRequest(WerkzeugRequest(builder.get_environ()))
        builder.close()
        incoming_request.registry = self.registry
        incoming_request.env = self.env(user=caller_id, context={'lang': 'en_US'}, su=False)
        request_token = http.request_var.set(incoming_request)
        controller = AIThreadController()
        try:
            with patch.object(current_thread(), 'uid', caller_id, create=True):
                incoming_request.update_env()
                caller_env = incoming_request.env
                for exit_kind in ('success', 'early_return', 'body_error'):
                    with self.subTest(exit_kind=exit_kind):
                        def run_transaction():
                            with controller._actor_env(
                                user_id=actor_id, context={'lang': 'fr_FR'}, guest_id=guest_id,
                            ) as env:
                                self.assertIs(env, http.request.env)
                                self.assertIs(env.transaction.default_env, env)
                                self.assertIs(env.cr, cr)
                                self.assertEqual(env.uid, actor_id)
                                self.assertFalse(env.su)
                                self.assertEqual(env.context['lang'], 'fr_FR')
                                self.assertEqual(env.context['guest'].env.uid, actor_id)
                                self.assertFalse(env.context['guest'].env.su)
                                if exit_kind == 'body_error':
                                    raise RuntimeError('body failed')
                                if exit_kind == 'early_return':
                                    return True
                            return False

                        error = self.assertRaisesRegex(RuntimeError, 'failed') if exit_kind == 'body_error' else nullcontext()
                        with (
                            patch.object(cr, 'commit') as commit,
                            patch.object(cr, 'rollback') as rollback,
                            error,
                        ):
                            self.assertEqual(run_transaction(), exit_kind == 'early_return')

                        commit.assert_not_called()
                        rollback.assert_not_called()
                        self.assertIs(http.request.env, caller_env)
                        self.assertIs(cr.transaction.default_env, caller_env)
                        self.assertEqual(current_thread().uid, caller_id)
        finally:
            cr.transaction.default_env = previous_default_env
            http.request_var.reset(request_token)

    def test_start_rebinds_the_channel_and_exact_message_in_caller_environment(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt(
            'Caller environment message',
        ))
        original_get_channel = AIThreadController._get_ai_channel_from_id
        observed = {}

        def observe_caller_environment(controller, env, channel_id):
            observed['caller_environment'] = env is http.request.env
            observed['request_cursor'] = env.cr is http.request.env.cr
            observed['default_environment'] = env.transaction.default_env is env
            observed['sudo'] = env.su
            return original_get_channel(controller, env, channel_id)

        with (
            patch.object(
                AIThreadController,
                '_get_ai_channel_from_id',
                autospec=True,
                side_effect=observe_caller_environment,
            ),
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                side_effect=accept_submitted_request,
            ),
        ):
            response = self._start_session_advance(message)

        self.assertNotIn('error', response.json())
        self.assertTrue(observed['caller_environment'])
        self.assertTrue(observed['request_cursor'])
        self.assertTrue(observed['default_environment'])
        self.assertFalse(observed['sudo'])

        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            foreign_channel = env['ai.agent'].browse(
                self.agent_id,
            )._create_ai_chat_channel('Foreign callback message')
            foreign_message_id = foreign_channel.message_post(
                body='Wrong channel', message_type='comment',
            ).id
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
        ) as transport:
            rejected = self._start_session_advance(
                self.env['mail.message'].browse(foreign_message_id),
            )

        self.assertIn('error', rejected.json())
        transport.assert_not_called()

    def test_website_sale_context_reaches_callback_pricing_consumer(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt(
            'Show me products',
        ))
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=accept_submitted_request,
        ):
            response = self._start_session_advance(message)

        self.assertEqual(response.status_code, 200)
        context = self._get_session(self.session_id).request_context
        self.assertTrue(context['website_id'])
        self.assertIn('pricelist_id', context)
        self.assertIn('fiscal_position_id', context)

        product_model = self.env['product.template'].with_context(**context)
        pricelist, fiscal_position = product_model._get_website_context()
        self.assertEqual(product_model.env.website.id, context['website_id'])
        self.assertEqual(pricelist.id, context['pricelist_id'])
        self.assertEqual(fiscal_position.id, context['fiscal_position_id'])

    def test_session_advance_accepts_numeric_prompt_button_id(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt(
            'Do I have any customer in New Jersey?',
        ))
        prompt_button = self.env.ref('ai.ai_prompt_customer_new_jersey')

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=accept_submitted_request,
        ) as submit:
            response = self._start_session_advance(
                message,
                ai_prompt_button_ref=prompt_button.id,
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('error', response.json())
        submitted_messages = submit.call_args.args[2]['messages']
        self.assertEqual(submit.call_args.kwargs['timeout'], IAP_TRANSPORT_TIMEOUT)
        submitted_text = ' '.join(
            part['text']
            for submitted_message in submitted_messages
            for part in submitted_message['content']
            if part['type'] == 'text'
        )
        self.assertIn('Get a list of contacts in New Jersey', submitted_text)

    def test_real_session_advance_and_callback_use_the_delivered_result(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt('Hi'))

        with (
            patch(
                "odoo.addons.ai.models.ai_session.call_odoo_ai_transport",
                side_effect=accept_submitted_request,
            ) as submit,
            patch.object(
                self.registry["ai.session"], "_continue", autospec=True,
            ) as advance,
        ):
            advance_response = self._start_session_advance(message)

        advance.assert_not_called()
        self.assertEqual(advance_response.status_code, 200)
        self.assertTrue(advance_response.headers['Content-Type'].startswith('application/json'))
        acknowledgement = advance_response.json()['result']
        self.assertTrue(acknowledgement['request_uuid'])
        self.assertEqual(acknowledgement['responseState'], 'running')
        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[1], '1/get_completions')
        submitted_payload = submit.call_args.args[2]
        self.assertEqual(
            submitted_payload['webhook_url'],
            f'{self.base_url()}/ai/completion_result_ready',
        )
        self.assertIs(submitted_payload['llm_retry'], False)
        self.assertNotIn('callback_url', submitted_payload)
        self.assertFalse(submit.call_args.kwargs['raise_user_error'])

        self.env.invalidate_all()
        session = self.env['ai.session'].sudo().search([
            ('request_uuid', '=', acknowledgement['request_uuid']),
        ])
        self.assertEqual(len(session), 1)
        request_uuid = acknowledgement['request_uuid']
        self.assertEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.request_phase, 'submitted')
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(
            session.request_callback_url,
            submitted_payload['webhook_url'],
        )

        callback_result = assistant_text('Result delivered by IAP')
        unknown = self._post_completion_callback({
            'request_uuid': '00000000-0000-4000-8000-ffffffffffff',
            'llm_result': {'status': 'success', 'result': callback_result},
            'llm_error': False,
        })
        self.assertEqual(unknown.status_code, 200)
        self.assertIsNone(unknown.json())
        self.assertNotIn('Set-Cookie', unknown.headers)

        event_count = len(self.ai_session.event_ids)
        message_count = len(self.channel.message_ids)
        with patch(
            'odoo.addons.ai.utils.ai_utils.iap_tools.iap_jsonrpc',
            side_effect=AssertionError('The callback must not poll IAP'),
        ):
            callback = self._post_completion_callback({
                'request_uuid': request_uuid,
                'llm_result': {'status': 'success', 'result': callback_result},
                'llm_error': False,
            })
        self.assertEqual(callback.status_code, 200)
        self.assertIsNone(callback.json())
        self.assertNotIn('Set-Cookie', callback.headers)
        self.env.invalidate_all()
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_phase)
        self.assertEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.request_result, {
            'kind': 'success',
            'message': callback_result,
        })
        self.assertEqual(len(self.ai_session.event_ids), event_count + 1)
        self.assertEqual(len(self.channel.message_ids), message_count + 1)
        self.assertIn('Result delivered by IAP', self.channel.message_ids[0].body)

        replay = self._post_completion_callback({
            'request_uuid': request_uuid,
            'llm_result': {'status': 'success', 'result': callback_result},
            'llm_error': False,
        })
        self.assertEqual(replay.status_code, 200)
        self.assertIsNone(replay.json())
        self.assertNotIn('Set-Cookie', replay.headers)
        self.env.invalidate_all()
        self.assertEqual(len(self.ai_session.event_ids), event_count + 1)
        self.assertEqual(len(self.channel.message_ids), message_count + 1)



    @mute_logger('odoo.http')
    def test_callback_rejects_malformed_payload(self):
        prepared = self._create_committed_prepared_session('Malformed callback payload')
        for llm_result, llm_error in (
            ({'status': 'success', 'result': assistant_text('Should not be applied')}, 'provider failed too'),
            (False, False),
            ({'status': 'success'}, False),
            ([], False),
        ):
            with self.subTest(llm_result=llm_result, llm_error=llm_error):
                response = self._post_completion_callback({
                    'request_uuid': prepared['request_uuid'],
                    'llm_result': llm_result,
                    'llm_error': llm_error,
                })

                self.assertEqual(response.status_code, 500)
                session = self._get_session(prepared['session_id'])
                self.assertEqual(session.loop_state, 'waiting_model')
                self.assertEqual(session.request_phase, 'prepared')
                self.assertFalse(session.request_result)

    def test_auto_approved_callback_mutations_keep_actor_attribution_after_flush(self):
        prepared = self._create_committed_prepared_session(
            'Callback actor attribution', auto_confirm=True,
        )
        create_tool = self.env.ref('ai.ir_actions_server_create_records')
        update_tool = self.env.ref('ai.ir_actions_server_update_records')
        actor_id = self.env.ref('base.user_admin').id
        create_call = {
            'type': 'tool_call',
            'call_id': 'callback-actor-create',
            'name': create_tool.ai_tool_name,
            'args': {
                'explanation': 'Create the attribution test contact.',
                'model_name': 'res.partner',
                'preview_menu_id': False,
                'values': [{'field_values': [{
                    'field': 'name', 'value': 'Callback Actor Before',
                }]}],
            },
        }
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=accept_submitted_request,
        ):
            created = self._post_completion_callback({
                'request_uuid': prepared['request_uuid'],
                'llm_result': {
                    'status': 'success',
                    'result': {'role': 'assistant', 'content': [create_call]},
                },
                'llm_error': False,
            })
        self.assertEqual(created.status_code, 200)
        self.env.invalidate_all()
        partner = self.env['res.partner'].search([('name', '=', 'Callback Actor Before')])
        self.assertEqual(len(partner), 1)
        self.assertEqual(partner.create_uid.id, actor_id)
        # Computed contact fields write during commit, after the tool returns.
        self.assertEqual(partner.write_uid.id, actor_id)

        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.request_phase, 'submitted')
        update_call = {
            'type': 'tool_call',
            'call_id': 'callback-actor-update',
            'name': update_tool.ai_tool_name,
            'args': {
                'explanation': 'Rename the attribution test contact.',
                'preview_menus': [],
                'updates': [{
                    'model_name': 'res.partner',
                    'domain': f"[('id', '=', {partner.id})]",
                    'changes': [{'field': 'name', 'value': 'Callback Actor After'}],
                }],
            },
        }
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=accept_submitted_request,
        ):
            updated = self._post_completion_callback({
                'request_uuid': session.request_uuid,
                'llm_result': {
                    'status': 'success',
                    'result': {'role': 'assistant', 'content': [update_call]},
                },
                'llm_error': False,
            })
        self.assertEqual(updated.status_code, 200)
        self.env.invalidate_all()
        self.assertEqual(partner.name, 'Callback Actor After')
        self.assertEqual(partner.write_uid.id, actor_id)

    def test_error_callback_finishes_the_matching_request(self):
        prepared = self._create_committed_prepared_session(
            'Terminal error callback',
        )
        response = self._post_completion_callback({
            'request_uuid': prepared['request_uuid'],
            'llm_result': False,
            'llm_error': 'provider unavailable',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'ready')
        self.assertEqual(session.request_uuid, prepared['request_uuid'])

    def test_confirmation_resume_executes_once_then_submits_followup(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation()
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=accept_submitted_request,
        ) as submit:
            response = self._resume_pending_confirmation(confirmation)

        self.assertEqual(response.status_code, 200)
        acknowledgement = response.json()['result']
        self.assertEqual(acknowledgement['responseState'], 'running')
        self.assertNotEqual(
            acknowledgement['request_uuid'], confirmation['request_uuid'],
        )
        submit.assert_called_once()
        self.env.invalidate_all()
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'submitted')
        self.assertFalse(session.resume_token)
        self.assertEqual(session.request_round, 2)
        self.assertEqual(session.request_uuid, acknowledgement['request_uuid'])
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', confirmation['label']),
        ]), 1)



    def test_confirmation_resume_captures_fresh_browser_context(self):
        self.authenticate('admin', 'admin')
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            resumed_company = env['res.company'].create({
                'name': 'Callback Resume Company',
            })
            env.user.company_ids = [Command.link(resumed_company.id)]
            resumed_company_id = resumed_company.id

        confirmation = self._create_committed_confirmation(
            'HTTP Fresh Context Contact',
        )
        session = self._get_session(confirmation['session_id'])
        original_snapshot = dict(session.request_context)
        current_view_info = {'marker': 'fresh-browser-view'}
        original_cids = self.opener.cookies.get('cids')
        self.opener.cookies['cids'] = str(resumed_company_id)
        try:
            with patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                side_effect=accept_submitted_request,
            ):
                response = self._resume_pending_confirmation(
                    confirmation,
                    current_view_info=current_view_info,
                )
        finally:
            if original_cids is None:
                self.opener.cookies.pop('cids', None)
            else:
                self.opener.cookies['cids'] = original_cids

        self.assertEqual(response.status_code, 200)
        acknowledgement = response.json()['result']
        self.env.invalidate_all()
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.request_uuid, acknowledgement['request_uuid'])
        self.assertNotEqual(session.request_context, original_snapshot)
        self.assertEqual(
            session.request_context['current_view_info'],
            current_view_info,
        )
        self.assertEqual(
            session.request_context['active_company_ids'],
            [resumed_company_id],
        )
        self.assertIn('fresh-browser-view', str(session.request_payload['messages']))

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
        ) as transport:
            duplicate = self._resume_pending_confirmation(confirmation)

        self.assertEqual(duplicate.json()['result'], acknowledgement)
        transport.assert_not_called()
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', confirmation['label']),
        ]), 1)

    def test_automation_resume_submits_with_final_prepared_context(self):
        self.authenticate('admin', 'admin')
        actor_id = self.env.ref('base.user_admin').id
        with self.registry.cursor() as cr:
            env = api.Environment(cr, actor_id, {})
            company = env['res.company'].create({'name': 'Automation Request Company'})
            env.user.company_ids = [Command.link(company.id)]
            company_id = company.id

        confirmation = self._create_committed_confirmation(
            'Automation Resume Actor Contact',
            context_snapshot={
                'allowed_company_ids': [company_id],
                'active_company_ids': [company_id],
                'ai_automation_run': True,
            },
        )
        observed = {}
        original_resume = self.registry['ai.session']._resume_pending_interaction

        def observe_activation_environment(session, *args, **kwargs):
            observed['activation_context'] = dict(http.request.env.context)

            def observe_activation_commit():
                env = http.request.env
                observed['activation_commit_context'] = dict(env.context)
                self.assertIs(env.transaction.default_env, env)

            session.env.cr.precommit.add(observe_activation_commit)
            return original_resume(session, *args, **kwargs)

        def observe_submission_environment(env):
            observed.update({
                'request_environment': env is http.request.env,
                'default_environment': env.transaction.default_env is env,
                'actor_uid': env.uid,
                'sudo': env.su,
                'context': dict(env.context),
                'company_ids': env.companies.ids,
            })
            return get_odoo_ai_connection_data(env)

        with (
            patch.object(
                self.registry['ai.session'], '_resume_pending_interaction',
                autospec=True, side_effect=observe_activation_environment,
            ),
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                side_effect=accept_submitted_request,
            ),
            patch(
                'odoo.addons.ai.models.ai_session.get_odoo_ai_connection_data',
                side_effect=observe_submission_environment,
            ),
        ):
            response = self._resume_pending_confirmation(confirmation)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('error', response.json())
        session = self._get_session(confirmation['session_id'])
        self.assertTrue(observed['request_environment'])
        self.assertTrue(observed['default_environment'])
        self.assertFalse(observed['sudo'])
        self.assertEqual(observed['actor_uid'], actor_id)
        self.assertEqual(observed['activation_commit_context'], observed['activation_context'])
        self.assertNotIn('ai_automation_run', observed['activation_commit_context'])
        self.assertEqual(observed['context'], session.request_context)
        self.assertTrue(observed['context']['ai_automation_run'])
        self.assertEqual(observed['company_ids'], [company_id])
        self.assertEqual(session.request_phase, 'submitted')
        partner = self.env['res.partner'].search([('name', '=', confirmation['label'])])
        self.assertEqual(partner.write_uid.id, actor_id)

    def test_confirmation_resume_treats_stale_token_as_noop_and_rejects_choice_and_channel(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation('HTTP Rejected Contact')
        another = self._create_committed_confirmation('HTTP Other Contact')

        with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport') as transport:
            stale_token = self._resume_pending_confirmation(
                confirmation, resume_token='an-already-consumed-resume-token',
            )
        transport.assert_not_called()
        wrong_choice = self._resume_pending_confirmation(
            confirmation,
            response={'kind': 'confirmation', 'value': 'invented-confirmation-choice'},
        )
        wrong_channel = self._resume_pending_confirmation(
            confirmation, channel_id=another['channel_id'],
        )

        self.assertEqual(stale_token.json()['result'], {
            'request_uuid': confirmation['request_uuid'],
            'responseState': 'waiting_user',
        })
        self.assertIn('error', wrong_choice.json())
        self.assertIn('error', wrong_channel.json())
        self.env.invalidate_all()
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.resume_token, confirmation['resume_token'])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_old_token_cannot_consume_confirmation_from_a_new_request(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation('HTTP First Token Contact')
        with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', side_effect=accept_submitted_request):
            first = self._resume_pending_confirmation(confirmation)
        self.assertNotIn('error', first.json())
        session = self._get_session(confirmation['session_id'])
        self.assertNotEqual(session.request_uuid, confirmation['request_uuid'])
        callback = self._post_completion_callback({
            'request_uuid': session.request_uuid,
            'llm_result': {'status': 'success', 'result': {
                'role': 'assistant',
                'content': [self._create_contact_tool_call('HTTP New Token Contact', 'new-token')],
            }},
            'llm_error': False,
        })
        self.assertEqual(callback.status_code, 200)
        session = self._get_session(session.id)
        token = session.resume_token
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertNotEqual(token, confirmation['resume_token'])
        events, messages = session.event_ids, session.channel_id.message_ids
        with (
            patch.object(self.registry['ai.session'], '_resume_pending_interaction') as resume,
            patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport') as submit,
        ):
            replay = self._resume_pending_confirmation(confirmation)
        self.assertEqual(replay.json()['result']['responseState'], 'waiting_user')
        resume.assert_not_called()
        submit.assert_not_called()
        session = self._get_session(session.id)
        self.assertEqual(session.resume_token, token)
        self.assertEqual(session.event_ids, events)
        self.assertEqual(session.channel_id.message_ids, messages)
        self.assertFalse(self.env['res.partner'].search_count([('name', '=', 'HTTP New Token Contact')]))

    def test_confirmation_resume_rejects_another_channel_member(self):
        confirmation = self._create_committed_confirmation(
            'HTTP Foreign Actor Contact',
        )
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            env['discuss.channel'].browse(
                confirmation['channel_id'],
            )._add_members(users=env['res.users'].browse(self.other_user_id))

        self.authenticate(
            'callback_confirmation_other',
            'callback_confirmation_other',
        )
        response = self._resume_pending_confirmation(confirmation)

        self.assertIn('error', response.json())
        self.env.invalidate_all()
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.resume_token, confirmation['resume_token'])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_confirmation_decline_settles_without_submission_or_mutation(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation('HTTP Declined Contact')
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
        ) as transport:
            response = self._resume_pending_confirmation(
                confirmation,
                response={
                    'kind': 'confirmation',
                    'value': UserInputResponse.DECLINE,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['responseState'], 'idle')
        transport.assert_not_called()
        self.env.invalidate_all()
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'ready')
        self.assertEqual(session.request_uuid, confirmation['request_uuid'])
        self.assertFalse(session.pending_tool_call)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_submission_rejects_a_stale_expected_uuid_before_iap_call(self):
        prepared = self._create_committed_prepared_session(
            'Exact UUID submission fence',
        )

        with (
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            ) as transport,
            self.assertRaises(MissingError),
        ):
            self._submit_prepared({
                'session_id': prepared['session_id'],
                'request_uuid': '00000000-0000-4000-8000-ffffffffffff',
            })

        transport.assert_not_called()
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'prepared')
        self.assertEqual(session.request_uuid, prepared['request_uuid'])

    def test_submission_reuses_the_persisted_payload_after_transport_failure(self):
        prepared = self._create_committed_prepared_session(
            'Stable webhook token across reconstruction',
        )
        request = {
            'session_id': prepared['session_id'],
            'request_uuid': prepared['request_uuid'],
        }
        sent_payloads = []

        def fail_first_send(_connection, _route, payload, **_kwargs):
            sent_payloads.append(copy.deepcopy(payload))
            if len(sent_payloads) == 1:
                raise requests.ConnectionError('uncertain first send')
            return None

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=fail_first_send,
        ):
            with self.assertRaises(requests.ConnectionError):
                self._submit_prepared(request)
            self.assertEqual(
                self._get_session(prepared['session_id']).request_phase,
                'prepared',
            )
            acknowledgement = self._submit_prepared(request)

        self.assertEqual(acknowledgement, {
            'request_uuid': prepared['request_uuid'],
            'responseState': 'running',
        })
        self.assertEqual(sent_payloads[0], sent_payloads[1])
        self.assertEqual(
            sent_payloads[0]['webhook_token'],
            prepared['request_webhook_token'],
        )
        self.assertEqual(
            self._get_session(prepared['session_id']).request_phase,
            'submitted',
        )

    def test_callback_before_late_acknowledgement_cannot_regress_session(self):
        prepared = self._create_committed_prepared_session(
            'Callback wins acknowledgement race',
        )
        callback_result = assistant_text('Callback completed before acknowledgement')

        callback = self._post_completion_callback({
            'request_uuid': prepared['request_uuid'],
            'llm_result': {'status': 'success', 'result': callback_result},
            'llm_error': False,
        })
        self.assertEqual(callback.status_code, 200)

        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_phase)
        self.assertEqual(session.request_result, {
            'kind': 'success', 'message': callback_result,
        })
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            session = env['ai.session'].sudo().browse(prepared['session_id'])
            self.assertFalse(session._apply_submission_acknowledgement(
                prepared['request_uuid'],
            ))

        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_phase)
        self.assertEqual(session.request_result, {
            'kind': 'success', 'message': callback_result,
        })

    def test_null_submission_response_marks_session_submitted_after_transport(self):
        prepared = self._create_committed_prepared_session(
            'Trust null transport response',
        )
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            return_value=None,
        ) as transport:
            acknowledgement = self._submit_prepared({
                'session_id': prepared['session_id'],
                'request_uuid': prepared['request_uuid'],
            })

        self.assertEqual(acknowledgement, {
            'request_uuid': prepared['request_uuid'],
            'responseState': 'running',
        })
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'submitted')
        self.assertEqual(session.request_uuid, prepared['request_uuid'])
        self.assertEqual(transport.call_args.args[1], '1/get_completions')
        payload = transport.call_args.args[2]
        self.assertEqual(payload['request_uuid'], prepared['request_uuid'])
        self.assertEqual(payload['webhook_token'], prepared['request_webhook_token'])
        self.assertEqual(payload['webhook_url'], session.request_callback_url)
        self.assertIs(payload['llm_retry'], False)
        self.assertNotIn('callback_url', payload)

        self.assertIsNone(self._submit_prepared(
            {'session_id': 0, 'request_uuid': prepared['request_uuid']},
        ))

    def test_submission_insufficient_credit_stores_failure_without_continuing(self):
        prepared = self._create_committed_prepared_session(
            'Synchronous insufficient credit',
        )
        with (
            patch(
                "odoo.addons.ai.models.ai_session.call_odoo_ai_transport",
                side_effect=InsufficientCreditError,
            ),
            patch.object(
                self.registry["iap.account"],
                "_send_no_credit_notification",
                autospec=True,
            ) as notify,
            patch.object(
                self.registry["ai.session"], "_continue", autospec=True,
            ) as continue_request,
        ):
            acknowledgement = self._submit_prepared({
                'session_id': prepared['session_id'],
                'request_uuid': prepared['request_uuid'],
            })

        self.assertEqual(
            acknowledgement,
            {
                "request_uuid": prepared["request_uuid"],
                "responseState": "running",
            },
        )
        continue_request.assert_not_called()
        notify.assert_not_called()
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, "waiting_model")
        self.assertEqual(session.request_phase, "prepared")
        self.assertEqual(session.request_uuid, prepared['request_uuid'])
        self.assertEqual(session.request_result, {
            'kind': 'failure',
            'code': 'insufficient_credit',
        })
        self.assertNotIn("AI is unreachable", session.channel_id.message_ids[0].body)

    def test_submission_leaves_commit_to_its_caller(self):
        prepared = self._create_committed_prepared_session('Caller-owned submission commit')
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            with (
                patch(
                    'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                    side_effect=accept_submitted_request,
                ),
                patch.object(cr, 'commit') as commit,
            ):
                acknowledgement = env['ai.session'].browse(prepared['session_id'])._submit_prepared_request(prepared['request_uuid'])
                commit.assert_not_called()

        self.assertEqual(acknowledgement['request_uuid'], prepared['request_uuid'])
        self.assertEqual(self._get_session(prepared['session_id']).request_phase, 'submitted')

    def test_submission_does_not_hold_the_session_row_lock_during_transport(self):
        raw_cursor = self.registry._db.cursor
        with raw_cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            agent = env['ai.agent'].create({
                'name': 'Callback physical lock agent',
                'system_prompt': 'Answer plainly.',
            })
            channel = agent._create_ai_chat_channel('Callback physical lock')
            session = env['ai.session'].sudo().create({
                'agent_id': agent.id,
                'channel_id': channel.id,
            })
            message = channel.message_post(body='Release the row lock', message_type='comment')
            prepared = session._prepare_model_request(
                message._convert_to_parts(),
                context_snapshot={
                    'allowed_company_ids': env.companies.ids,
                    'active_company_ids': env.companies.ids,
                },
            )
            session_id = session.id
            channel_id = channel.id
            agent_id = agent.id

        def observe_submit(_connection, _route, payload, **_kwargs):
            with raw_cursor() as cr:
                cr.execute(
                    'SELECT id FROM ai_session WHERE id = %s FOR UPDATE NOWAIT',
                    [session_id],
                )
                self.assertEqual(cr.fetchone()[0], session_id)
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                session = env['ai.session'].sudo().browse(session_id)
                self.assertEqual(session.request_uuid, payload['request_uuid'])
                self.assertEqual(session.request_phase, 'prepared')
            return None

        with (
            raw_cursor() as cr,
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                side_effect=observe_submit,
            ),
        ):
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            acknowledgement = env['ai.session'].browse(prepared['session_id'])._submit_prepared_request(prepared['request_uuid'])

        self.assertEqual(acknowledgement['request_uuid'], prepared['request_uuid'])
        with raw_cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            session = env['ai.session'].sudo().browse(session_id)
            self.assertEqual(session.request_phase, 'submitted')
            session.unlink()
            env['discuss.channel'].browse(channel_id).unlink()
            env['ai.agent'].browse(agent_id).unlink()
