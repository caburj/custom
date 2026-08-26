from . import controllers


def post_load():
    from odoo.addons.odoo_ai import dispatcher

    from .provider import run_completion

    dispatcher.run_completion = run_completion
