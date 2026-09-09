# -*- coding: utf-8 -*-
# Asyntai AI Search for Odoo
# Copyright (c) 2026 Asyntai
# License: LGPL-3
"""Everything this module remembers, and the one question it asks Asyntai.

Two stores, on purpose.

  * The settings the owner chooses (where the bar goes, a selector, a colour)
    live in ir.config_parameter, bound to fields on the Settings screen. They
    change when somebody presses Save and at no other time.

  * Everything that changes on its own - the site id, the preview secret, the
    feed token, the cached status answer - lives in a small table of this
    module's own. ir.config_parameter is cached across the whole registry and
    a write to it drops that cache for every model, which is a poor price to
    pay for a status refresh every fifteen minutes. The table is also never
    listed under Technical > System Parameters, where a secret has no place.
"""
import hashlib
import hmac
import json
import logging
import time

import requests

from odoo import api, fields, models, release
from odoo.tools import sql as sql_tools

_logger = logging.getLogger(__name__)

# Odoo's own version, as the feed reports it. The feed reader on the Asyntai
# side keeps whatever is sent here as the store's platform version, so the
# word "Odoo" travels with the number: the same reader serves OpenCart.
ODOO_VERSION = 'Odoo %s' % release.version.split('+')[0]


class AsyntaiSearchState(models.Model):
    """One row per key. Read and written only through AsyntaiSearch below."""
    _name = 'asyntai.search.state'
    _description = 'Asyntai AI Search state'
    _log_access = False
    _rec_name = 'key'

    key = fields.Char(required=True, index=True)
    value = fields.Text()

    def init(self):
        # One row per key, enforced by the database. Made here rather than
        # with _sql_constraints, which Odoo 19 no longer reads, or with
        # models.Constraint, which Odoo 16 to 18 do not have. Odoo 19 also
        # folded create_unique_index into create_index(unique=True).
        name = 'asyntai_search_state_key_unique'
        try:
            sql_tools.create_index(self.env.cr, name, self._table, ['key'], unique=True)
        except TypeError:
            sql_tools.create_unique_index(self.env.cr, name, self._table, ['key'])


