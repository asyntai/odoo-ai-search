/** @odoo-module **/
/**
 * Asyntai AI Search - the settings panel, in the browser.
 *
 * Everything it calls goes to this Odoo server. Nothing is ever fetched from
 * Asyntai as a script, so no code from another server runs inside the Odoo
 * backend.
 *
 * Odoo renders the Settings form with OWL and re-renders it when the tab
 * changes, so the panel is filled in whenever its container appears rather
 * than once at page load.
 *
 * @copyright Copyright (c) 2026 Asyntai
 * @license   LGPL-3
 */

const STRINGS = {
    preparing: 'Preparing...',
    waiting: 'Waiting for you to finish in the Asyntai window...',
    saving: 'Connected. Saving...',
    blocked: 'Your browser blocked the pop-up. Allow pop-ups and try again.',
    failed: 'Could not connect. Please try again.',
    timeout: 'Timed out waiting for the Asyntai window. Please try again.',
    signedOut: 'Odoo signed you out. Please log in again, then try once more.',
    confirm: 'Disconnect this site from Asyntai? The search bar stops, and your usual Odoo search takes over.',
};

const HEADINGS = {
    live: 'Live on your site',
    setting_up: 'Setting up your site',
    blocked: 'Connected, but not on your site yet',
    unknown: 'We could not reach Asyntai just now',
};

const DOTS = { live: 'on', setting_up: 'busy', blocked: 'busy', unknown: 'off' };

let popup = null;
let filledFor = null;

function esc(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function say(message, ok) {
    const box = document.getElementById('asyntai-search-alert');
    if (!box) { return; }
    box.style.display = 'block';
    box.style.borderLeftColor = ok ? '#1a7f37' : '#b32d2e';
    box.textContent = message;
}

function call(path, params) {
    return fetch('/asyntai_search/' + path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'call',
            params: params || {},
            id: Math.floor(Math.random() * 1000000000),
        }),
    }).then(function (response) {
        // Read as text first. An Odoo session that ended mid-handshake
        // answers with the sign-in page, which is HTML, and parsing it
        // straight away throws an error that says nothing.
        return response.text().then(function (raw) {
            let parsed;
            try {
                parsed = JSON.parse(raw);
            } catch (e) {
                const lost = new Error(STRINGS.signedOut);
                lost.signedOut = true;
                throw lost;
            }
            if (parsed.error) {
                const data = parsed.error.data || {};
                throw new Error(data.message || parsed.error.message || STRINGS.failed);
            }
            const result = parsed.result || {};
            if (result.ok === false) {
                throw new Error(result.error || STRINGS.failed);
            }
            return result;
        });
    });
}

// -----------------------------------------------------------------
// Rendering
// -----------------------------------------------------------------

function renderConnect(data) {
    const what = data.shop
        ? 'We read your products, pages and blog posts, and the bar switches on by itself when they are ready.'
        : 'We read your pages and blog posts, and the bar switches on by itself when they are ready.';
    return '<div class="asyntai-panel asyntai-hero">'
        + '<h3>Connect your Asyntai account</h3>'
        + '<p>Sign in, or create a free account. ' + what + '</p>'
        + '<p><button type="button" id="asyntai-search-connect" class="asyntai-btn">Connect Asyntai</button></p>'
        + '<p class="asyntai-fine">We only ever read your site. Nothing in it is changed.</p>'
        + '</div>'
        + '<div class="asyntai-points">'
        + '<div class="asyntai-point">' + (data.shop ? 'Products, pages and blog posts in one search box.' : 'Pages and blog posts in one search box.') + '</div>'
        + '<div class="asyntai-point">Nothing to paste. Nothing to set up.</div>'
        + '<div class="asyntai-point">If your allowance runs out, your usual search takes over.</div>'
        + '</div>';
}

function renderStatus(data) {
    let html = '<div class="asyntai-panel">';
    html += '<p class="asyntai-state"><span class="asyntai-dot ' + DOTS[data.state] + '"></span>'
        + esc(HEADINGS[data.state]) + '</p>';
    html += '<p class="asyntai-detail">' + esc(data.message) + '</p>';

    // How much of the month is left, worded so nobody reads it as a
    // search-only budget: searches and chat replies share one allowance.
    if (data.state === 'live' && data.monthly_limit) {
        html += '<p class="asyntai-detail">' + esc(
            Number(data.searches_left).toLocaleString() + ' of your '
            + Number(data.monthly_limit).toLocaleString()
            + ' monthly replies left. Searches and chat replies share this allowance.') + '</p>';
    }

    if (data.account_email) {
        html += '<p class="asyntai-fine">Connected as ' + esc(data.account_email) + '</p>';
    }

    html += '<p class="asyntai-links">';
    html += '<a href="' + esc(data.dashboard_url) + '" target="_blank" rel="noopener">Open your Asyntai dashboard</a>';
    // Analytics says nothing at all until visitors have searched, so it is
    // offered only while the bar is live.
    if (data.state === 'live') {
        html += '<a href="' + esc(data.analytics_url) + '" target="_blank" rel="noopener">See what visitors searched for</a>';
    }
    html += '<a href="#" id="asyntai-search-disconnect" class="asyntai-danger">Disconnect this site</a>';
    html += '</p></div>';

    // A link to the owner's real bar, not a drawing of one. A copy of the
    // bar built into this module would go stale the moment the widget
    // changes.
    if (data.preview_url) {
        html += '<div class="asyntai-panel"><h3>Try it on your own content</h3>'
            + '<p class="asyntai-detail">Open your real search bar and type something a visitor would look for. Searches you run there are not counted against your monthly allowance.</p>'
            + '<p><a class="asyntai-btn" href="' + esc(data.preview_url) + '" target="_blank" rel="noopener">Try your search bar</a></p></div>';
    }

    if (data.state === 'live' && data.placement === 'manual') {
        html += '<div class="asyntai-panel asyntai-hint"><p class="asyntai-detail">'
            + 'The bar only appears where you place it. In the website editor, add an HTML block with '
            + '<code>&lt;div data-asyntai-search&gt;&lt;/div&gt;</code> where the bar should go.'
            + '</p></div>';
    }

    return html;
}

