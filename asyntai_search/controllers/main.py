# -*- coding: utf-8 -*-
# Asyntai AI Search for Odoo
# Copyright (c) 2026 Asyntai
# License: LGPL-3
"""The connect handshake, and the catalogue feed.

The handshake, in order:
  1. "Connect" calls prepare. Python makes a preview secret and a feed token
     and parks them at Asyntai under a one-time token. No account exists yet,
     so nothing is linked to anybody.
  2. The browser opens the Asyntai sign-in window with that same token.
  3. The browser polls THIS server, which asks Asyntai for the token. Once
     the owner has signed in, the answer carries their site id.

Every call from the settings screen lands on this server. Nothing is ever
fetched from Asyntai as a script, so no code from another server runs inside
the Odoo backend.
"""
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from urllib.parse import urlencode

import werkzeug.exceptions

from odoo import http, release
from odoo.http import request

_logger = logging.getLogger(__name__)

# Odoo 19 renamed the JSON-RPC route type and warns about the old name on
# every start. One source serves every version, so the name is picked here.
JSON_ROUTE = 'jsonrpc' if release.version_info[0] >= 19 else 'json'

# How long a handshake token stays valid, in seconds.
STATE_TTL = 900

# Products per feed page, and the most a hand-made request may ask for.
PAGE_SIZE = 100
MAX_PAGE_SIZE = 250

# How far a signed feed request's clock may drift, in seconds.
CLOCK_SKEW = 300

# Longest description sent per product. Asyntai truncates again.
MAX_DESCRIPTION = 2000

# Layers of escaping undone before tags are removed. Real data has one or two.
MAX_DECODE_PASSES = 5

# A tag only when "<" is followed by a letter or "/", so "5 < 10 cm" keeps
# its words once the text has been decoded.
TAG_RE = re.compile(r'</?[a-zA-Z][^<>]*>')
OPEN_TAG_AT_END_RE = re.compile(r'</?[a-zA-Z][^<>]*$')
SCRIPT_RE = re.compile(r'<(script|style)\b[\s\S]*?(?:</\1\s*>|$)', re.I)
COMMENT_RE = re.compile(r'<!--[\s\S]*?(?:-->|$)')
SPACE_RE = re.compile(r'[\s ]+')


def _require_admin():
    """Administrators only. auth='user' lets any employee in; this does not."""
    if not request.env.user.has_group('base.group_system'):
        raise werkzeug.exceptions.Forbidden('Administrators only.')


