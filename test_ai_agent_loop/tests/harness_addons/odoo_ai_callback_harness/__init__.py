from . import controllers


def post_load():
    from odoo.addons.odoo_ai import ai_service

    from .provider import get_completions

    ai_service.get_completions = get_completions
