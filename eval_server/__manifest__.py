{
    'name': 'Eval Server',
    'version': '1.0',
    'category': 'Technical',
    'author': 'Odoo S.A.',
    'summary': 'Unix socket eval server for direct ORM access from CLI',
    'depends': ['base'],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_load': 'start_eval_server',
}
