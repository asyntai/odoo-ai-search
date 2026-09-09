# -*- coding: utf-8 -*-
# Asyntai AI Search for Odoo
# Copyright (c) 2026 Asyntai
# License: LGPL-3

from odoo import api, SUPERUSER_ID

from . import models
from . import controllers


def uninstall_hook(cr_or_env, registry=None):
    """Forget every setting the module wrote.

    The state table goes with the module's own tables, but the placement
    settings live in ir.config_parameter, which Odoo never cleans up on its
    own. A reinstall must start from nothing, not from a stale selector.

    Odoo 16 hands hooks (cr, registry); Odoo 17 and later hand them an env.
    """
    if isinstance(cr_or_env, api.Environment):
        env = cr_or_env
    else:
        env = api.Environment(cr_or_env, SUPERUSER_ID, {})

    params = env['ir.config_parameter'].sudo()
    params.search([('key', '=like', 'asyntai_search.%')]).unlink()
