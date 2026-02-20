{
    'name': 'AI Debug',
    'version': '1.0',
    'category': 'Technical',
    'summary': 'Instrument the AI agentic loop for full observability',
    'depends': ['ai'],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_debug_trace_views.xml',
        'views/ai_debug_iteration_views.xml',
        'views/ai_debug_tool_call_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
