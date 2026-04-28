{
    'name': 'AI MCP Debugger',
    'version': '1.0',
    'category': 'Technical',
    'author': 'Odoo S.A.',
    'summary': 'Integrates the AI debugger with MCP server tool call tracing',
    'depends': ['ai_debug', 'ai_mcp'],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
    'assets': {
        'ai_debug.assets': [
            'ai_mcp_debug/static/src/mcp_patch.scss',
            'ai_mcp_debug/static/src/mcp_patch.xml',
            'ai_mcp_debug/static/src/mcp_patch.js',
        ],
        'ai_debug.assets_dark': [
            ('include', 'ai_mcp_debug/static/src/mcp_patch.scss'),
        ],
    },
}
