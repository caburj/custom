# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy
from unittest.mock import patch

import requests

from odoo import api, Command
from odoo.tests import HttpCase, tagged, TransactionCase
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import AiSession
from odoo.addons.ai.utils.ai_utils import UserInputResponse
from odoo.addons.base.tests.files import JPG_B64, JPG_RAW, PNG_B64, PNG_RAW

from .common import apply_iap_result
from .test_ai_web_search_continuation import TRANSPORT, WebSearchFixture, assistant_text


def assistant_image(data=PNG_B64, mimetype='image/png'):
    return {'role': 'assistant', 'content': [
        {'type': 'text', 'text': 'Provider image commentary.'},
        {'type': 'inline_data', 'data': data, 'mimetype': mimetype},
    ]}


class ImageGenerationFixture(WebSearchFixture):
    fixture_name = 'Image generation'
    fixture_key = 'image_generation'
    fixture_skill = 'ai.ai_skill_generate_image'
    fixture_tool = 'ai.ir_actions_server_ai_generate_image'
    fixture_tool_key = 'image'
    fixture_prompt = 'Create a picture of a lighthouse.'
    fixture_instructions = 'Generate or edit the requested image.'
    feedback = 'Here is your lighthouse. Would you like any changes?'

    @property
    def image_title(self):
        return f'Continuation lighthouse {self.session_id}'

    def _call(self, name, call_id=None, args=None):
        if name == 'image':
            args = {
                'prompt': self.fixture_prompt,
                'images_paths': [],
                'image_title': self.image_title,
                'feedback': self.feedback,
                'aspect_ratio': '16:9',
                **(args or {}),
            }
        return super()._call(name, call_id=call_id, args=args)

    def _generated_attachments(self, env=None):
        return (env or self.env)['ir.attachment'].sudo().search([
            ('name', '=', f'AI Generated {self.image_title}'),
        ])


