# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import copy
import json

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai.utils.ai_utils import UserInputResponse
from odoo.addons.mail.tools.discuss import Store

from .common import apply_iap_result


def tool_call(name, call_id, **args):
    return {'type': 'tool_call', 'name': name, 'call_id': call_id, 'args': args}


@tagged('post_install', '-at_install')
class TestAISessionSubagents(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.child_agent = cls.env['ai.agent'].create({
            'name': 'Foreground specialist',
            'subtitle': 'Find the delegated answer.',
            'system_prompt': 'Private specialist instructions.',
            'skill_ids': [Command.clear()],
        })
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Foreground coordinator',
            'system_prompt': 'Coordinate the answer.',
            'allowed_agent_ids': [Command.set(cls.child_agent.ids)],
            'skill_ids': [Command.clear()],
        })
        cls.channel = cls.agent._create_ai_chat_channel('Foreground tests')
        cls.session = cls.env['ai.session'].sudo().create({
            'agent_id': cls.agent.id,
            'channel_id': cls.channel.id,
        })
        cls.create_tool = cls.env.ref('ai.ir_actions_server_create_records')
        cls.context_snapshot = {
            'allowed_company_ids': cls.env.companies.ids,
            'active_company_ids': cls.env.companies.ids,
            'lang': 'en_US',
        }

    def _prepare(self, session=None, text='Parent-only conversation'):
        session = self.session if session is None else session
        session.with_context(**self.context_snapshot)._prepare_model_request(
            [{'type': 'text', 'text': text}],
            context_snapshot=self.context_snapshot,
        )
        return session

    def _apply(self, session, *content):
        return apply_iap_result(session, session.request_uuid, {
            'kind': 'success',
            'message': {'role': 'assistant', 'content': list(content)},
        })

    def _start(self, call_id, **args):
        return tool_call('start_session', call_id, **{
            'agent_id': self.child_agent.id,
            'message': f'Delegated work {call_id}',
            **args,
        })

    def _children(self, parent=None):
        parent = self.session if parent is None else parent
        return self.env['ai.session'].sudo().search([
            ('parent_session_id', '=', parent.id),
            ('agent_id', '!=', False),
        ], order='id')

    def _create_contact(self, call_id, name):
        return tool_call(self.create_tool.ai_tool_name, call_id,
            explanation=f'Create {name}?', model_name='res.partner',
            preview_menu_id=False,
            values=[{'field_values': [{'field': 'name', 'value': name}]}],
        )

    def _complete(self, child, text):
        self._apply(child, {'type': 'text', 'text': text})
        self.assertEqual(child.loop_state, 'ready')
        self.assertEqual(child.exchange_result['status'], 'completed')
        return child.parent_session_id._merge_child_result(child)

    def _child_result(self, result):
        return json.loads(result['result'][0]['text'])

    def _results(self, session=None):
        session = self.session if session is None else session
        return [part for message in session.request_payload['messages']
                for part in message['content']
                if part.get('type') == 'tool_result']

    def test_fresh_child_uses_own_prompt_and_explicit_attachments(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'delegated.txt',
            'raw': b'Explicitly delegated attachment contents.',
            'mimetype': 'text/plain',
            'res_model': 'discuss.channel',
            'res_id': self.channel.id,
        })
        self.session.write({'res_model': 'res.partner', 'res_id': self.env.user.partner_id.id})
        self._prepare()
        catalogue = self.session.request_payload['instructions']
        self.assertIn(self.child_agent.name, catalogue)
        self.assertIn(self.child_agent.subtitle, catalogue)
        self.assertIn(str(self.child_agent.id), catalogue)
        self.assertNotIn(self.child_agent.system_prompt, catalogue)
        self._apply(self.session, self._start('child', attachment_ids=attachment.ids))
        child = self._children()
        self.assertEqual(len(child), 1)
        self.assertEqual(child.channel_id, self.channel)
        self.assertEqual(child.request_user_id, self.session.request_user_id)
        self.assertEqual(child.request_guest_id, self.session.request_guest_id)
        self.assertEqual(child.request_context, self.session.request_context)
        self.assertEqual((child.res_model, child.res_id), (self.session.res_model, self.session.res_id))
        self.assertIn(self.child_agent.system_prompt, child.request_payload['instructions'])
        self.assertNotIn('Parent-only conversation', str(child._get_history()))
        self.assertIn('Delegated work child', str(child._get_history()))
        self.assertIn('Explicitly delegated attachment contents.', str(child.request_payload['messages']))
        self.assertFalse(child.exchange_result)
        self.assertEqual(self.session.pending_tool_call['pending_results'], [{
            'tool_name': 'start_session', 'tool_call_id': 'child',
            'child_session_id': child.id,
        }])

    def test_parallel_children_merge_in_call_order_once(self):
        self._prepare()
        parent_uuid = self.session.request_uuid
        self._apply(self.session, self._start('A'), self._start('B'))
        first, second = self._children()
        self.assertEqual(self.session.loop_state, 'waiting_child')
        visible_messages = self.channel.message_ids
        self._complete(second, 'Second finished first')
        self.assertEqual(self.session.request_uuid, parent_uuid)
        self.assertEqual(self.session.loop_state, 'waiting_child')
        pending = self.session.pending_tool_call['pending_results']
        self.assertEqual(pending[0]['child_session_id'], first.id)
        self.assertEqual(self._child_result(pending[1])['session_id'], second.id)
        self._complete(first, 'First finished last')
        next_uuid = self.session.request_uuid
        self.assertNotEqual(next_uuid, parent_uuid)
        self.assertEqual(self.session.loop_state, 'waiting_model')
        results = self._results()
        self.assertEqual([item['tool_call_id'] for item in results], ['A', 'B'])
        self.assertEqual([self._child_result(item)['session_id'] for item in results], [first.id, second.id])
        self.assertIn('First finished last', self._child_result(results[0])['message'])
        self.assertIn('Second finished first', self._child_result(results[1])['message'])
        events = self.session.event_ids
        self.session._merge_child_result(first)
        self.session._merge_child_result(second)
        self.assertEqual(self.session.request_uuid, next_uuid)
        self.assertEqual(self.session.event_ids, events)
        self.assertEqual(self.channel.message_ids, visible_messages)

    def test_confirmation_preserves_children_and_batch_budget_across_resume(self):
        counter = self.env['ir.actions.server'].create({
            'name': 'Foreground counter', 'ai_tool_name': 'foreground_counter',
            'ai_tool_description': 'Count completed ordinary calls.',
            'ai_tool_schema': '{"type":"object","properties":{},"required":[]}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code', 'use_in_ai': True,
            'code': "ai['state']['runs'] = ai['state'].get('runs', 0) + 1\nai['result'] = 'counted'",
        })
        self.env['ir.config_parameter'].sudo().set_int('ai.max_tool_calls_per_call', 2)
        self.session.state = {'available_tools': [counter.id, self.create_tool.id]}
        self._prepare()
        self._apply(self.session,
            self._start('A'), tool_call(counter.ai_tool_name, 'count-before'),
            self._start('B'), self._create_contact('create', 'Foreground budget contact'),
            tool_call(counter.ai_tool_name, 'over-budget'), self._start('C'),
        )
        first, second = self._children()
        self.assertEqual(self.session.loop_state, 'waiting_confirmation')
        self.assertEqual(self.session.state['runs'], 1)
        pending = copy.deepcopy(self.session.pending_tool_call)
        token = self.session.resume_token
        self._complete(second, 'Ready while parent asks')
        self.assertEqual(self.session.resume_token, token)
        self.assertEqual(self.session.pending_tool_call['call_id'], pending['call_id'])
        self.assertEqual(self.session.pending_tool_call['user_input_request'], pending['user_input_request'])
        self.assertEqual(self.session.loop_state, 'waiting_confirmation')
        self.session._resume_pending_interaction(
            self.session.request_uuid, token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        self.assertEqual(len(self._children()), 3)
        self.assertEqual(self.session.loop_state, 'waiting_child')
        self.assertEqual(self.session.state['runs'], 1)
        results = self.session.pending_tool_call['pending_results']
        self.assertEqual([item['tool_call_id'] for item in results],
                         ['A', 'count-before', 'B', 'create', 'over-budget', 'C'])
        self.assertFalse(results[4]['success'])
        self.assertTrue(results[3]['success'])
        self.assertEqual(results[0]['child_session_id'], first.id)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', 'Foreground budget contact'),
        ]), 1)

    def test_decline_waits_for_launched_child_without_dispatching_remainder(self):
        self.child_agent.allowed_agent_ids = self.child_agent
        self._prepare()
        self._apply(self.session, self._start('declining-parent'))
        root = self.session
        self.session = self._children()
        self.session.state = {'available_tools': self.create_tool.ids}
        request_uuid = self.session.request_uuid
        self._apply(self.session, self._start('A'),
            self._create_contact('decline', 'Foreground declined contact'), self._start('B'),
        )
        child = self._children()
        self.session._resume_pending_interaction(
            request_uuid, self.session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.DECLINE},
        )
        self.assertEqual(self.session.loop_state, 'waiting_child')
        self.assertEqual(self._children(), child)
        self.assertFalse(self.session.exchange_result)
        self._complete(child, 'Already launched work completed')
        self.assertEqual(self.session.loop_state, 'ready')
        self.assertEqual(self.session.exchange_result['status'], 'declined')
        root._merge_child_result(self.session)
        self.assertEqual(self._child_result(self._results(root)[0])['status'], 'declined')
        self.assertEqual(self.session.request_uuid, request_uuid)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Foreground declined contact'),
        ]))

    def test_allowlist_and_public_argument_validation(self):
        self._prepare()
        self._apply(self.session,
            self._start('unlisted', agent_id=self.agent.id),
            self._start('structured-message', message={'text': 'Not a string'}),
            self._start('string-attachment', attachment_ids=['1']),
            self._start('boolean-attachment', attachment_ids=[True]),
            tool_call('start_session', 'missing-message', agent_id=self.child_agent.id),
        )
        self.assertFalse(self._children())
        results = self._results()
        self.assertEqual(len(results), 5)
        self.assertTrue(all(not result['success'] for result in results))
        self.agent.allowed_agent_ids = False
        self.assertFalse(self.session._get_delegation_tools())

    def test_four_levels_allow_repeated_agent_identity(self):
        self.agent.allowed_agent_ids = self.agent
        self._prepare()
        parent = self.session
        for depth in (2, 3, 4):
            self._apply(parent, self._start(str(depth), agent_id=self.agent.id))
            child = self._children(parent)
            self.assertEqual(len(child), 1)
            self.assertEqual(child.agent_id, self.agent)
            self.assertNotEqual(child, parent)
            names = {tool['name'] for tool in child.request_payload['tools']}
            if depth < 4:
                self.assertTrue({'start_session', 'continue_session'} <= names)
            else:
                self.assertFalse({'start_session', 'continue_session'} & names)
                self.assertIn('ai_tool_load_skills', names)
            parent = child
        self._apply(parent, self._start('too-deep', agent_id=self.agent.id))
        self.assertFalse(self._children(parent))
        self.assertFalse(self._results(parent)[0]['success'])

    def test_continue_idle_direct_child_preserves_history_and_fences_old_uuid(self):
        self._prepare()
        self._apply(self.session, self._start('start'))
        child = self._children()
        old_uuid = child.request_uuid
        self._complete(child, 'First exchange answer')
        self._apply(self.session, tool_call(
            'continue_session', 'continue', session_id=child.id,
            message='Follow up on the first answer',
        ))
        self.assertEqual(self._children(), child)
        self.assertEqual(child.parent_session_id, self.session)
        self.assertFalse(child.exchange_result)
        self.assertEqual(child.loop_state, 'waiting_model')
        new_uuid = child.request_uuid
        self.assertNotEqual(new_uuid, old_uuid)
        self.assertIn('First exchange answer', str(child.request_payload['messages']))
        self.assertIn('Follow up on the first answer', str(child.request_payload['messages']))
        history = copy.deepcopy(child._get_history())
        apply_iap_result(child, old_uuid, {
            'kind': 'success',
            'message': {'role': 'assistant', 'content': [
                {'type': 'text', 'text': 'Stale exchange callback'},
            ]},
        })
        self.assertEqual(child.request_uuid, new_uuid)
        self.assertEqual(child._get_history(), history)
        self.assertFalse(child.exchange_result)
        self._complete(child, 'Follow-up answer')
        result = self._results()[-1]
        self.assertEqual(result['tool_name'], 'continue_session')
        self.assertEqual(self._child_result(result)['session_id'], child.id)
        self.assertIn('Follow-up answer', self._child_result(result)['message'])

    def test_continue_rejects_busy_child_and_another_parents_child(self):
        self._prepare()
        self._apply(self.session, self._start('start'), tool_call(
            'continue_session', 'busy', session_id=-1, message='Unavailable',
        ))
        child = self._children()
        other = self.env['ai.session'].sudo().create({
            'agent_id': self.agent.id, 'channel_id': self.channel.id,
        })
        self._prepare(other)
        self._apply(other, tool_call(
            'continue_session', 'not-direct', session_id=child.id,
            message='Another parent must not take this child',
        ))
        self.assertFalse(self._children(other))
        self.assertFalse(self._results(other)[-1]['success'])
        self.assertEqual(child.parent_session_id, self.session)
        self._complete(child, 'Ready for another exchange')
        self._apply(self.session,
            tool_call('continue_session', 'first', session_id=child.id, message='One exchange'),
            tool_call('continue_session', 'busy', session_id=child.id, message='Do not queue'),
        )
        pending = self.session.pending_tool_call['pending_results']
        self.assertEqual(pending[0]['child_session_id'], child.id)
        self.assertFalse(pending[1]['success'])
        self.assertNotIn('Do not queue', str(child._get_history()))

    def test_failed_child_does_not_cancel_its_sibling(self):
        self._prepare()
        self._apply(self.session, self._start('failure'), self._start('success'))
        failed, sibling = self._children()
        apply_iap_result(failed, failed.request_uuid, {
            'kind': 'failure', 'code': 'request_failed',
        })
        self.assertEqual(failed.loop_state, 'ready')
        self.assertEqual(failed.exchange_result['status'], 'failed')
        self.session._merge_child_result(failed)
        self.assertEqual(self.session.loop_state, 'waiting_child')
        self.assertEqual(sibling.loop_state, 'waiting_model')
        self._complete(sibling, 'Sibling still completed')
        results = self._results()
        self.assertEqual([self._child_result(result)['status'] for result in results],
                         ['failed', 'completed'])
        self.assertEqual(self.session.loop_state, 'waiting_model')

    def test_tool_terminal_answer_preserves_image_and_sources(self):
        image = self.env['ai.attachment.vacuum']._create_attachments_and_mark_unused([{
            'name': 'child-result.png', 'mimetype': 'image/png',
            'raw': base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
            ),
        }])
        image_signature = 'image-model-only-signature'
        final_parts = [
            {'type': 'text', 'text': 'Actual final tool answer'},
            {'type': 'inline_data', 'mimetype': 'image/png',
             'data': image.raw.to_base64(), 'metadata': {'attachment_id': image.id},
             'provider_data': {'gemini': {'thought_signature': image_signature}}},
        ]
        final_tool = self.env['ir.actions.server'].create({
            'name': 'Foreground final answer', 'ai_tool_name': 'foreground_final',
            'ai_tool_description': 'Return the processed final answer.',
            'ai_tool_schema': '{"type":"object","properties":{},"required":[]}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code', 'use_in_ai': True,
            'code': f"ai['result'] = 'Intermediate tool result'\nai['final_message'] = {final_parts!r}",
        })
        self._prepare()
        self._apply(self.session, self._start('answer'))
        child = self._children()
        sources = {'1': {'title': 'Reference', 'url': 'https://example.com/reference'}}
        child.state = {'available_tools': final_tool.ids, 'web_sources': sources}
        before = self.channel.message_ids
        self._apply(child, {'type': 'text', 'text': 'Raw model preamble'},
                    tool_call(final_tool.ai_tool_name, 'final'))
        result = child.exchange_result
        self.assertEqual(child.loop_state, 'ready')
        self.assertIn('Actual final tool answer', result['message'])
        self.assertNotIn('Raw model preamble', result['message'])
        self.assertNotIn('Intermediate tool result', result['message'])
        self.assertEqual(result['attachment_ids'], image.ids)
        self.assertFalse(self.env['ai.attachment.vacuum'].search([
            ('attachment_id', '=', image.id),
        ]))
        self.assertEqual(result['sources'], sources)
        history = child._get_history()
        self.assertEqual([message['role'] for message in history], ['user', 'assistant', 'user'])
        retained_result = history[-1]['content'][0]
        self.assertEqual(retained_result['type'], 'tool_result')
        self.assertIn('Actual final tool answer', str(retained_result['result']))
        self.assertTrue(any(part.get('type') == 'inline_data' for part in retained_result['result']))
        self.assertNotIn(image_signature, str([message for message in history if message['role'] == 'assistant']))
        self.session._merge_child_result(child)
        self.assertEqual(self._child_result(self._results()[0])['attachment_ids'], image.ids)
        self.assertTrue(any(
            part.get('type') == 'inline_data'
            for part in self._results()[0]['result']
        ))
        self.assertEqual(self.channel.message_ids, before)
        self._apply(self.session, tool_call(
            'continue_session', 'image-follow-up', session_id=child.id,
            message='Revise the image from the previous answer',
        ))
        self.assertIn('Actual final tool answer', str(child.request_payload['messages']))
        self.assertTrue(any(
            part.get('type') == 'inline_data'
            for tool_result in self._results(child)
            for part in tool_result['result']
        ))
        for session in (self.session, child):
            assistant_messages = [message for message in session.request_payload['messages']
                                  if message['role'] == 'assistant']
            self.assertNotIn(image_signature, str(assistant_messages))
            self.assertFalse(any(part.get('type') == 'inline_data'
                                 for message in assistant_messages for part in message['content']))

    def test_deleting_root_removes_children_and_their_event_histories(self):
        self._prepare()
        self._apply(self.session, self._start('child'))
        child = self._children()
        self._complete(child, 'Retained child answer')
        events = self.session.event_ids | child.event_ids
        self.assertTrue(child.exists())
        self.session.unlink()
        self.assertFalse(child.exists())
        self.assertFalse(events.exists())

    def test_delegation_keeps_actor_permissions_for_attachments_and_tool_effects(self):
        actor = new_test_user(self.env, login='foreground_actor', groups='base.group_user,base.group_partner_manager')
        self.channel._add_members(partner_ids=actor.partner_id.ids)
        private_channel = self.agent._create_ai_chat_channel('Not shared with the actor')
        private_attachment = self.env['ir.attachment'].create({
            'name': 'private.txt', 'raw': b'Private attachment must stay private.',
            'mimetype': 'text/plain',
            'res_model': 'discuss.channel', 'res_id': private_channel.id,
        })
        effect = self.env['ir.actions.server'].create({
            'name': 'Foreground actor effect', 'ai_tool_name': 'foreground_actor_effect',
            'ai_tool_description': 'Create a contact as the requesting user.',
            'ai_tool_schema': '{"type":"object","properties":{},"required":[]}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code', 'use_in_ai': True,
            'code': "partner = env['res.partner'].create({'name': 'Foreground actor contact'})\nai['result'] = {'user_id': env.uid, 'sudo': env.su, 'partner_id': partner.id}",
        })
        self.session = self.session.with_user(actor).sudo()
        self.context_snapshot = {**self.context_snapshot,
            'allowed_company_ids': actor.company_ids.ids,
            'active_company_ids': actor.company_ids.ids,
        }
        self._prepare()
        self._apply(self.session,
            self._start('private', attachment_ids=private_attachment.ids), self._start('allowed'),
        )
        child = self._children()
        self.assertEqual(len(child), 1)
        self.assertEqual(child.request_user_id, actor)
        self.assertFalse(self.session.pending_tool_call['pending_results'][0]['success'])
        self.assertNotIn('Private attachment must stay private.', str(child.request_payload))
        child = child.with_user(actor).sudo().with_context(**child.request_context)
        child.state = {'available_tools': effect.ids}
        self._apply(child, tool_call(effect.ai_tool_name, 'effect'))
        result = json.loads(self._results(child)[-1]['result'][0]['text'])
        self.assertEqual(result['user_id'], actor.id)
        self.assertFalse(result['sudo'])
        self.assertEqual(self.env['res.partner'].browse(result['partner_id']).create_uid, actor)

    def test_continue_does_not_clear_a_terminal_result_before_its_marker_is_merged(self):
        self._prepare()
        self._apply(self.session, self._start('start'))
        child = self._children()
        self._complete(child, 'First exchange')
        self.session.state = {'available_tools': self.create_tool.ids}
        self._apply(self.session,
            tool_call('continue_session', 'second', session_id=child.id, message='Second exchange'),
            self._create_contact('pause', 'Foreground unmerged contact'),
            tool_call('continue_session', 'too-early', session_id=child.id, message='Third exchange'),
        )
        self._apply(child, {'type': 'text', 'text': 'Undelivered second answer'})
        child_uuid = child.request_uuid
        result = copy.deepcopy(child.exchange_result)
        self.assertEqual(child.loop_state, 'ready')
        self.session._resume_pending_interaction(
            self.session.request_uuid, self.session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        self.assertEqual(child.request_uuid, child_uuid)
        self.assertEqual(child.exchange_result, result)
        pending = self.session.pending_tool_call['pending_results']
        self.assertEqual(pending[0]['child_session_id'], child.id)
        self.assertFalse(pending[2]['success'])
        self.session._merge_child_result(child)
        self.assertEqual(self.session.loop_state, 'waiting_model')
        self.assertIn('Undelivered second answer', self._child_result(self._results()[1])['message'])

    def test_source_owned_question_and_client_wait_do_not_settle_children(self):
        client_tool = self.env['ir.actions.server'].create({
            'name': 'Foreground browser result', 'ai_tool_name': 'foreground_browser_result',
            'ai_tool_description': 'Read the current browser view.',
            'ai_tool_schema': '{"type":"object","properties":{},"required":[]}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code', 'use_in_ai': True,
            'code': "ai['result'] = {'client_tool': {'name': 'foreground_view', 'params': {}}}",
        })
        question_tool = self.env.ref('ai.ir_actions_server_ask_user_question')
        self._prepare()
        self._apply(self.session, self._start('question'), self._start('browser'))
        question, browser = self._children()
        browser.state = {'available_tools': client_tool.ids}
        pending = copy.deepcopy(self.session.pending_tool_call)
        self._apply(question, tool_call(question_tool.ai_tool_name, 'question',
            question='Which option?', choices=['Yes', 'No'],
            multi_select=False, allow_free_text=False,
        ))
        self._apply(browser, tool_call(client_tool.ai_tool_name, 'browser'))
        self.assertEqual(question.loop_state, 'waiting_answer')
        self.assertEqual(browser.loop_state, 'waiting_client_result')
        self.assertFalse(question.exchange_result)
        self.assertFalse(browser.exchange_result)
        self.assertEqual(self.session.pending_tool_call, pending)
        self.assertEqual(self.session.loop_state, 'waiting_child')
        browser._resume_pending_interaction(
            browser.request_uuid, browser.resume_token,
            {'kind': 'client_result', 'value': {'view': 'browser result'}},
        )
        self.assertEqual(browser.loop_state, 'waiting_model')
        self.assertEqual(question.loop_state, 'waiting_answer')
        self.assertEqual(self.session.pending_tool_call, pending)

    def test_unavailable_website_child_resume_keeps_pending_interaction(self):
        values = self.env['ai.agent'].action_launch_ai_chat(interface_key='website_builder_ai')
        self.session = self.env['ai.session'].sudo().search([
            ('channel_id', '=', values['ai_channel_id']),
        ])
        self.session.agent_id.allowed_agent_ids = self.child_agent
        self.context_snapshot = {**self.context_snapshot,
            'current_view_info': {'website_page': {'is_page_ai_editable': True}},
        }
        self.session = self.session.with_context(**self.context_snapshot)
        self._prepare()
        self._apply(self.session, self._start('website'))
        child = self._children().with_context(**self.context_snapshot)
        child.state = {'available_tools': self.create_tool.ids}
        self._apply(child, self._create_contact('website-confirm', 'Foreground website contact'))
        pending = copy.deepcopy(child.pending_tool_call)
        token = child.resume_token
        self.assertFalse(child.exchange_result)
        with self.assertRaises(UserError):
            child.with_context(current_view_info={})._resume_pending_interaction(
                child.request_uuid, token,
                {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
                context_snapshot={'current_view_info': {}},
            )
        self.assertEqual(child.loop_state, 'waiting_confirmation')
        self.assertEqual(child.resume_token, token)
        self.assertEqual(child.pending_tool_call, pending)
        self.assertFalse(child.exchange_result)

    def test_declined_child_without_descendants_returns_refusal_information(self):
        self._prepare()
        self._apply(self.session, self._start('declining'))
        child = self._children()
        child.state = {'available_tools': self.create_tool.ids}
        self._apply(child, self._create_contact('decline', 'Foreground immediately declined'))
        child._resume_pending_interaction(
            child.request_uuid, child.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.DECLINE},
        )
        self.assertEqual(child.loop_state, 'ready')
        self.assertEqual(child.exchange_result['status'], 'declined')
        self.assertTrue(child.exchange_result['message'])
        self.session._merge_child_result(child)
        result = self._child_result(self._results()[0])
        self.assertEqual(result['status'], 'declined')
        self.assertTrue(result['message'])

    def test_descendant_store_sanitizes_question_markup_and_preserves_confirmation_table(self):
        self._prepare()
        self._apply(self.session, self._start('question'), self._start('confirmation'))
        question, confirmation = self._children()
        ask = self.env.ref('ai.ir_actions_server_ask_user_question')
        self._apply(question, tool_call(ask.ai_tool_name, 'ask',
            question='Which option?', choices=['First', 'Second'],
            multi_select=False, allow_free_text=False,
        ))
        confirmation.state = {'available_tools': self.create_tool.ids}
        self._apply(confirmation, self._create_contact('confirm', 'Formatted contact'))
        bodies = [
            '<p onclick="alert(1)" custom-untrusted-attribute="bad" '
            'style="position:fixed;inset:0;z-index:9999">Which <strong>option</strong>?</p>'
            '<img src="x" onerror="alert(2)"><script>alert(3)</script>'
            '<a href="javascript:alert(4)">Unsafe link</a>',
            '<p><strong>Create this contact?</strong></p><table><thead><tr>'
            '<th>Field</th><th>Value</th></tr></thead><tbody><tr>'
            '<td>Name</td><td>Formatted contact</td></tr></tbody></table>',
        ]
        rendered = []
        for session, body in zip((question, confirmation), bodies):
            pending = copy.deepcopy(session.pending_tool_call)
            pending['user_input_request']['body'] = body
            session.pending_tool_call = pending
            data = Store().add(session, '_store_session_fields')._build_result()
            request = next(item for item in data['ai.session'] if item['id'] == session.id)['userInputRequest']
            self.assertEqual(request['body'][0], 'markup')
            self.assertEqual(request['requestUuid'], session.request_uuid)
            self.assertEqual(request['resumeToken'], session.resume_token)
            rendered.append(str(request['body'][1]))
        for unsafe in ('<script', 'onclick', 'onerror', 'javascript:',
                       'custom-untrusted-attribute', 'position', 'inset', 'z-index'):
            self.assertNotIn(unsafe, rendered[0])
        self.assertIn('<strong>option</strong>', rendered[0])
        self.assertIn('<strong>Create this contact?</strong>', rendered[1])
        self.assertIn('<table>', rendered[1])
        self.assertIn('<th>Field</th>', rendered[1])
        self.assertIn('<td>Formatted contact</td>', rendered[1])
