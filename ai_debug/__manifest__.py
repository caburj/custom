# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'AI Debug',
    'category': 'Hidden',
    'depends': ['ai', 'bus'],
    'data': [
        'security/ir.access.csv',
        'views/client.xml',
    ],
    'assets': {
        # Backend webclient: registers the bypass-confirmation switch in the
        # user-menu so devs can toggle it from anywhere in the UI without
        # having to navigate to /ai-debug first.
        'web.assets_backend': [
            'ai_debug/static/src/user_menu_item.js',
        ],
        'ai_debug.assets': [
            # Core JS (OWL, module_loader, env, session, RPC, ORM, registry, templates, etc.)
            ('include', 'web._assets_core'),
            ('remove', 'web/static/src/core/**/*.scss'),

            # Bootstrap styles
            ('include', 'web._assets_helpers'),
            'web/static/src/scss/pre_variables.scss',
            'web/static/lib/bootstrap/scss/_variables.scss',
            'web/static/lib/bootstrap/scss/_variables-dark.scss',
            'web/static/lib/bootstrap/scss/_maps.scss',
            ('include', 'web._assets_bootstrap'),

            # Icons & fonts
            ('include', 'web.icons_fonts'),

            # Bus service (real-time notifications)
            'bus/static/src/*.js',
            'bus/static/src/services/**/*.js',
            'bus/static/src/workers/*',
            ('remove', 'bus/static/src/workers/bus_worker_script.js'),

            # App
            'ai_debug/static/src/**/*.xml',
            'ai_debug/static/src/**/*.js',
            # The user-menu switch belongs to the regular backend (loaded
            # above into web.assets_backend); the /ai-debug standalone page
            # has no user menu, so registering it here would be dead weight.
            ('remove', 'ai_debug/static/src/user_menu_item.js'),
            'ai_debug/static/src/**/*.css',
        ],
        'web.assets_unit_tests': [
            'ai_debug/static/src/record.js',
            'ai_debug/static/src/store.js',
            'ai_debug/static/src/lazy_fields.js',
            'ai_debug/static/src/hooks/*.js',
            # The real viewer components + their templates, so acceptance
            # tests can mount the production ConversationView / ChatMessage /
            # IterationSection / ToolCallCard / JsonViewer / TextBlock and
            # assert the rendered DOM the user sees. This is a TEST-ONLY
            # bundle (never served to end users); the production page bundle
            # is ``ai_debug.assets`` above and is untouched.
            'ai_debug/static/src/components/**/*.js',
            'ai_debug/static/src/components/**/*.xml',
            'ai_debug/static/tests/**/*.test.js',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
