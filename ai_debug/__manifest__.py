{
    'name': 'AI Debug',
    'version': '1.0',
    'category': 'Technical',
    'summary': 'Instrument the AI agentic loop for full observability',
    'depends': ['ai_app', 'bus'],
    'data': [
        'security/ir.model.access.csv',
        'views/debug_panel_action.xml',
        'views/ai_debug_trace_views.xml',
        'views/ai_debug_iteration_views.xml',
        'views/ai_debug_tool_call_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_debug/static/src/**/*.js',
            'ai_debug/static/src/**/*.xml',
            'ai_debug/static/src/**/*.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
