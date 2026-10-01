/*
 * Admin-only "Git sync conflict" alert.
 *
 * The GitHub poller (C:\Share\apps\autobroll-sync) writes each app's sync state
 * to a status file; this app's /api/git-sync-status returns that entry to
 * admins only (403 for everyone else). When the server copy and GitHub have
 * both changed, admins see a small pill in the corner; clicking it explains
 * what diverged and how to reconcile.
 *
 * Shared verbatim by every app the poller syncs. Edit all copies together.
 * Usage: <script src="git-sync-alert.js" data-endpoint="/api/git-sync-status" defer></script>
 */
(function () {
    'use strict';

    var script = document.currentScript;
    var endpoint = (script && script.getAttribute('data-endpoint')) || '/api/git-sync-status';
    // The poller rewrites the status every 5 minutes. While an alert is up,
    // check often so it disappears promptly once a sync succeeds.
    var POLL_MS = 60000;
    var POLL_WHILE_SHOWING_MS = 15000;
    // A conflict shows at once. Other failures (tests blocking an update,
    // GitHub unreachable) show after this many consecutive polls (~15 min),
    // so a passing network blip never alarms anyone.
    var PROBLEM_AFTER_FAILURES = 3;

    var CSS = [
        '.gsa-root{--gsa-bg:#fff;--gsa-fg:#1f2937;--gsa-muted:#5b6472;--gsa-border:#d8dde5;--gsa-code:#f3f5f8;',
        '--gsa-conflict:#c62828;--gsa-problem:#9a5b00;--gsa-on-accent:#fff;position:fixed;right:16px;bottom:16px;z-index:2147483000;',
        'font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--gsa-fg)}',
        '[data-theme="dark"] .gsa-root{--gsa-bg:#161b22;--gsa-fg:#e6edf3;--gsa-muted:#9aa4b2;--gsa-border:#30363d;--gsa-code:#0d1117;--gsa-conflict:#ff7b72;--gsa-problem:#e3b341;--gsa-on-accent:#0d1117}',
        '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .gsa-root{--gsa-bg:#161b22;--gsa-fg:#e6edf3;',
        '--gsa-muted:#9aa4b2;--gsa-border:#30363d;--gsa-code:#0d1117;--gsa-conflict:#ff7b72;--gsa-problem:#e3b341;--gsa-on-accent:#0d1117}}',
        '.gsa-root[hidden]{display:none}',
        '.gsa-pill{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;border:0;cursor:pointer;',
        'font:600 13px/1 inherit;color:var(--gsa-on-accent);background:var(--gsa-accent);box-shadow:0 4px 14px rgba(0,0,0,.25)}',
        '.gsa-pill:focus-visible,.gsa-close:focus-visible{outline:3px solid var(--gsa-accent);outline-offset:2px}',
        '.gsa-dot{width:8px;height:8px;border-radius:50%;background:var(--gsa-on-accent);animation:gsa-pulse 2s ease-in-out infinite}',
        '@keyframes gsa-pulse{50%{opacity:.35}}@media (prefers-reduced-motion:reduce){.gsa-dot{animation:none}}',
        '.gsa-panel{position:absolute;right:0;bottom:calc(100% + 10px);width:min(440px,calc(100vw - 32px));max-height:70vh;',
        'overflow:auto;background:var(--gsa-bg);border:1px solid var(--gsa-border);border-top:4px solid var(--gsa-accent);',
        'border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.28);padding:16px 18px}',
        '.gsa-panel[hidden]{display:none}',
        '.gsa-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}',
        '.gsa-title{margin:0;font-size:16px;font-weight:700;color:var(--gsa-accent)}',
        '.gsa-close{border:0;background:none;color:var(--gsa-muted);font-size:20px;line-height:1;cursor:pointer;padding:0 2px}',
        '.gsa-meta{margin:2px 0 10px;color:var(--gsa-muted);font-size:12.5px}',
        '.gsa-panel h4{margin:14px 0 4px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--gsa-muted)}',
        '.gsa-panel p{margin:0 0 8px}',
        '.gsa-panel ul,.gsa-panel ol{margin:0;padding-left:20px}',
        '.gsa-panel li{margin:2px 0;overflow-wrap:anywhere}',
        '.gsa-panel code{font:12.5px/1.4 ui-monospace,Consolas,monospace;background:var(--gsa-code);',
        'border:1px solid var(--gsa-border);border-radius:4px;padding:1px 5px;overflow-wrap:anywhere}',
        '@media (max-width:480px){.gsa-root{right:12px;bottom:12px}}'
    ].join('');

    var root, pill, pillLabel, panel, lastKey = '';

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function ago(iso) {
        var then = Date.parse(iso);
        if (isNaN(then)) return '';
        var minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
        if (minutes < 1) return 'just now';
        if (minutes < 60) return minutes + ' min ago';
        var hours = Math.round(minutes / 60);
        if (hours < 48) return hours + ' h ago';
        return Math.round(hours / 24) + ' days ago';
    }

    function list(items) {
        var ul = el('ul');
        items.forEach(function (item) { ul.appendChild(el('li', null, item)); });
        return ul;
    }

    function step(parts) {
        var li = el('li');
        parts.forEach(function (part) {
            li.appendChild(typeof part === 'string' ? document.createTextNode(part) : part);
        });
        return li;
    }

    function build() {
        var style = el('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        root = el('div', 'gsa-root');
        root.hidden = true;
        pill = el('button', 'gsa-pill');
        pill.type = 'button';
        pill.setAttribute('aria-haspopup', 'dialog');
        pill.setAttribute('aria-expanded', 'false');
        pill.setAttribute('aria-controls', 'gsa-panel');
        pill.appendChild(el('span', 'gsa-dot'));
        pillLabel = el('span');
        pill.appendChild(pillLabel);
        panel = el('div', 'gsa-panel');
        panel.id = 'gsa-panel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-labelledby', 'gsa-title');
        root.appendChild(panel);
        root.appendChild(pill);
        document.body.appendChild(root);

        pill.addEventListener('click', function () { setOpen(panel.hidden); });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && !panel.hidden) { setOpen(false); pill.focus(); }
        });
        document.addEventListener('click', function (event) {
            if (!panel.hidden && !root.contains(event.target)) setOpen(false);
        });
    }

    function setOpen(open) {
        panel.hidden = !open;
        pill.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function render(status) {
        var conflict = status.state === 'conflict';
        var title = conflict ? 'Git sync conflict' : 'Git sync problem';
        root.style.setProperty('--gsa-accent', conflict ? 'var(--gsa-conflict)' : 'var(--gsa-problem)');
        root.setAttribute('data-state', status.state);
        pillLabel.textContent = title;
        pill.setAttribute('aria-label', title + ' — show details');

        panel.textContent = '';
        var head = el('div', 'gsa-head');
        head.appendChild(el('h3', 'gsa-title', title)).id = 'gsa-title';
        var close = el('button', 'gsa-close', '×');
        close.type = 'button';
        close.setAttribute('aria-label', 'Close');
        close.addEventListener('click', function () { setOpen(false); pill.focus(); });
        head.appendChild(close);
        panel.appendChild(head);

        var meta = [status.repo];
        if (status.since) meta.push('since ' + ago(status.since));
        if (status.last_checked) meta.push('checked ' + ago(status.last_checked));
        panel.appendChild(el('p', 'gsa-meta', meta.filter(Boolean).join(' · ')));

        if (conflict) {
            panel.appendChild(el('p', null,
                'This server and GitHub both changed, so automatic sync is paused for this app. ' +
                'Nothing was overwritten; the app keeps running the server copy until someone reconciles.'));
        } else {
            panel.appendChild(el('p', null, status.message || 'The last sync attempts failed.'));
        }

        var local = status.local_changes || [];
        var remote = status.remote_commits || [];
        if (local.length) {
            panel.appendChild(el('h4', null, 'Changed on this server, not on GitHub'));
            panel.appendChild(list(local));
        }
        if (remote.length) {
            panel.appendChild(el('h4', null, 'New on GitHub, not on this server'));
            panel.appendChild(list(remote));
        }

        panel.appendChild(el('h4', null, 'How to fix'));
        var branch = status.branch || 'main';
        var steps = el('ol');
        if (conflict) {
            steps.appendChild(step(['On the server, open a terminal in ', el('code', null, status.path || '(app folder)'), '.']));
            steps.appendChild(step(['Save the server edits: ', el('code', null, 'git add -A'), ' then ',
                el('code', null, 'git commit -m "Describe the server edits"'), '.']));
            steps.appendChild(step(['Bring in GitHub\u2019s commits: ', el('code', null, 'git pull --no-rebase origin ' + branch),
                ', and resolve any conflicts.']));
            steps.appendChild(step(['Send it back: ', el('code', null, 'git push origin ' + branch), '.']));
            steps.appendChild(step(['The sync resumes within 5 minutes and this alert clears.']));
        } else {
            steps.appendChild(step(['See ', el('code', null, 'C:\\Share\\apps\\autobroll-sync\\logs\\github_poll.log'),
                ' on the server for the full error.']));
            steps.appendChild(step(['This alert clears after the next successful sync.']));
        }
        panel.appendChild(steps);
    }

    function shouldShow(status) {
        if (!status || status.visible === false) return false;
        if (status.state === 'conflict') return true;
        return status.state === 'error' && Number(status.failures || 0) >= PROBLEM_AFTER_FAILURES;
    }

    var timer = null;

    function showing() {
        return !!root && !root.hidden;
    }

    function hide() {
        // Resolved: remove the alert entirely, closing its panel too.
        if (root) {
            setOpen(false);
            root.hidden = true;
        }
        lastKey = '';
    }

    function refresh() {
        clearTimeout(timer);
        fetch(endpoint, { cache: 'no-store', credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (status) {
                if (!shouldShow(status)) {
                    hide();
                    return;
                }
                if (!root) build();
                var key = JSON.stringify(status);
                if (key !== lastKey) {
                    var wasOpen = !panel.hidden;
                    render(status);
                    setOpen(wasOpen);
                    lastKey = key;
                }
                root.hidden = false;
            })
            .catch(function () { /* Not an admin, offline, or no endpoint: stay silent. */ })
            .then(function () {
                timer = setTimeout(refresh, showing() ? POLL_WHILE_SHOWING_MS : POLL_MS);
            });
    }

    function start() {
        refresh();
        // Coming back to the tab re-checks at once, so a fix made elsewhere shows immediately.
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') refresh();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
