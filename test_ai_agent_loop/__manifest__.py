# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Test AI Agent Loop',
    'category': 'Hidden',
    'summary': 'Tests for the callback-driven AI agent loop',
    'author': 'Odoo S.A.',
    'depends': ['ai_app', 'ai_livechat', 'ai_website', 'ai_website_sale'],
    'assets': {
        'im_livechat.embed_assets_unit_tests_setup': [
            'ai/static/tests/mock_server/controllers/messaging_menu.js',
            'ai_app/static/tests/mock_server/controllers/messaging_menu.js',
        ],
        'im_livechat.embed_assets_unit_tests': [
            'test_ai_agent_loop/static/tests/embed/**/*',
        ],
        'web.assets_unit_tests': [
            'test_ai_agent_loop/static/tests/**/*',
            ('remove', 'test_ai_agent_loop/static/tests/embed/**/*'),
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
