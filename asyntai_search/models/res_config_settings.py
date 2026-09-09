# -*- coding: utf-8 -*-
# Asyntai AI Search for Odoo
# Copyright (c) 2026 Asyntai
# License: LGPL-3

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """The settings the owner chooses. Bound to system parameters, so Odoo
    itself loads and saves them; nothing here runs on a visitor's page."""
    _inherit = 'res.config.settings'

    asyntai_search_placement = fields.Selection(
        [
            ('auto', 'Automatic: replace the header search box if there is one, otherwise add the bar to the header'),
            ('replace', 'In place of the search box my site already shows'),
            ('header', 'Add the bar to the site header'),
            ('manual', 'Only where I add the block myself'),
        ],
        string='Where the bar goes',
        default='auto',
        config_parameter='asyntai_search.placement',
        help='Replace mode takes the place of the search box your site already '
             'shows. Pressing Enter without picking a result still opens your '
             'usual search page.',
    )
    asyntai_search_selector = fields.Char(
        string='Search box to replace',
        config_parameter='asyntai_search.selector',
        help='Leave empty and we find it. Fill in a CSS selector only if we '
             'pick the wrong one.',
    )
    asyntai_search_placeholder = fields.Char(
        string='Placeholder text',
        config_parameter='asyntai_search.placeholder',
        help='Leave empty and each visitor sees it in their own language.',
    )
    asyntai_search_accent = fields.Char(
        string='Accent colour',
        config_parameter='asyntai_search.accent',
        help='Leave empty to use the colour set in your Asyntai dashboard.',
    )