function fill(force) {
    const panel = document.getElementById('asyntai-search-panel');
    if (!panel) { return; }
    if (filledFor === panel && !force) { return; }
    filledFor = panel;

    call('status', {}).then(function (data) {
        const target = document.getElementById('asyntai-search-panel');
        if (!target) { return; }
        target.innerHTML = data.connected ? renderStatus(data) : renderConnect(data);
    }).catch(function (error) {
        say(error.message || STRINGS.failed, false);
    });
}

// -----------------------------------------------------------------
// The handshake
// -----------------------------------------------------------------

// The window must be opened inside the click, before any network call, or
// the browser treats it as unrequested and blocks it. When it is blocked
// anyway, the handshake still runs: the sign-in address is offered as a
// link instead, and the poll waits for whichever window the owner uses.
function connect() {
    popup = window.open('about:blank', 'asyntai_connect',
        'width=820,height=740,scrollbars=yes,resizable=yes');

    say(STRINGS.preparing, true);

    call('prepare', {}).then(function (data) {
        if (popup) {
            popup.location = data.url;
            say(STRINGS.waiting, true);
        } else {
            sayLink(STRINGS.blocked + ' Or ', data.url, 'open the sign-in page in a new tab', '.');
        }
        poll(data.state, 0);
    }).catch(function (error) {
        if (popup) { try { popup.close(); } catch (e) { /* already gone */ } }
        say(error.message || STRINGS.failed, false);
    });
}

function sayLink(before, url, label, after) {
    const box = document.getElementById('asyntai-search-alert');
    if (!box) { return; }
    box.style.display = 'block';
    box.style.borderLeftColor = '#bf8700';
    box.textContent = '';
    box.appendChild(document.createTextNode(before));
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = label;
    box.appendChild(link);
    box.appendChild(document.createTextNode(after));
}

function poll(state, attempt) {
    if (attempt > 150) { say(STRINGS.timeout, false); return; }

    call('poll', { state: state }).then(function (data) {
        if (data && data.ready && data.site_id) {
            say(STRINGS.saving, true);
            return call('finish', { site_id: data.site_id, account_email: data.account_email || '' })
                .then(function () {
                    if (popup) { try { popup.close(); } catch (e) { /* already gone */ } }
                    say('Connected. We are reading your site now.', true);
                    fill(true);
                });
        }
        setTimeout(function () { poll(state, attempt + 1); }, 2000);
    }).catch(function (error) {
        // A lost session never recovers by waiting, so stop and say what
        // happened. Anything else is a blip worth another try.
        if (error && error.signedOut) {
            if (popup) { try { popup.close(); } catch (e) { /* already gone */ } }
            say(error.message, false);
            return;
        }
        setTimeout(function () { poll(state, attempt + 1); }, 3000);
    });
}

function disconnect() {
    if (!window.confirm(STRINGS.confirm)) { return; }
    call('disconnect', {}).then(function () {
        say('Disconnected. Your usual Odoo search is running.', true);
        fill(true);
    }).catch(function (error) {
        say(error.message || STRINGS.failed, false);
    });
}

// -----------------------------------------------------------------
// Wiring
// -----------------------------------------------------------------

document.addEventListener('click', function (event) {
    const target = event.target;
    if (!target || !target.closest) { return; }

    if (target.closest('#asyntai-search-connect')) {
        event.preventDefault();
        event.stopPropagation();
        connect();
        return;
    }

    if (target.closest('#asyntai-search-disconnect')) {
        event.preventDefault();
        event.stopPropagation();
        disconnect();
    }
}, true);

// The settings form is rendered and re-rendered by OWL, so watch for the
// panel rather than assuming it is there at load.
const observer = new MutationObserver(function () { fill(false); });

function start() {
    observer.observe(document.body, { childList: true, subtree: true });
    fill(false);
}

if (document.body) {
    start();
} else {
    document.addEventListener('DOMContentLoaded', start);
}