class AsyntaiSearchController(http.Controller):

    # -----------------------------------------------------------------
    # Handshake
    # -----------------------------------------------------------------

    @http.route('/asyntai_search/prepare', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def prepare(self, **kwargs):
        """Park a fresh preview secret at Asyntai and hand the browser the
        sign-in address."""
        _require_admin()
        model = request.env['asyntai.search'].sudo()

        state = 'odoo_' + secrets.token_hex(12)

        # Made here and sent once, in this request body, which is the only
        # hop of the handshake that never passes through a browser. With it
        # this site can prove a preview belongs to it without depending on a
        # cookie surviving inside somebody else's frame.
        secret = secrets.token_hex(24)

        payload = {
            'state': state,
            'site_url': model.site_url(),
            'consumer_key': '',
            'consumer_secret': '',
            'plugin_secret': secret,
            'platform': 'odoo',
            'product': 'search',
        }

        # A shop hands over a catalogue feed as well: the address of it, and
        # the token every call to it is signed with. A site with no shop
        # stages nothing here and is searched from its pages alone.
        feed_token = ''
        if model.shop_installed():
            feed_token = secrets.token_hex(32)
            payload['feed_token'] = feed_token
            payload['feed_url'] = model.site_url() + '/asyntai_search/feed'

        body = model.http_post_json(model.origin() + '/api/v1/wp-search/stage/', payload)
        if body is None:
            return {'ok': False, 'error': 'Could not reach Asyntai. Check that this '
                                          'server can make outgoing HTTPS requests.'}

        # Kept only after Asyntai accepted them, so a failed handshake cannot
        # leave this site signing tokens with a secret nobody knows.
        model.set('secret', secret)
        model.set('state', state)
        model.set('state_at', str(int(time.time())))
        if feed_token:
            model.set('feed_token', feed_token)
        else:
            model.forget('feed_token')

        query = {
            'state': state,
            'site_url': model.site_url(),
            'platform': 'odoo',
            # Which product brought them, kept apart from which platform: this
            # is what separates a search install from a chat install in the
            # signup numbers.
            'product': 'search',
            'wp_email': request.env.user.email or '',
            'lang': (request.env.user.lang or 'en')[:2],
        }
        return {
            'ok': True,
            'state': state,
            'url': model.origin() + '/wp-auth?' + urlencode(query),
        }

    @http.route('/asyntai_search/poll', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def poll(self, state='', **kwargs):
        """Has the owner finished signing in?"""
        _require_admin()
        model = request.env['asyntai.search'].sudo()

        state = (state or '').strip()
        stored = model.get('state', '')

        # Only the token this site just generated is ever polled, so a
        # guessed or replayed token cannot read somebody else's handshake.
        if not state or state != stored:
            return {'ok': False, 'error': 'Unknown handshake. Press Connect again.'}

        try:
            started = int(model.get('state_at', '0') or 0)
        except ValueError:
            started = 0
        if int(time.time()) - started > STATE_TTL:
            return {'ok': False, 'error': 'This connection attempt has expired. '
                                          'Please press Connect again.'}

        body = model.http_get(model.origin() + '/api/v1/wp-search/connect-status/',
                              {'state': state})
        if body is None:
            return {'ok': True, 'ready': False}

        try:
            decoded = json.loads(body)
        except ValueError:
            return {'ok': True, 'ready': False}

        data = decoded.get('data') if isinstance(decoded, dict) else None
        if not isinstance(decoded, dict) or not decoded.get('ready') \
                or not isinstance(data, dict) or not data.get('site_id'):
            return {'ok': True, 'ready': False}

        return {
            'ok': True,
            'ready': True,
            'site_id': str(data.get('site_id')),
            'account_email': str(data.get('account_email') or ''),
        }

    @http.route('/asyntai_search/finish', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def finish(self, site_id='', account_email='', **kwargs):
        """Remember the site id and ask Asyntai for a first status."""
        _require_admin()
        model = request.env['asyntai.search'].sudo()

        site_id = (site_id or '').strip()
        # The id is ours, so its shape is known. Anything else is a caller
        # that did not come from the poll above.
        if not re.match(r'^[A-Za-z0-9_-]{6,64}$', site_id):
            return {'ok': False, 'error': 'Invalid site id.'}

        model.set('site_id', site_id)
        model.set('account_email', (account_email or '')[:255])
        model.forget('state')
        model.forget('state_at')
        model.refresh()
        return {'ok': True}

    @http.route('/asyntai_search/disconnect', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def disconnect(self, **kwargs):
        """Forget this site's connection. The secret and the feed token go
        with it: a token kept after a disconnect can only ever sign a request
        nobody should be able to make."""
        _require_admin()
        model = request.env['asyntai.search'].sudo()
        for key in ('site_id', 'secret', 'feed_token', 'status', 'status_at',
                    'state', 'state_at', 'account_email'):
            model.forget(key)
        return {'ok': True}

    @http.route('/asyntai_search/status', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def status(self, **kwargs):
        """Everything the settings screen shows."""
        _require_admin()
        model = request.env['asyntai.search'].sudo()

        site_id = model.site_id()
        if not site_id:
            return {'ok': True, 'connected': False, 'shop': model.shop_installed()}

        status = model.refresh_if_stale()
        reason = (status or {}).get('reason') or ''

        if status and status.get('enabled'):
            state = 'live'
        elif reason == 'no_products':
            state = 'setting_up'
        elif reason in ('plan', 'limit'):
            state = 'blocked'
        else:
            state = 'unknown'

        def _int(value):
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return {
            'ok': True,
            'connected': True,
            'site_id': site_id,
            'account_email': model.get('account_email', ''),
            'state': state,
            'message': model.message(status) if state != 'unknown' else
                       'Your site is still connected. We will check again shortly, '
                       'and nothing on your site has changed in the meantime.',
            'searches_left': _int((status or {}).get('searches_left')),
            'monthly_limit': _int((status or {}).get('monthly_limit')),
            'products': _int((status or {}).get('products')),
            'sync': (status or {}).get('sync'),
            'dashboard_url': (status or {}).get('dashboard_url') or 'https://asyntai.com/dashboard',
            'analytics_url': (status or {}).get('analytics_url') or 'https://asyntai.com/ai-search-analytics/',
            'preview_url': model.preview_url(),
            'placement': model.effective_placement(),
            'shop': model.shop_installed(),
        }

    # -----------------------------------------------------------------
    # The catalogue
    # -----------------------------------------------------------------

    @http.route('/asyntai_search/feed', type='http', auth='public', methods=['GET'],
                website=True, multilang=False, sitemap=False, csrf=False)
    def feed(self, **query):
        """The read-only product feed Asyntai reads the catalogue from.

        WHY A FEED AND NOT A CRAWL. Crawling a shop gives us page text, which
        goes stale the moment a price changes and carries no stock figure at
        all. Reading the shop's own numbers is what lets the search bar show
        a price, a discount and an availability that are correct today.

        WHAT A SHOPPER WOULD SEE IS WHAT IS SENT. Only published products, at
        the price the website's pricelist and tax setting would show, in the
        website's currency.

        Every call must carry a signature made with the token this site
        handed Asyntai when it connected. An unsigned call is refused before
        a single product is read.
        """
        status, body = self._feed(query)
        return request.make_json_response(
            body, status=status,
            headers=[('Cache-Control', 'no-store'), ('X-Robots-Tag', 'noindex')],
        )

    def _feed(self, query):
        model = request.env['asyntai.search'].sudo()
        # The token alone is the proof, not the site id. Asyntai starts
        # reading the catalogue the moment the owner signs in, which is
        # before this server has polled for the site id, and a feed that
        # refused that first read would be marked disconnected for good.
        token = model.get('feed_token', '')
        if not token:
            return 403, {'ok': False, 'error': 'This site is not connected to Asyntai.'}

        raw_page = str(query.get('page', ''))
        raw_limit = str(query.get('limit', ''))
        ids = str(query.get('ids', ''))
        ts = str(query.get('ts', ''))
        sig = str(query.get('sig', ''))

        # The signature covers the values AS SENT, so the string signed by
        # Asyntai is the string checked here.
        signed = 'page=%s&limit=%s&ids=%s&ts=%s' % (raw_page, raw_limit, ids, ts)

        if not ts.isdigit():
            return 403, {'ok': False, 'error': 'Missing timestamp.'}

        # A replayed request is worth little here, but a signature with no
        # expiry is a credential that never dies.
        if abs(int(time.time()) - int(ts)) > CLOCK_SKEW:
            return 403, {'ok': False, 'error': 'The request has expired.'}

        expected = hmac.new(token.encode('utf-8'), signed.encode('utf-8'),
                            hashlib.sha256).hexdigest()
        if not sig or not hmac.compare_digest(expected, sig):
            return 403, {'ok': False, 'error': 'Bad signature.'}

        website = request.env['website'].get_current_website()
        store = {
            'name': website.name or request.env.company.name or '',
            'url': model.site_url(),
            'currency': self._currency(website),
            'platform': 'odoo',
            'version': 'Odoo %s' % release.version.split('+')[0],
        }

        if not model.shop_installed():
            return 200, {'ok': True, 'store': store, 'page': 1, 'pages': 1,
                         'total': 0, 'products': []}

        templates = request.env['product.template'].sudo().with_context(
            website_id=website.id, lang=website.default_lang_id.code)

        # What the shop itself shows: published, for sale, on this website.
        domain = [('sale_ok', '=', True), ('is_published', '=', True),
                  ('website_id', 'in', (False, website.id))]

        if ids:
            wanted = []
            for piece in ids.split(','):
                piece = piece.strip()
                if piece.isdigit() and int(piece) not in wanted:
                    wanted.append(int(piece))
                if len(wanted) >= 50:
                    break
            rows = templates.search(domain + [('id', 'in', wanted)], order='id')
            products = [p for p in (self._one(t, website) for t in rows) if p]
            return 200, {'ok': True, 'store': store, 'page': 1, 'pages': 1,
                         'total': len(products), 'products': products}

        page = int(raw_page) if raw_page.isdigit() and int(raw_page) > 0 else 1
        limit = int(raw_limit) if raw_limit.isdigit() else PAGE_SIZE
        if limit < 1 or limit > MAX_PAGE_SIZE:
            limit = PAGE_SIZE

        total = templates.search_count(domain)
        # Ordered by id rather than by name, so a rename between two pages
        # cannot make a product appear twice or not at all.
        rows = templates.search(domain, order='id', limit=limit, offset=(page - 1) * limit)
        products = [p for p in (self._one(t, website) for t in rows) if p]

        return 200, {
            'ok': True,
            'store': store,
            'page': page,
            'pages': max(1, -(-total // limit)),
            'total': total,
            'products': products,
        }

    def _currency(self, website):
        try:
            return website.currency_id.name or ''
        except Exception:
            try:
                return request.env.company.currency_id.name or ''
            except Exception:
                return ''

    def _one(self, template, website):
        """One product, as a shopper would see it, or None."""
        name = self._plain(template.name or '')
        if not name:
            return None

        out = {'id': template.id, 'name': name}

        description = self._plain(
            getattr(template, 'description_ecommerce', None)
            or template.description_sale
            or getattr(template, 'description', None) or '')
        if description:
            out['description'] = description

        if template.default_code:
            out['sku'] = template.default_code
        if template.barcode:
            out['ean'] = template.barcode

        price, special, currency, _template_qty = self._price(template, website)
        if price is not None:
            out['price'] = price
        if special is not None:
            out['special'] = special
        out['currency'] = currency or self._currency(website)
        quantity, in_stock = self._stock(template, website)
        if quantity is not None:
            out['quantity'] = quantity
        if in_stock is not None:
            out['stock_status'] = 'In stock' if in_stock else 'Out of stock'

        categories = []
        for category in getattr(template, 'public_categ_ids', []):
            label = (category.display_name or category.name or '').strip()
            if label and label not in categories:
                categories.append(label)
        if categories:
            out['categories'] = categories

        base = self._base_url(website)
        path = template.website_url or ('/shop/%d' % template.id)
        out['url'] = base + path if path.startswith('/') else path

        if template.image_1920:
            out['image_url'] = base + website.image_url(template, 'image_512')

        return out

    def _stock(self, template, website):
        """(quantity, in_stock) for one product, each None when unknown.

        Read per variant, the way the shop page reads it. The template-level
        combination info that _price uses answers free_qty 0 for EVERY
        product once Inventory is installed, because a template is not a
        variant; that sent a whole stocked catalogue as out of stock.

        Products Inventory does not count (services, consumables, kits) give
        (None, None): the shop always sells them. A counted product at 0 that
        the shop still sells ("Continue selling when out-of-stock") gives
        (None, True), so the feed never says 0 and In stock together.
        """
        try:
            variants = template.product_variant_ids
            if not variants or 'free_qty' not in variants._fields:
                return None, None  # Inventory is not installed

            if 'is_storable' in template._fields:  # 18 and later
                storable = bool(template.is_storable)
            else:  # 16 and 17
                storable = (getattr(template, 'detailed_type', None) or template.type) == 'product'
            if not storable:
                return None, None

            total = 0.0
            for variant in variants.sudo():
                if hasattr(website, '_get_product_available_qty'):
                    free = website._get_product_available_qty(variant)
                elif hasattr(website, '_get_warehouse_available'):
                    free = variant.with_context(warehouse=website._get_warehouse_available()).free_qty
                else:
                    free = variant.free_qty
                total += max(0.0, float(free or 0))

            quantity = int(total)
            if quantity <= 0 and getattr(template, 'allow_out_of_stock_order', False):
                return None, True
            return quantity, quantity > 0
        except Exception as e:
            _logger.info('Asyntai AI Search: stock of %s unknown: %s', template.id, e)
            return None, None

    def _price(self, template, website):
        """(price, special, currency, quantity) with the website's pricelist
        and tax display applied. The catalogue price when that fails."""
        try:
            info = template._get_combination_info(only_template=True)
            currency = info.get('currency')
            currency = currency.name if currency is not None and hasattr(currency, 'name') else ''
            price = info.get('price')
            list_price = info.get('list_price')
            special = None
            if info.get('has_discounted_price') and list_price is not None \
                    and price is not None and float(price) < float(list_price):
                special, price = price, list_price
            quantity = None
            if 'free_qty' in info:
                try:
                    quantity = int(float(info.get('free_qty') or 0))
                except (TypeError, ValueError):
                    quantity = None
            return (self._money(price), self._money(special), currency, quantity)
        except Exception as e:
            _logger.info('Asyntai AI Search: price of %s fell back: %s', template.id, e)
            return (self._money(template.list_price), None, '', None)

    @staticmethod
    def _money(value):
        if value is None:
            return None
        try:
            return '%.4f' % float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _plain(html):
        """HTML reduced to the text a shopper would read. Used for names too.

        Entities are decoded FIRST, until nothing changes, and tags are
        removed after that. In the other order an escaped value ("&lt;b&gt;")
        comes back as live markup once the strip is done.
        """
        import html as html_module

        text = str(html or '')
        for _ in range(MAX_DECODE_PASSES):
            decoded = html_module.unescape(text)
            if decoded == text:
                break
            text = decoded

        # Until nothing changes: removing one tag can join the pieces around
        # it into another ("<scr<b>ipt>").
        for _ in range(MAX_DECODE_PASSES):
            before = text
            text = SCRIPT_RE.sub(' ', text)
            text = COMMENT_RE.sub(' ', text)
            text = TAG_RE.sub(' ', text)
            text = OPEN_TAG_AT_END_RE.sub(' ', text)
            if text == before:
                break

        text = SPACE_RE.sub(' ', text).strip()
        return text[:MAX_DESCRIPTION]

    def _base_url(self, website):
        try:
            base = website.get_base_url()
        except Exception:
            base = ''
        if not base:
            base = request.env['asyntai.search'].sudo().site_url()
        return (base or '').rstrip('/')
