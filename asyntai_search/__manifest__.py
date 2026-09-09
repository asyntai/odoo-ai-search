# -*- coding: utf-8 -*-
# Asyntai AI Search for Odoo
# Copyright (c) 2026 Asyntai
# License: LGPL-3

{
    'name': 'Asyntai - AI Search',
    'version': '17.0.1.0.0',
    'category': 'Website',
    'summary': 'AI search bar that understands what visitors mean. Finds products, pages and blog posts, not only exact words.',
    'description': """
Asyntai - AI Search for Odoo
============================

Visitors know what they want but not what it is called. A normal search
box matches words, so "something to carry my laptop in" finds nothing.
Asyntai AI Search understands what they mean and shows the right products,
pages and blog posts.

Features:
---------
* Results that match what visitors mean, not only the words they type
* Product photo, price and availability inside the search box
* Pages and blog posts in the same search, so questions find answers
* Prices and stock read from your own shop, tax and pricelist included
* Adds itself to your header. Nothing to paste, nothing to configure
* Free to start. If the monthly allowance runs out, Odoo's own search takes over

Configuration:
--------------
Open Asyntai AI Search in the app switcher and press Connect.
    """,
    'author': 'Asyntai',
    'website': 'https://asyntai.com/documentation/odoo-ai-search/',
    'license': 'LGPL-3',
    'depends': ['base', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/menu_views.xml',
        'views/res_config_settings_views.xml',
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'asyntai_search/static/src/css/admin.css',
            'asyntai_search/static/src/js/admin.js',
        ],
        'web.assets_frontend': [
            'asyntai_search/static/src/css/frontend.css',
        ],
    },
    'images': [
        'static/description/ai-search-for-odoo-1.png',
        'static/description/ai-search-for-odoo-2.png',
        'static/description/ai-search-for-odoo-3.png',
        'static/description/ai-search-for-odoo-4.png',
    ],
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'auto_install': False,
    'application': True,
}
