# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

import requests

from odoo import Command, api
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .common import apply_iap_result
from .test_ai_session_subagents import tool_call
from odoo.addons.ai.controllers.thread import AIThreadController


@tagged('post_install', '-at_install')
class TestAISessionSubagentsHttp(HttpCase):
    @contextmanager
    def _physical_tree(
        self, child_count=1, *, confirmation=False, context_snapshot=None,
        child_round_limits=None, prepare_root=True,
    ):
        """Use committed fixtures and real HTTP cursors, not TestCursor wrappers."""
        raw_cursor = self.registry._db.cursor
        with raw_cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            agent = env['ai.agent'].create({
                'name': 'Physical foreground agent',
                'system_prompt': 'Complete focused work.',
                'skill_ids': [Command.clear()],
            })
            agent.allowed_agent_ids = agent
            channel = agent._create_ai_chat_channel('Physical foreground callbacks')
            parent = env['ai.session'].sudo().create({
                'agent_id': agent.id, 'channel_id': channel.id,
            })
            create_tool = env.ref('ai.ir_actions_server_create_records')
            if confirmation:
                parent.state = {'available_tools': create_tool.ids}
            contact_name = f'Physical foreground confirmed {parent.id}'
            parent_uuid = False
            if prepare_root:
                parent.with_context({
                    'allowed_company_ids': env.companies.ids,
                    'active_company_ids': env.companies.ids,
                    **(context_snapshot or {}),
                })._prepare_agent_request(
                    [{'type': 'text', 'text': 'Run independent children'}],
                )
                parent_uuid = parent.request_uuid
                parent = parent.with_context(parent.request_context)
                prepare_request = type(parent)._store_request
                round_limits = iter(child_round_limits or ())

                def prepare_child_request(session, *args, **kwargs):
                    if session.parent_session_id == parent:
                        kwargs['request_round_limit'] = next(round_limits)
                    return prepare_request(session, *args, **kwargs)

                with (
                    patch.object(type(parent), '_store_request', prepare_child_request)
                    if child_round_limits is not None else nullcontext()
                ):
                    apply_iap_result(parent, parent_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': [
                            tool_call('start_session', f'child-{index}',
                                      agent_id=agent.id, message=f'Child {index}')
                            for index in range(child_count)
                        ] + ([tool_call(create_tool.ai_tool_name, 'confirm',
                            explanation='Create the confirmed contact?', model_name='res.partner',
                            preview_menu_id=False, values=[{'field_values': [
                                {'field': 'name', 'value': contact_name},
                            ]}],
                        )] if confirmation else [])},
                    })
            children = env['ai.session'].sudo().search([
                ('parent_session_id', '=', parent.id),
            ], order='id')
            fixture = {
                'parent_id': parent.id, 'parent_uuid': parent_uuid,
                'channel_id': channel.id, 'agent_id': agent.id, 'contact_name': contact_name,
                'children': [(child.id, child.request_uuid) for child in children],
            }
        try:
            with patch.object(self.registry, 'cursor', lambda readonly=False: raw_cursor()):
                yield fixture
        finally:
            with raw_cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                env['ai.session'].sudo().browse(fixture['parent_id']).exists().unlink()
                env['discuss.channel'].sudo().browse(fixture['channel_id']).exists().unlink()
                env['ai.agent'].sudo().browse(fixture['agent_id']).exists().unlink()
                env['res.partner'].search([('name', 'in', [
                    fixture['contact_name'], fixture['contact_name'] + ' A',
                    fixture['contact_name'] + ' B', fixture['contact_name'] + ' C',
                ])]).unlink()

    def _callback(self, request_uuid, text, *, concurrent=False):
        with nullcontext() if concurrent else self.allow_requests(all_requests=True):
            return requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json={
                    'request_uuid': request_uuid, 'llm_error': False,
                    'llm_result': {'status': 'success', 'result': {
                        'role': 'assistant', 'content': ([{'type': 'text', 'text': text}]
                                                       if isinstance(text, str) else text),
                    }},
                }, timeout=25,
            )

    def _snapshot(self, session_id):
        with self.registry._db.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            session = env['ai.session'].sudo().browse(session_id)
            return {
                'loop_state': session.loop_state,
                'request_uuid': session.request_uuid,
                'request_phase': session.request_phase,
                'resume_token': session.resume_token,
                'pending': session.pending_tool_call,
                'payload': session.request_payload,
                'events': session.event_ids.ids,
            }

    def _results(self, snapshot):
        return [part for message in snapshot['payload']['messages']
                for part in message['content'] if part.get('type') == 'tool_result']


    def test_callback_submits_all_children_before_waiting_for_confirmation(self):
        with self._physical_tree(child_count=0) as fixture:
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref("base.user_admin").id, {})
                parent = env["ai.session"].sudo().browse(fixture["parent_id"])
                create_tool = env.ref("ai.ir_actions_server_create_records")
                parent.state = {"available_tools": create_tool.ids}
                prepared = parent._prepare_agent_request(
                    [{"type": "text", "text": "Delegate then ask"}],
                )
                calls = [
                    tool_call(
                        "start_session",
                        label,
                        agent_id=fixture["agent_id"],
                        message=label,
                    )
                    for label in ("A", "B")
                ]
                calls.append(
                    tool_call(
                        create_tool.ai_tool_name,
                        "confirm",
                        explanation="Create the contact?",
                        model_name="res.partner",
                        preview_menu_id=False,
                        values=[
                            {
                                "field_values": [
                                    {"field": "name", "value": fixture["contact_name"]},
                                ],
                            },
                        ],
                    ),
                )

            def observe_submission(_connection, _route, payload, **_kwargs):
                # A separate connection must see every prepared child before the first send.
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    children = (
                        env["ai.session"]
                        .sudo()
                        .search([("parent_session_id", "=", fixture["parent_id"])])
                    )
                    self.assertEqual(len(children), 2)
                    self.assertIn(
                        payload["request_uuid"], children.mapped("request_uuid"),
                    )
                    self.assertEqual(
                        env["ai.session"].browse(fixture["parent_id"]).loop_state,
                        "waiting_confirmation",
                    )

            with patch(
                "odoo.addons.ai.models.ai_session.call_odoo_ai_transport",
                side_effect=observe_submission,
            ) as transport:
                response = self._callback(prepared["request_uuid"], calls)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(transport.call_count, 2)
            self.assertEqual(
                len(
                    {call.args[2]["request_uuid"] for call in transport.call_args_list},
                ),
                2,
            )
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                children = (
                    env["ai.session"]
                    .sudo()
                    .search([("parent_session_id", "=", fixture["parent_id"])])
                )
                self.assertEqual(
                    children.mapped("request_phase"), ["submitted", "submitted"],
                )
                self.assertFalse(
                    env["res.partner"].search([("name", "=", fixture["contact_name"])]),
                )




    def test_child_callback_during_confirmation_and_resume_execute_once(self):
        with self._physical_tree(confirmation=True) as fixture:
            self.authenticate('admin', 'admin')
            child_id, child_uuid = fixture['children'][0]
            waiting = self._snapshot(fixture['parent_id'])
            with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport:
                self.assertEqual(self._callback(child_uuid, 'Done while awaiting approval').status_code, 200)
                filled = self._snapshot(fixture['parent_id'])
                self.assertEqual(filled['loop_state'], 'waiting_confirmation')
                self.assertEqual(filled['resume_token'], waiting['resume_token'])
                self.assertEqual(filled['pending']['user_input_request'], waiting['pending']['user_input_request'])
                self.assertEqual(filled['pending']['call_id'], waiting['pending']['call_id'])
                transport.assert_not_called()
                payload = self.build_rpc_payload({
                    'channel_id': fixture['channel_id'], 'session_id': fixture['parent_id'],
                    'resume_token': waiting['resume_token'],
                    'response': {'kind': 'confirmation', 'value': 'confirm_once'},
                })
                response = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertNotIn('error', response.json())
                final = self._snapshot(fixture['parent_id'])
                self.assertEqual(final['request_phase'], 'submitted')
                transport.assert_called_once()
                replay = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertNotIn('error', replay.json())
                self.assertEqual(self._snapshot(fixture['parent_id']), final)
                transport.assert_called_once()
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                self.assertEqual(env['res.partner'].search_count([('name', '=', fixture['contact_name'])]), 1)
                self.assertEqual(env['ai.session'].sudo().search([
                    ('parent_session_id', '=', fixture['parent_id']),
                ]).ids, [child_id])


    def _contact_call(self, env, call_id, name):
        return tool_call(env.ref('ai.ir_actions_server_create_records').ai_tool_name, call_id,
            explanation=f'Create {name}?', model_name='res.partner', preview_menu_id=False,
            values=[{'field_values': [{'field': 'name', 'value': name}]}],
        )



    def test_autoapproval_commits_child_effects_before_submission(self):
        self.authenticate('admin', 'admin')
        for web_search in (False, True):
            with self.subTest(web_search=web_search), self._physical_tree() as fixture:
                child_id, child_uuid = fixture['children'][0]
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                    child = env['ai.session'].sudo().browse(child_id)
                    create_tool = env.ref('ai.ir_actions_server_create_records')
                    tool_ids = create_tool.ids
                    calls = [self._contact_call(env, 'automatic-confirm', fixture['contact_name'])]
                    if web_search:
                        search_tool = env.ref('ai.ir_actions_server_ai_web_search')
                        tool_ids += search_tool.ids
                        calls.append(tool_call(
                            search_tool.ai_tool_name, 'automatic-search',
                            query='Odoo durable callbacks', retrieval_mode='summary',
                            context_hint='Automatic approval',
                        ))
                    child.state = {'available_tools': tool_ids}
                    apply_iap_result(child, child_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': calls},
                    })
                    self.assertEqual(child.loop_state, 'waiting_confirmation')
                    resume_token = child.resume_token
                run_tool = self.registry['ir.actions.server']._ai_tool_run
                invocations, submissions = [], []

                def count_confirmed_tool(tool, record, arguments, tools_context):
                    if tools_context.get('session_id') == child_id and tools_context.get('tool_request_confirmed'):
                        invocations.append(tool.id)
                    return run_tool(tool, record, arguments, tools_context)

                def observe_submission(_connection, _route, payload, **_kwargs):
                    source = self._snapshot(child_id)
                    with self.registry._db.cursor() as cr:
                        env = api.Environment(cr, self.env.uid, {})
                        prepared = env['ai.session'].sudo().search([
                            ('request_uuid', '=', payload['request_uuid']),
                        ])
                        self.assertEqual(len(prepared), 1)
                        self.assertEqual(prepared.loop_state, 'waiting_model')
                        self.assertEqual(prepared.request_phase, 'prepared')
                        self.assertEqual(env['res.partner'].search_count([
                            ('name', '=', fixture['contact_name']),
                        ]), 1)
                        if web_search:
                            self.assertEqual(prepared.parent_session_id.id, child_id)
                            self.assertFalse(prepared.channel_id)
                            self.assertEqual(source['loop_state'], 'waiting_child')
                            self.assertEqual(source['request_uuid'], child_uuid)
                            self.assertEqual(source['pending']['pending_results'][-1]['child_session_id'], prepared.id)
                        else:
                            self.assertEqual(prepared.id, child_id)
                        submissions.append((prepared.id, prepared.request_uuid))

                with (
                    patch.object(self.registry['ir.actions.server'], '_ai_tool_run', count_confirmed_tool),
                    patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', side_effect=observe_submission),
                ):
                    response = self.url_open('/ai/resume_pending_interaction', json=self.build_rpc_payload({
                        'channel_id': fixture['channel_id'], 'session_id': child_id,
                        'resume_token': resume_token,
                        'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
                    }))

                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn('error', response.json())
                self.assertEqual(invocations, tool_ids)
                self.assertEqual(len(submissions), 1)
                submitted_id, submitted_uuid = submissions[0]
                submitted = self._snapshot(submitted_id)
                self.assertEqual(submitted['request_uuid'], submitted_uuid)
                self.assertNotEqual(submitted_uuid, child_uuid)
                self.assertEqual(submitted['request_phase'], 'submitted')

    def test_autoapproval_delivers_terminal_child_before_parent_submission(self):
        self.authenticate('admin', 'admin')
        # Approval exhausts the child's original budget without another child request.
        with self._physical_tree(child_count=2, child_round_limits=(1, 20)) as fixture:
            child_id, child_uuid = fixture['children'][0]
            callback_id, callback_uuid = fixture['children'][1]
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                child = env['ai.session'].sudo().browse(child_id)
                create_tool = env.ref('ai.ir_actions_server_create_records')
                child.state = {'available_tools': create_tool.ids}
                apply_iap_result(child, child_uuid, {
                    'kind': 'success', 'message': {'role': 'assistant', 'content': [
                        self._contact_call(env, 'terminal-confirm', fixture['contact_name']),
                    ]},
                })
                self.assertEqual(child.loop_state, 'waiting_confirmation')
                resume_token = child.resume_token
            self.assertEqual(self._callback(callback_uuid, 'Sibling completed').status_code, 200)
            submit = self.registry['ai.session']._submit_prepared_request
            run_tool = self.registry['ir.actions.server']._ai_tool_run
            attempts, invocations = [], []

            def count_confirmed_tool(tool, record, arguments, tools_context):
                if tools_context.get('session_id') == child_id and tools_context.get('tool_request_confirmed'):
                    invocations.append(tool.id)
                return run_tool(tool, record, arguments, tools_context)

            def observe_parent_submission(session, request_uuid):
                self.assertEqual(session.id, fixture['parent_id'])
                child = self._snapshot(child_id)
                parent = self._snapshot(session.id)
                self.assertEqual(child['loop_state'], 'ready')
                result = next(json.loads(item['result'][0]['text']) for item in self._results(parent)
                              if item['tool_name'] == 'start_session'
                              and json.loads(item['result'][0]['text'])['session_id'] == child_id)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(self._snapshot(callback_id)['loop_state'], 'ready')
                self.assertEqual(parent['request_uuid'], request_uuid)
                self.assertEqual(parent['request_phase'], 'prepared')
                self.assertFalse(parent['pending'])
                attempts.append((child, parent))
                return submit(session, request_uuid)

            with (
                patch.object(self.registry['ai.session'], '_submit_prepared_request',
                             autospec=True, side_effect=observe_parent_submission),
                patch.object(self.registry['ir.actions.server'], '_ai_tool_run', count_confirmed_tool),
                patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport,
            ):
                response = self.url_open('/ai/resume_pending_interaction', json=self.build_rpc_payload({
                    'channel_id': fixture['channel_id'], 'session_id': child_id,
                    'resume_token': resume_token,
                    'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
                }))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(attempts), 1)
            self.assertEqual(invocations, create_tool.ids)
            self.assertEqual(self._snapshot(child_id), attempts[0][0])
            root = self._snapshot(fixture['parent_id'])
            self.assertEqual(root['request_phase'], 'submitted')
            self.assertEqual([json.loads(result['result'][0]['text'])['status'] for result in self._results(root)],
                             ['failed', 'completed'])
            transport.assert_called_once()
            self.assertEqual(transport.call_args.args[2]['request_uuid'], root['request_uuid'])
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                self.assertEqual(env['res.partner'].search_count([('name', '=', fixture['contact_name'])]), 1)


    def test_only_accepted_allow_all_resumes_other_confirmations(self):
        self.authenticate('admin', 'admin')
        with self._physical_tree(child_count=3, confirmation=True, child_round_limits=(1, 20, 1)) as fixture:
            first_id, first_uuid = fixture['children'][0]
            sibling_id, sibling_uuid = fixture['children'][1]
            last_id, last_uuid = fixture['children'][2]
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                root = env['ai.session'].sudo().browse(fixture['parent_id'])
                root_token = root.resume_token
                for session_id, request_uuid, suffix in (
                    (first_id, first_uuid, ' A'), (last_id, last_uuid, ' C'),
                ):
                    child = env['ai.session'].sudo().browse(session_id)
                    child.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                    apply_iap_result(child, request_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': [
                            self._contact_call(env, f'confirm-{session_id}', fixture['contact_name'] + suffix),
                        ]},
                    })
                # These prompts represent accepted late arrivals after allow-all.
                root.auto_confirm = True
            pending = {sid: self._snapshot(sid) for sid in (first_id, last_id)}

            def resume(session_id, token, value):
                response = self.url_open('/ai/resume_pending_interaction', json=self.build_rpc_payload({
                    'channel_id': fixture['channel_id'], 'session_id': session_id,
                    'resume_token': token, 'response': {'kind': 'confirmation', 'value': value},
                }))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn('error', response.json())

            with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as submit:
                for label in ('Sibling completed', 'Duplicate callback'):
                    self.assertEqual(self._callback(sibling_uuid, label).status_code, 200)
                    self.assertEqual({sid: self._snapshot(sid) for sid in pending}, pending)
                resume(fixture['parent_id'], root_token, 'confirm_once')
                self.assertEqual({sid: self._snapshot(sid) for sid in pending}, pending)
                resume(fixture['parent_id'], root_token, 'auto_confirm')
                self.assertEqual({sid: self._snapshot(sid) for sid in pending}, pending)
                submit.assert_not_called()

                resume(first_id, pending[first_id]['resume_token'], 'auto_confirm')
                self.assertTrue(all(self._snapshot(sid)['loop_state'] == 'ready' for sid in pending))
                submit.assert_called_once()
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                for suffix in ('', ' A', ' C'):
                    self.assertEqual(env['res.partner'].search_count([
                        ('name', '=', fixture['contact_name'] + suffix),
                    ]), 1)

    def test_autoapproval_sweep_failure_rolls_back_all_pending_descendants(self):
        with self._physical_tree(child_count=3) as fixture:
            self.authenticate('admin', 'admin')
            first_id, first_uuid = fixture['children'][0]
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                children = env['ai.session'].sudo().browse([child_id for child_id, _uuid in fixture['children']])
                children.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                for child, suffix in zip(children, (' A', ' B', ' C')):
                    apply_iap_result(child, child.request_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': [
                            self._contact_call(env, f'confirm-{child.id}', fixture['contact_name'] + suffix),
                        ]},
                    })
                token = children[0].resume_token
            sweep = AIThreadController._resume_auto_confirmations
            attempts = []

            def interrupt_first_sweep(controller, root):
                attempts.append(root.id)
                prepared = sweep(controller, root)
                if len(attempts) == 1:
                    raise RuntimeError('failed after consuming all observed approvals')
                return prepared

            payload = self.build_rpc_payload({
                'channel_id': fixture['channel_id'], 'session_id': first_id,
                'resume_token': token,
                'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
            })
            with (
                mute_logger('odoo.http'),
                patch.object(AIThreadController, '_resume_auto_confirmations',
                             autospec=True, side_effect=interrupt_first_sweep),
                patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport,
            ):
                failed = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertIn('error', failed.json())
                self.assertTrue(all(self._snapshot(child_id)['loop_state'] == 'waiting_confirmation'
                                    for child_id, _uuid in fixture['children']))
                self.assertEqual(self._snapshot(first_id)['resume_token'], token)
                transport.assert_not_called()
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    self.assertFalse(env['ai.session'].sudo().browse(fixture['parent_id']).auto_confirm)
                    self.assertFalse(env['res.partner'].search_count([
                        ('name', 'in', [fixture['contact_name'] + suffix for suffix in (' A', ' B', ' C')]),
                    ]))
                replay = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertNotIn('error', replay.json())
                self.assertTrue(all(self._snapshot(child_id)['loop_state'] == 'waiting_model'
                                    for child_id, _uuid in fixture['children']))
                self.assertEqual(transport.call_count, 3)
                replay = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertNotIn('error', replay.json())
                self.assertEqual(transport.call_count, 3)
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                for suffix in (' A', ' B', ' C'):
                    self.assertEqual(env['res.partner'].search_count([
                        ('name', '=', fixture['contact_name'] + suffix),
                    ]), 1)


    def test_allow_all_and_parent_delivery_keep_the_resuming_company_and_view(self):
        self.authenticate('admin', 'admin')
        original_cids = self.opener.cookies.get('cids')
        with self.registry._db.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            company = env['res.company'].create({'name': 'Event context company'})
            env.user.company_ids = [Command.link(company.id)]
            company_id = company.id
        try:
            with self._physical_tree(child_count=2, context_snapshot={
                'current_view_info': {'marker': 'before-resume'},
            }) as fixture:
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                    children = env['ai.session'].sudo().browse([sid for sid, _uuid in fixture['children']])
                    for child, suffix in zip(children, (' A', ' B')):
                        child.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                        apply_iap_result(child, child.request_uuid, {
                            'kind': 'success', 'message': {'role': 'assistant', 'content': [
                                self._contact_call(env, f'confirm-{child.id}', fixture['contact_name'] + suffix),
                            ]},
                        })
                    token = children[0].resume_token
                self.opener.cookies['cids'] = str(company_id)
                observed = []
                resume = self.registry['ai.session']._resume_pending_interaction
                submit = self.registry['ai.session']._submit_prepared_request
                merge = self.registry['ai.session']._merge_child_result

                def observe(kind, session):
                    from odoo.http import request
                    observed.append((kind, session.id))
                    self.assertEqual(session.env.company.id, company_id)
                    self.assertEqual(session.env.context['current_view_info'], {'marker': 'after-resume'})
                    self.assertEqual(request.env.company.id, company_id)
                    self.assertIs(request.env.transaction.default_env, request.env)

                def observe_resume(session, *args, **kwargs):
                    observe('resume', session)
                    return resume(session, *args, **kwargs)

                def observe_submit(session, *args, **kwargs):
                    observe('submit', session)
                    self.assertFalse(session.env.su)
                    return submit(session, *args, **kwargs)

                def observe_merge(session, *args, **kwargs):
                    observe('merge', session)
                    return merge(session, *args, **kwargs)

                with (
                    patch.object(self.registry['ai.session'], '_resume_pending_interaction', observe_resume),
                    patch.object(self.registry['ai.session'], '_submit_prepared_request', observe_submit),
                    patch.object(self.registry['ai.session'], '_merge_child_result', observe_merge),
                    patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None),
                ):
                    response = self.url_open('/ai/resume_pending_interaction', json=self.build_rpc_payload({
                        'channel_id': fixture['channel_id'], 'session_id': fixture['children'][0][0],
                        'resume_token': token, 'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
                        'current_view_info': {'marker': 'after-resume'},
                    }))
                    self.assertNotIn('error', response.json())
                    self.assertEqual(sum(kind == 'resume' for kind, _sid in observed), 2)
                    for sid, _uuid in fixture['children']:
                        child = self._snapshot(sid)
                        self.assertEqual(self._callback(child['request_uuid'], 'Child complete').status_code, 200)
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    parent = env['ai.session'].sudo().browse(fixture['parent_id'])
                    self.assertEqual(parent.loop_state, 'waiting_model')
                    self.assertEqual(parent.request_context['allowed_company_ids'], [company_id])
                    self.assertEqual(parent.request_context['current_view_info'], {'marker': 'after-resume'})
                    self.assertIn('after-resume', str(parent.request_payload['messages']))
                    self.assertEqual(env['res.partner'].search_count([
                        ('name', 'in', [fixture['contact_name'] + ' A', fixture['contact_name'] + ' B']),
                    ]), 2)
        finally:
            if original_cids is None:
                self.opener.cookies.pop('cids', None)
            else:
                self.opener.cookies['cids'] = original_cids
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                env.ref('base.user_admin').company_ids = [Command.unlink(company_id)]
                env['payment.provider'].search([('company_id', '=', company_id)]).unlink()
                env['res.company'].browse(company_id).unlink()