@tagged('post_install', '-at_install')
class TestAIImageGenerationContinuation(ImageGenerationFixture, TransactionCase):
    def setUp(self):
        super().setUp()
        self._create_fixture(self.env(user=self.env.ref('base.user_admin').id))

    def test_image_prepares_headless_child_and_retains_parent_intent(self):
        parent = self._session()
        parent_payload = copy.deepcopy(parent.request_payload)
        calls = [self._call('prefix'), self._call('image', args={'aspect_ratio': '32:18'}), self._call('suffix')]
        outcome = self._apply_calls(calls)
        child = self._session(outcome["prepared_requests"][0]["session_id"])

        self.assertEqual(outcome['response'], {
            'request_uuid': self.parent_request_uuid, 'responseState': 'running',
        })
        self.assertEqual(parent.loop_state, 'waiting_child')
        self.assertFalse(parent.request_phase)
        self.assertFalse(parent.resume_token)
        self.assertEqual(parent.request_uuid, self.parent_request_uuid)
        self.assertEqual(parent.request_payload, parent_payload)
        self.assertEqual(parent.request_result, {
            'kind': 'success', 'message': {'role': 'assistant', 'content': calls},
        })
        self.assertEqual(parent.pending_tool_call['call_id'], 'image')
        self.assertEqual([part['tool_call_id'] for part in parent.pending_tool_call['pending_results']], ['prefix', 'image'])
        self.assertEqual(parent.pending_tool_call['pending_results'][-1], {
            'tool_name': self.tool_names['image'], 'tool_call_id': 'image', 'child_session_id': child.id,
        })
        self._assert_prefix_once(parent)
        self.assertNotIn('suffix_runs', parent.state)
        self.assertFalse(self._generated_attachments())
        self.assertEqual(child.parent_session_id, parent)
        self.assertFalse(child.agent_id)
        self.assertFalse(child.channel_id)
        self.assertFalse(child.res_model)
        self.assertFalse(child.res_id)
        self.assertFalse(child.event_ids)
        self.assertEqual(parent.channel_id.ai_session_ids, parent)
        self.assertEqual(child.request_user_id.id, self.actor_id)
        self.assertFalse(child.request_guest_id)
        self.assertEqual(child.request_context, self.context_snapshot)
        self.assertEqual(child.request_callback_url, parent.request_callback_url)
        self.assertEqual(child.request_round, 1)
        self.assertEqual(child.request_round_limit, 1)
        self.assertEqual(child.request_phase, 'prepared')
        self.assertEqual(child.continuation_data, {
            'continuation_type': 'image_generation',
        })
        payload = child.request_payload
        self.assertEqual(set(payload), {
            'messages', 'instructions', 'tools', 'aspect_ratio', 'web_grounding', 'image_generation',
        })
        self.assertEqual(payload['messages'], [{
            'role': 'user', 'content': [{'type': 'text', 'text': self.fixture_prompt}],
        }])
        self.assertEqual(payload['tools'], [])
        self.assertEqual(payload['aspect_ratio'], '16:9')
        self.assertIs(payload['web_grounding'], False)
        self.assertIs(payload['image_generation'], True)
        self.assertIn('no visible or readable text', payload['instructions'])
        self.assertNotIn('odoo_current_context', str(payload))

    def test_image_final_creates_reusable_attachments_once_without_another_round(self):
        outcome = self._apply_calls([self._call('image')])
        child = self._session(outcome["prepared_requests"][0]["session_id"])
        message = assistant_image()
        message['content'].append({'type': 'inline_data', 'data': JPG_B64, 'mimetype': 'image/jpeg'})
        original_post = AiSession._post_ai_response
        with patch.object(AiSession, '_post_ai_response', autospec=True, side_effect=original_post) as post:
            finished = self._apply(child, message)
        parent = self._session()

        self.assertEqual(finished['response'], {
            'request_uuid': self.parent_request_uuid, 'responseState': 'idle',
        })
        self.assertNotIn('prepared', finished)
        self.assertEqual(parent.loop_state, 'ready')
        self.assertEqual(child.loop_state, 'ready')
        self.assertFalse(parent.request_phase)
        self.assertFalse(child.request_phase)
        self.assertFalse(parent.pending_tool_call)
        self.assertEqual(parent.request_round, 1)
        self.assertEqual(parent.request_uuid, self.parent_request_uuid)
        self.assertEqual(child.request_result, {'kind': 'success', 'message': message})
        attachments = self._generated_attachments()
        self.assertEqual(len(attachments), 2)
        self.assertEqual({att.mimetype: att.raw.content for att in attachments}, {
            'image/png': PNG_RAW, 'image/jpeg': JPG_RAW,
        })
        self.assertTrue(all(att.description == f'AI Generated {self.image_title}' for att in attachments))
        self.assertTrue(all(att.create_uid.id == self.actor_id and not att.public for att in attachments))
        visible_message = parent.channel_id.message_ids[0]
        self.assertEqual(set(visible_message.attachment_ids.ids), set(attachments.ids))
        self.assertIn(self.feedback, visible_message.body)
        self.assertNotIn('Provider image commentary', visible_message.body)
        post.assert_called_once()
        image_parts = [part for part in post.call_args.args[1] if part['type'] == 'inline_data']
        self.assertEqual({part['metadata']['attachment_id'] for part in image_parts}, set(attachments.ids))
        for part in image_parts:
            self.assertEqual(part['metadata']['image_path'], f"/web/image/ir.attachment/{part['metadata']['attachment_id']}/raw")
        results = self._results(parent)
        self.assertEqual([part['tool_call_id'] for part in results], ['image'])
        self.assertTrue(results[0]['success'])
        self.assertEqual(results[0]['result'][0]['text'], 'The image has been generated successfully')
        counts = (len(parent.event_ids), len(parent.channel_id.message_ids))
        self._apply(child, message)
        self.assertEqual(self._generated_attachments(), attachments)
        self.assertEqual((len(parent.event_ids), len(parent.channel_id.message_ids)), counts)

        # Edit the generated attachment through the same public tool contract.
        image_path = next(part['metadata']['image_path'] for part in image_parts if part['mimetype'] == 'image/png')
        edit_prompt = parent.channel_id.message_post(body='Make the lighthouse blue.', message_type='comment')
        parent.with_context(self.context_snapshot)._prepare_agent_request(edit_prompt._convert_to_parts())
        edit = self._apply_calls([self._call('image', args={
            'prompt': 'Make the lighthouse blue.', 'images_paths': [image_path],
        })])
        edit_child = self._session(edit["prepared_requests"][0]["session_id"])
        edit_parts = edit_child.request_payload['messages'][0]['content']
        self.assertEqual(edit_parts[0], {'type': 'text', 'text': 'Make the lighthouse blue.'})
        self.assertEqual(len(edit_parts), 2)
        self.assertEqual(edit_parts[1]['data'], PNG_B64)
        self.assertEqual(edit_parts[1]['mimetype'], 'image/png')
        self.assertEqual(edit_parts[1]['metadata']['image_path'], image_path)
        self._apply(edit_child, assistant_image())
        self.assertEqual(len(self._generated_attachments()), 3)
        self.assertEqual(parent.loop_state, 'ready')

    def test_text_only_image_result_posts_clarification_without_attachments(self):
        outcome = self._apply_calls([self._call('image')])
        child = self._session(outcome["prepared_requests"][0]["session_id"])
        finished = self._apply(child, assistant_text('What should the lighthouse look like?'))
        parent = self._session()

        self.assertEqual(finished['response']['responseState'], 'idle')
        self.assertNotIn('prepared', finished)
        self.assertEqual(parent.loop_state, 'ready')
        self.assertEqual(child.loop_state, 'ready')
        self.assertEqual(parent.request_round, 1)
        self.assertFalse(self._generated_attachments())
        self.assertFalse(parent.channel_id.message_ids[0].attachment_ids)
        self.assertIn('What should the lighthouse look like?', parent.channel_id.message_ids[0].body)
        self.assertNotIn(self.feedback, parent.channel_id.message_ids[0].body)
        self.assertEqual(self._results(parent)[0]['result'][0]['text'], 'What should the lighthouse look like?')

    def test_image_preserves_order_across_confirmation_client_and_question_suffix(self):
        names = ['prefix', 'image', 'confirmation', 'client', 'question', 'suffix']
        outcome = self._apply_calls([self._call(name) for name in names])
        child = self._session(outcome["prepared_requests"][0]["session_id"])
        waiting = self._apply(child, assistant_image())
        parent = self._session()
        self.assertEqual(waiting['response']['responseState'], 'waiting_user')
        self.assertEqual(parent.loop_state, 'waiting_confirmation')
        self.assertFalse(parent.pending_tool_call.get('final_message'))
        token = parent.resume_token
        parent._resume_pending_interaction(
            token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        self.assertEqual(parent.loop_state, 'waiting_client_result')
        self.assertNotEqual(parent.resume_token, token)
        parent._resume_pending_interaction(
            parent.resume_token, {'kind': 'client_result', 'value': False},
        )
        self.assertEqual(parent.loop_state, 'waiting_answer')
        resumed = parent._resume_pending_interaction(
            parent.resume_token, {'kind': 'question', 'value': ['Continue']},
        )
        results = self._results(parent)
        self.assertEqual([part['tool_call_id'] for part in results], names)
        self.assertTrue(all(part['success'] for part in results))
        self.assertEqual(results[3]['result'][0]['text'], 'false')
        self._assert_prefix_once(parent)
        self.assertEqual(parent.state['confirmation_runs'], 1)
        self.assertEqual(parent.state['client_runs'], 1)
        self.assertEqual(parent.state['suffix_runs'], 1)
        self.assertEqual(parent.request_round, 2)
        self.assertEqual(resumed["prepared_requests"][0]["session_id"], parent.id)
        self.assertFalse(any(self.feedback in message.body for message in parent.channel_id.message_ids))
        self.assertEqual(len(self._generated_attachments()), 1)

    def test_sequential_images_keep_completed_prefix_and_only_the_last_final(self):
        outcome = self._apply_calls([
            self._call('prefix'), self._call('image', 'first-image'),
            self._call('image', 'second-image', {'feedback': 'Here is the second image.'}),
        ])
        first = self._session(outcome["prepared_requests"][0]["session_id"])
        next_image = self._apply(first, assistant_image())
        second = self._session(next_image["prepared_requests"][0]["session_id"])
        parent = self._session()

        self.assertNotEqual(first, second)
        self.assertEqual(parent.loop_state, 'waiting_child')
        self.assertEqual(second.parent_session_id, parent)
        self.assertEqual(parent.pending_tool_call['call_id'], 'second-image')
        self.assertEqual([part['tool_call_id'] for part in parent.pending_tool_call['pending_results']], [
            'prefix', 'first-image', 'second-image',
        ])
        self.assertEqual(parent.pending_tool_call['pending_results'][-1], {
            'tool_name': self.tool_names['image'], 'tool_call_id': 'second-image', 'child_session_id': second.id,
        })
        self.assertEqual(len(self._generated_attachments()), 1)
        self._assert_prefix_once(parent)
        self.assertFalse(any(self.feedback in message.body for message in parent.channel_id.message_ids))
        finished = self._apply(second, assistant_image(JPG_B64, 'image/jpeg'))
        self.assertEqual(finished['response']['responseState'], 'idle')
        self.assertEqual(parent.request_round, 1)
        self.assertEqual([part['tool_call_id'] for part in self._results(parent)], ['prefix', 'first-image', 'second-image'])
        self._assert_prefix_once(parent)
        self.assertEqual(len(self._generated_attachments()), 2)
        self.assertIn('Here is the second image.', parent.channel_id.message_ids[0].body)
        self.assertEqual(parent.channel_id.message_ids[0].attachment_ids.raw.content, JPG_RAW)

    def test_image_failure_balances_unexecuted_calls_and_finishes_both_sessions(self):
        for code in ('request_failed', 'insufficient_credit'):
            with self.subTest(code=code):
                self._create_fixture(self.env(user=self.env.ref('base.user_admin').id))
                outcome = self._apply_calls([self._call('prefix'), self._call('image'), self._call('suffix')])
                child = self._session(outcome["prepared_requests"][0]["session_id"])
                failure = {'kind': 'failure', 'code': code}
                with patch.object(self.registry['iap.account'], '_send_no_credit_notification', autospec=True) as notify:
                    finished = apply_iap_result(child, child.request_uuid, failure, deliver_child=True)
                    parent = self._session()
                    counts = (len(parent.event_ids), len(parent.channel_id.message_ids))
                    apply_iap_result(child, child.request_uuid, failure, deliver_child=True)
                self.assertEqual(notify.call_count, int(code == 'insufficient_credit'))
                self.assertEqual(finished['response'], {
                    'request_uuid': self.parent_request_uuid, 'responseState': 'idle',
                })
                self.assertEqual(parent.loop_state, 'ready')
                self.assertEqual(child.loop_state, 'ready')
                self.assertFalse(parent.pending_tool_call)
                self.assertFalse(parent.request_phase)
                self.assertEqual(child.request_result, failure)
                self.assertEqual([part['tool_call_id'] for part in self._results(parent)], ['prefix', 'image', 'suffix'])
                self.assertEqual([part['success'] for part in self._results(parent)], [True, False, False])
                self._assert_prefix_once(parent)
                self.assertNotIn('suffix_runs', parent.state)
                self.assertFalse(self._generated_attachments())
                self.assertEqual((len(parent.event_ids), len(parent.channel_id.message_ids)), counts)
                self.assertIn('Image generation is unavailable', parent.channel_id.message_ids[0].body)

    def test_image_input_and_attachment_creation_use_the_request_actor(self):
        private_image = self.env['ir.attachment'].create({
            'name': 'Private reference image', 'raw': PNG_B64, 'mimetype': 'image/png',
        })
        actor = self.env['res.users'].create({
            'name': 'Image continuation actor',
            'login': 'image_continuation_actor',
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
        })
        self._create_fixture(self.env['ai.session'].with_user(actor).sudo().env)
        with mute_logger('odoo.addons.ai.models.ai_session'):
            refused = self._apply_calls([self._call('image', args={
                'images_paths': [f'/web/image/ir.attachment/{private_image.id}/raw'],
            })])
        parent = self._session()
        self.assertEqual(refused["prepared_requests"][0]["session_id"], parent.id)
        self.assertFalse(self._results(parent)[0]['success'])
        self.assertNotIn(PNG_B64, str(parent.request_payload))
        self.assertFalse(self.env['ai.session'].sudo().search([('parent_session_id', '=', parent.id)]))
        self.assertFalse(self._generated_attachments())

        outcome = self._apply_calls([self._call('image')])
        child = self._session(outcome["prepared_requests"][0]["session_id"])
        self.assertEqual(child.request_user_id, actor)
        self._apply(child, assistant_image())
        attachment = self._generated_attachments()
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.create_uid, actor)
        self.assertFalse(attachment.public)
        self.assertEqual(attachment.raw.content, PNG_RAW)
        self.assertEqual(parent.loop_state, 'ready')

    def test_website_image_continuation_returns_permanent_public_urls_to_the_parent(self):
        session_data = self.env['ai.agent'].with_user(self.actor_id).action_launch_ai_chat(
            interface_key='website_builder_ai',
        )
        self.channel_id = session_data['ai_channel_id']
        parent = self.env['ai.session'].sudo().search([('channel_id', '=', self.channel_id)])
        self.session_id = parent.id
        self.context_snapshot = {
            **self.context_snapshot,
            'current_view_info': {'website_page': {'is_page_ai_editable': True}},
        }
        parent = self._session()
        parent.state = {'available_tools': list(self.tool_ids.values())}
        message = parent.channel_id.message_post(body=self.fixture_prompt, message_type='comment')
        parent.with_context(self.context_snapshot)._prepare_agent_request(message._convert_to_parts())
        self.parent_request_uuid = parent.request_uuid
        outcome = self._apply_calls([self._call('image'), self._call('suffix')])
        child = self._session(outcome["prepared_requests"][0]["session_id"])
        resumed = self._apply(child, assistant_image())

        attachments = self._generated_attachments()
        original = attachments.filtered(lambda attachment: not attachment.public)
        permanent = attachments.filtered('public')
        self.assertEqual(len(original), 1)
        self.assertEqual(len(permanent), 1)
        self.assertEqual(original.raw.content, PNG_RAW)
        self.assertEqual(permanent.res_model, 'ir.ui.view')
        self.assertFalse(self.env['ai.attachment.vacuum'].sudo().search([
            ('attachment_id', 'in', permanent.ids),
        ]))
        image_result = self._results(parent)[0]['result'][0]['text']
        self.assertIn('Here are the public URLs of the generated images.', image_result)
        self.assertIn(f'- ID: {original.id}, URL: {permanent.image_src}', image_result)
        self.assertEqual(resumed["prepared_requests"][0]["session_id"], parent.id)
        self.assertEqual(parent.request_round, 2)
        self.assertEqual(parent.state['suffix_runs'], 1)
        self.assertIn(permanent.image_src, str(parent.request_payload))
        self._apply(child, assistant_image())
        self.assertEqual(self._generated_attachments(), attachments)
        self.assertEqual(parent.state['suffix_runs'], 1)


