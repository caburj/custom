{
    'name': 'AI Debug',
    'version': '1.1',
    'category': 'Technical',
    'summary': 'Standalone live tracer for the AI agentic loop',
    'depends': ['ai_app', 'bus'],
    'data': [
        'views/ai_debug_index.xml',
    ],
    'assets': {
        'ai_debug.assets': [
            ('include', 'web.assets_backend'),
            'ai_debug/static/src/app/**/*.scss',
            'ai_debug/static/src/app/**/*.xml',
            'ai_debug/static/src/app/**/*.js',
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