class AsyntaiSearch(models.AbstractModel):
    _name = 'asyntai.search'
    _description = 'Asyntai AI Search'

    # How long a preview link stays valid, in seconds.
    PREVIEW_TTL = 1500

    # How long a stored status answer is trusted when Asyntai sent no
    # cache_seconds, and the floor under whatever it did send.
    STATUS_MAX_AGE = 3600
    STATUS_MIN_AGE = 30

    # -----------------------------------------------------------------
    # Where Asyntai is
    # -----------------------------------------------------------------

    @api.model
    def origin(self):
        """Where this server's Python talks to Asyntai.

        Overridable through a system parameter so a staging copy can point at
        a test server. There is deliberately no field for it: a settings
        screen that lets somebody retype the server address is a settings
        screen that lets somebody break their own site in a way support
        cannot see.
        """
        value = self._param('asyntai_search.origin', '')
        return value.rstrip('/') if value else 'https://asyntai.com'

    @api.model
    def script_url(self):
        """What the VISITOR'S browser downloads, which is not the host above."""
        return self._param('asyntai_search.script_url', '') \
            or 'https://widget.asyntai.com/static/js/search-widget.js'

    # -----------------------------------------------------------------
    # Storage
    # -----------------------------------------------------------------

    @api.model
    def _param(self, key, default=''):
        value = self.env['ir.config_parameter'].sudo().get_param(key, default)
        return value if isinstance(value, str) else default

    @api.model
    def get(self, key, default=''):
        row = self.env['asyntai.search.state'].sudo().search([('key', '=', key)], limit=1)
        if not row or row.value is None or row.value is False:
            return default
        return row.value

    @api.model
    def set(self, key, value):
        rows = self.env['asyntai.search.state'].sudo()
        row = rows.search([('key', '=', key)], limit=1)
        was = row.value if row else None
        if row:
            row.write({'value': str(value)})
        else:
            rows.create({'key': key, 'value': str(value)})
        self._after_change(key, was, str(value))

    @api.model
    def forget(self, key):
        rows = self.env['asyntai.search.state'].sudo().search([('key', '=', key)])
        was = rows[:1].value if rows else None
        rows.unlink()
        self._after_change(key, was, None)

    @api.model
    def _after_change(self, key, was, now):
        """Drop Odoo's rendered-page cache when what the page shows changed.

        website.layout is cached whole for ordinary pages, header included,
        and that cache does not know about this module's table. Without this
        a disconnected site kept serving the script tag, and a site whose
        allowance came back kept serving none, until something else happened
        to clear the cache. Cleared only when the outcome moves: a status
        refresh that leaves the bar switched on touches nothing.
        """
        if key == 'site_id':
            changed = (was or '') != (now or '')
        elif key == 'status':
            changed = self._enabled(was or '') != self._enabled(now or '')
        else:
            return
        if changed:
            self._clear_page_cache()

    @api.model
    def _clear_page_cache(self):
        registry = self.env.registry
        try:
            if hasattr(registry, 'clear_cache'):
                # Odoo 17 and later name their caches; the t-cache values of
                # rendered templates live in this one. An Odoo that does not
                # know the name gets everything cleared instead.
                try:
                    registry.clear_cache('templates.cached_values')
                except Exception:
                    registry.clear_cache()
            else:
                registry.clear_caches()
        except Exception as e:  # pragma: no cover
            _logger.info('Asyntai AI Search: could not clear the page cache: %s', e)

    @api.model
    def all_state(self):
        """Every stored key at once: one query for a page render."""
        rows = self.env['asyntai.search.state'].sudo().search_read([], ['key', 'value'])
        return {row['key']: (row['value'] or '') for row in rows}

    # -----------------------------------------------------------------
    # What the owner chose
    # -----------------------------------------------------------------

    @api.model
    def site_id(self):
        return self.get('site_id', '').strip()

    @api.model
    def placement(self):
        """Where the bar goes.

          'auto'     replace the header search box if the site shows one,
                     otherwise add the bar to the header
          'replace'  take the place of the search box the site already shows
          'header'   add the bar to the site header
          'manual'   render only where the owner placed a container

        Defaults to 'auto', which always ends with exactly one bar on the
        page and never two.
        """
        value = self._param('asyntai_search.placement', 'auto')
        return value if value in ('auto', 'replace', 'header', 'manual') else 'auto'

    @api.model
    def effective_placement(self, website=None):
        """'auto' settled into one of the other three, for this website."""
        placement = self.placement()
        if placement != 'auto':
            return placement

        website = website or self.env['website'].get_current_website()
        try:
            shows_search = bool(website.is_view_active('website.header_search_box'))
        except Exception:
            shows_search = False

        return 'replace' if shows_search else 'header'

    # -----------------------------------------------------------------
    # The page
    # -----------------------------------------------------------------

    @api.model
    def page_attrs(self):
        """The attributes of the script tag, or False when no bar may render.

        False while there has never been a status answer, on purpose. A bar
        that cannot answer is worse than no bar, because in replace mode it
        has hidden the site's own search behind it.
        """
        state = self.all_state()
        site_id = (state.get('site_id') or '').strip()

        if not site_id or not self._enabled(state.get('status', '')):
            return False

        attrs = {
            'src': self.script_url(),
            'async': 'async',
            'data-asyntai-id': site_id,
        }

        placement = self.effective_placement()

        if placement == 'replace':
            selector = self._param('asyntai_search.selector', '').strip()
            attrs['data-replace'] = selector or 'auto'

        accent = self._param('asyntai_search.accent', '').strip()
        if accent:
            attrs['data-accent'] = accent

        placeholder = self._param('asyntai_search.placeholder', '').strip()
        if placeholder:
            attrs['data-placeholder'] = placeholder

        return attrs

    @api.model
    def header_bar(self, layout=None):
        """Whether the header template should print a container for the bar.

        `layout` is the header's own `_layout` variable. Some Odoo headers
        show the search box as an icon that opens a modal, and a form inside
        a closed modal is nothing the bar can take the place of: replace mode
        would leave the visitor with Odoo's own box. On those headers
        'auto' puts the bar in the header instead, where the icon was, and
        the stylesheet hides the icon.
        """
        state = self.all_state()
        site_id = (state.get('site_id') or '').strip()

        if not site_id or not self._enabled(state.get('status', '')):
            return False

        placement = self.placement()
        if placement == 'auto' and layout == 'modal':
            return True

        return self.effective_placement() == 'header'

    # -----------------------------------------------------------------
    # The one question we ask Asyntai
    # -----------------------------------------------------------------

    @api.model
    def status(self):
        """The last answer, or None when there has never been one."""
        raw = self.get('status', '')
        if not raw:
            return None
        try:
            decoded = json.loads(raw)
        except ValueError:
            return None
        return decoded if isinstance(decoded, dict) else None

    @api.model
    def _enabled(self, raw):
        if not raw:
            return False
        try:
            decoded = json.loads(raw)
        except ValueError:
            return False
        return isinstance(decoded, dict) and bool(decoded.get('enabled'))

    @api.model
    def enabled(self):
        return self._enabled(self.get('status', ''))

    @api.model
    def refresh(self, timeout=10):
        """Re-ask Asyntai and store the answer.

        Returns the answer, or None when the call failed, in which case the
        previous answer is kept: a network blip must not switch a working
        site's search off.
        """
        site_id = self.site_id()
        if not site_id:
            self.forget('status')
            self.forget('status_at')
            return None

        body = self.http_get(
            self.origin() + '/api/v1/search-widget/status/',
            {'widget_id': site_id}, timeout,
        )
        if body is None:
            return None

        try:
            decoded = json.loads(body)
        except ValueError:
            return None

        if not isinstance(decoded, dict) or 'enabled' not in decoded:
            return None

        self.set('status', json.dumps(decoded))
        self.set('status_at', str(int(time.time())))
        return decoded

    @api.model
    def refresh_if_stale(self):
        """Refresh only when the stored answer is older than Asyntai asked
        us to keep it. For the settings screen, where somebody is waiting."""
        status = self.status()
        if not status:
            return self.refresh()

        try:
            age = int(time.time()) - int(self.get('status_at', '0') or 0)
        except ValueError:
            age = self.STATUS_MAX_AGE

        return self.refresh() if age >= self._max_age(status) else status

    @api.model
    def _max_age(self, status):
        try:
            max_age = int(status.get('cache_seconds', self.STATUS_MAX_AGE))
        except (TypeError, ValueError):
            max_age = self.STATUS_MAX_AGE
        return max(max_age, self.STATUS_MIN_AGE)

    @api.model
    def _cron_refresh(self):
        """The scheduled action. Quiet when there is nothing to ask about."""
        if not self.site_id():
            return
        try:
            self.refresh_if_stale()
        except Exception as e:  # pragma: no cover - bookkeeping must never raise
            _logger.warning('Asyntai AI Search: status refresh failed: %s', e)

    @api.model
    def message(self, status):
        """A sentence for the settings screen.

        Known reasons are worded here. An unknown reason falls back to
        whatever Asyntai sent, which is what lets a new reason appear without
        a new release of this module.
        """
        if not isinstance(status, dict):
            return 'Not connected yet.'

        if status.get('enabled'):
            try:
                products = int(status.get('products') or 0)
            except (TypeError, ValueError):
                products = 0
            # A site with no shop is still perfectly searchable, and telling
            # a blog it is "searching 0 products" would read as a fault.
            if products < 1:
                return 'Searching your pages and blog posts.'
            return 'Searching {:,} products, plus your pages and blog posts.'.format(products)

        reason = status.get('reason') or ''
        if reason == 'plan':
            return ('Your plan does not include the AI Search Bar yet. Your usual '
                    'Odoo search is still running, so nothing on your site has changed.')
        if reason == 'limit':
            return ('You have used all your replies for this month. Your usual Odoo '
                    'search is still running, and the bar comes back when your '
                    'allowance resets.')
        if reason == 'no_products':
            return ('We are reading your site. This takes a few minutes, then the '
                    'bar switches on by itself.')
        if reason == 'unknown_widget':
            return 'This site is not connected to Asyntai any more. Connect it again above.'

        message = status.get('message')
        return str(message) if message else 'The search bar is not running.'

    # -----------------------------------------------------------------
    # The owner's own bar, on a link
    # -----------------------------------------------------------------

    @api.model
    def preview_url(self):
        """The address of this site's own search bar, carrying proof that this
        site asked for it.

        Signed rather than relying on a session: the owner is signed in to
        Odoo, not necessarily to Asyntai, and a link that lands on a sign-in
        form is a link nobody follows. Empty without a secret, which hides the
        button rather than offering a door that does not open.
        """
        site_id = self.site_id()
        secret = self.get('secret', '')
        if not site_id or not secret:
            return ''

        expiry = int(time.time()) + self.PREVIEW_TTL
        signature = hmac.new(
            secret.encode('utf-8'),
            ('%s:%d' % (site_id, expiry)).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

        return '%s/ai-search-bar/preview/?widget_id=%s&token=%d.%s' % (
            self.origin(), site_id, expiry, signature)

    # -----------------------------------------------------------------
    # The site itself
    # -----------------------------------------------------------------

    @api.model
    def site_url(self):
        """The public address of this site.

        The website's own domain when the owner set one, otherwise the address
        Odoo last saw itself at. Both are what a visitor would type.
        """
        website = self.env['website'].get_current_website()
        domain = (website.domain or '').strip().rstrip('/')
        if domain and not domain.startswith('http'):
            domain = 'https://' + domain
        if not domain:
            domain = self._param('web.base.url', '').rstrip('/')
        return domain

    @api.model
    def shop_installed(self):
        """Whether there is a catalogue to feed at all."""
        module = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'website_sale'), ('state', '=', 'installed')], limit=1)
        return bool(module)

    # -----------------------------------------------------------------
    # HTTP
    # -----------------------------------------------------------------

    @api.model
    def http_get(self, url, params=None, timeout=10):
        """Body of a GET, or None on any failure."""
        try:
            response = requests.get(
                url, params=params or {}, timeout=timeout,
                headers={'Accept': 'application/json',
                         'User-Agent': 'Asyntai-Odoo/1.0'},
            )
        except requests.RequestException as e:
            _logger.info('Asyntai AI Search: GET %s failed: %s', url, e)
            return None

        if response.status_code < 200 or response.status_code > 299:
            return None

        return response.text

    @api.model
    def http_post_json(self, url, payload, timeout=15):
        """Body of a JSON POST, or None on any failure."""
        try:
            response = requests.post(
                url, json=payload, timeout=timeout,
                headers={'Accept': 'application/json',
                         'User-Agent': 'Asyntai-Odoo/1.0'},
            )
        except requests.RequestException as e:
            _logger.info('Asyntai AI Search: POST %s failed: %s', url, e)
            return None

        if response.status_code < 200 or response.status_code > 299:
            return None

        return response.text