@tagged('post_install', '-at_install')
class TestAIImageGenerationContinuationHttp(ImageGenerationFixture, HttpCase):
    def setUp(self):
        super().setUp()
        with self.registry.cursor() as cr:
            self._create_fixture(api.Environment(cr, self.env.ref('base.user_admin').id, {}))

    def _post_callback(self, request_uuid, message):
        with (
            self.allow_requests(all_requests=True),
            patch.object(AiSession, '_get_completions', side_effect=AssertionError('Image callback must not complete synchronously')) as direct,
        ):
            response = requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json={
                    'request_uuid': request_uuid,
                    'llm_result': {'status': 'success', 'result': message},
                    'llm_error': False,
                },
                timeout=12,
            )
        direct.assert_not_called()
        self.assertNotIn('Cookie', response.request.headers)
        return response

    def test_image_callback_rolls_back_result_and_effects_then_replays_once(self):
        observations = []
        calls = [self._call('prefix'), self._call('image'), self._call('suffix')]

        def observe_submission(_connection, route, payload, **_kwargs):
            with self.registry.cursor() as cr:
                env = api.Environment(cr, self.actor_id, self.context_snapshot)
                parent = self._session(env=env)
                child = env['ai.session'].sudo().search([('request_uuid', '=', payload['request_uuid'])])
                observations.append({
                    'route': route, 'payload': copy.deepcopy(payload),
                    'child_payload': child.request_payload, 'child_phase': child.request_phase,
                    'child_parent': child.parent_session_id.id, 'child_user': child.request_user_id.id,
                    'parent_state': parent.loop_state, 'parent_result': parent.request_result,
                    'prefix_count': env['res.partner'].search_count([('name', '=', self.prefix_name)]),
                    'image_count': len(self._generated_attachments(env)),
                })
            return None

        with patch(TRANSPORT, side_effect=observe_submission) as submit:
            response = self._post_callback(self.parent_request_uuid, {'role': 'assistant', 'content': calls})
        self.assertEqual(response.status_code, 200)
        submit.assert_called_once()
        observed = observations[0]
        self.assertEqual(observed['route'], '1/get_completions')
        self.assertEqual(observed['parent_state'], 'waiting_child')
        self.assertEqual(observed['child_phase'], 'prepared')
        self.assertEqual(observed['child_parent'], self.session_id)
        self.assertEqual(observed['child_user'], self.actor_id)
        self.assertEqual(observed['prefix_count'], 1)
        self.assertEqual(observed['image_count'], 0)
        self.assertEqual(observed['parent_result'], {
            'kind': 'success', 'message': {'role': 'assistant', 'content': calls},
        })
        self.env.invalidate_all()
        child = self.env['ai.session'].sudo().search([('parent_session_id', '=', self.session_id)])
        self.assertEqual(observed['payload'], {
            **observed['child_payload'], 'request_uuid': child.request_uuid,
            'webhook_url': child.request_callback_url,
            'webhook_token': child.request_webhook_token,
            'llm_retry': False,
        })
        self.assertEqual(child.request_phase, 'submitted')
        child_uuid = child.request_uuid
        parent = self._session()
        pending = copy.deepcopy(parent.pending_tool_call)
        message = assistant_image()
        original_apply = AiSession._continue_image_generation

        def fail_after_effect(image):
            original_apply(image)
            raise RuntimeError('Roll back image attachment creation and the parent suffix')

        with (
            mute_logger('odoo.http'),
            patch.object(AiSession, '_continue_image_generation', autospec=True, side_effect=fail_after_effect),
            patch(TRANSPORT) as submit,
        ):
            failed = self._post_callback(child_uuid, message)
        self.assertEqual(failed.status_code, 500)
        submit.assert_not_called()
        self.env.invalidate_all()
        self.assertFalse(child.request_result)
        self.assertEqual(child.loop_state, 'waiting_model')
        self.assertEqual(child.request_phase, 'submitted')
        parent = self._session()
        self.assertEqual(parent.loop_state, 'waiting_child')
        self.assertEqual(parent.request_uuid, self.parent_request_uuid)
        self.assertEqual(parent.pending_tool_call, pending)
        self.assertEqual(parent.pending_tool_call['call_id'], 'image')
        self.assertEqual(parent.pending_tool_call['pending_results'][-1], {
            'tool_name': self.tool_names['image'], 'tool_call_id': 'image', 'child_session_id': child.id,
        })
        self.assertNotIn('suffix_runs', parent.state)
        self.assertFalse(self._generated_attachments())
        self._assert_prefix_once(parent)
        partner = self.env['res.partner'].browse(parent.state['prefix_partner_ids'])
        self.assertFalse(partner.comment)

        with patch(TRANSPORT, return_value=None) as submit:
            completed = self._post_callback(child_uuid, message)
        self.assertEqual(completed.status_code, 200)
        submit.assert_called_once()
        self.env.invalidate_all()
        self.assertEqual(child.loop_state, 'ready')
        self.assertEqual(child.request_result, {'kind': 'success', 'message': message})
        self.assertEqual(parent.request_round, 2)
        self.assertEqual(parent.request_phase, 'submitted')
        self.assertEqual(submit.call_args.args[2]['request_uuid'], parent.request_uuid)
        self.assertFalse(parent.pending_tool_call)
        self.assertEqual(parent.state['suffix_runs'], 1)
        self._assert_prefix_once(parent)
        self.assertIn('Suffix executed', partner.comment)
        self.assertEqual([part['tool_call_id'] for part in self._results(parent)], ['prefix', 'image', 'suffix'])
        self.assertTrue(all(part['success'] for part in self._results(parent)))
        attachment = self._generated_attachments()
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.create_uid.id, self.actor_id)
        self.assertEqual(attachment.raw.content, PNG_RAW)
        self.assertFalse(attachment.public)
        counts = (len(parent.event_ids), len(parent.channel_id.message_ids))
        with patch(TRANSPORT) as submit:
            repeated = self._post_callback(child_uuid, message)
        self.assertEqual(repeated.status_code, 200)
        submit.assert_not_called()
        self.env.invalidate_all()
        self.assertEqual(self._generated_attachments(), attachment)
        self.assertEqual((len(parent.event_ids), len(parent.channel_id.message_ids)), counts)
        self.assertEqual(parent.state['suffix_runs'], 1)
        self.assertEqual(child.request_result, {'kind': 'success', 'message': message})
