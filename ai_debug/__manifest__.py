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
            ('include', 'web.assets_backend'),
            # The ai_natural_language_service subscribes to AI_ADJUST_SEARCH /
            # AI_SOFT_RELOAD bus events and tries actionService.switchView() —
            # which crashes on this standalone page (no action window).
            ('remove', 'ai/static/src/ai_natural_language_service.js'),
            'ai_debug/static/src/app/**/*.scss',
            ('remove', 'ai_debug/static/src/app/**/*.dark.scss'),
            'ai_debug/static/src/app/**/*.xml',
            'ai_debug/static/src/app/**/*.js',
        ],
        'ai_debug.assets_dark': [
            ('include', 'ai_debug.assets'),
            ('include', 'web.dark_mode_variables'),
            'ai_debug/static/src/app/**/*.dark.scss',
        ],
        'web.assets_backend': [
            'ai_debug/static/src/debug_menu_button.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
