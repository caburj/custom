{
    'name': 'AI Debug',
    'version': '1.2',
    'category': 'Technical',
    'author': 'Odoo S.A.',
    'summary': 'Standalone live tracer for the AI agentic loop',
    'depends': ['ai_app', 'bus'],
    'data': [
        'views/ai_debug_index.xml',
    ],
    'assets': {
        'ai_debug.assets': [
            ('include', 'web._assets_helpers'),
            ('include', 'web._assets_backend_helpers'),
            'web/static/src/scss/pre_variables.scss',
            'web/static/lib/bootstrap/scss/_variables.scss',
            'web/static/lib/bootstrap/scss/_variables-dark.scss',
            'web/static/lib/bootstrap/scss/_maps.scss',
            ('include', 'web._assets_bootstrap_backend'),
            ('include', 'web._assets_core'),
            ('include', 'web.icons_fonts'),
            ('remove', 'web/static/src/**/*.dark.scss'),

            # Minimal page-side dependency closure for bus_service. The worker
            # code is served independently by bus.websocket_worker_assets.
            'bus/static/src/bus_parameters_plugin.js',
            'bus/static/src/multi_tab_fallback_plugin.js',
            'bus/static/src/multi_tab_shared_worker_plugin.js',
            'bus/static/src/multi_tab_plugin.js',
            'bus/static/src/services/worker_plugin.js',
            'bus/static/src/services/bus_plugin.js',

            'ai_debug/static/src/app/**/*.scss',
            ('remove', 'ai_debug/static/src/app/**/*.dark.scss'),
            'ai_debug/static/src/app/**/*.xml',
            'ai_debug/static/src/app/**/*.js',
        ],
        'ai_debug.assets_dark': [
            ('include', 'ai_debug.assets'),
            ('include', 'web.dark_mode_variables'),
            'web/static/src/core/**/*.dark.scss',
            'ai_debug/static/src/app/**/*.dark.scss',
        ],
        'web.assets_backend': [
            'ai_debug/static/src/debug_menu_button.js',
        ],
        'web.assets_unit_tests': [
            'ai_debug/static/src/app/event_payload.js',
            'ai_debug/static/src/app/db.js',
            'ai_debug/static/tests/**/*.test.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
