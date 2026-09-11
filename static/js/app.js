/* Shared helpers for the operator console. No framework, no build step —
   the whole point of this tool is that it runs from a checkout on a laptop the
   night before an event. */

/* ------------------------------------------------------------------ theme */

const Theme = {
  KEY: 'coupon-theme',
  get() {
    try { return localStorage.getItem(Theme.KEY) || 'system'; } catch { return 'system'; }
  },
  apply(mode) {
    if (mode === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', mode);
    try { localStorage.setItem(Theme.KEY, mode); } catch { /* private mode */ }
    document.querySelectorAll('[data-theme-icon]').forEach((el) => {
      const dark = mode === 'dark' || (mode === 'system' &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
      el.querySelector('use').setAttribute('href', dark ? '#i-sun' : '#i-moon');
    });
  },
  toggle() {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.hasAttribute('data-theme') &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
    Theme.apply(dark ? 'light' : 'dark');
  },
};

/* ------------------------------------------------------------------ toasts */

function toast(message, kind = 'ok', timeout = 4200) {
  let host = document.querySelector('.toasts');
  if (!host) {
    host = document.createElement('div');
    host.className = 'toasts';
    document.body.appendChild(host);
  }
  const icon = { ok: '#i-check-circle', error: '#i-x-circle', warn: '#i-alert', info: '#i-info' }[kind] || '#i-info';
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.innerHTML =
    `<svg style="color:var(--${kind === 'error' ? 'danger' : kind === 'warn' ? 'warn' : 'ok'})"><use href="${icon}"/></svg>` +
    `<div style="flex:1">${escapeHtml(message)}</div>` +
    '<button class="close" aria-label="Dismiss"><svg style="width:14px;height:14px"><use href="#i-x"/></svg></button>';
  el.querySelector('.close').onclick = () => el.remove();
  host.appendChild(el);
  if (timeout) setTimeout(() => el.remove(), timeout);
  return el;
}

/* --------------------------------------------------------------------- api */

async function api(path, options = {}) {
  const config = { headers: {}, ...options };
  if (config.body && !(config.body instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
    config.body = JSON.stringify(config.body);
  }
  let response;
  try {
    response = await fetch(path, config);
  } catch (err) {
    throw new Error('Could not reach the server. Is it still running?');
  }
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json')) {
    if (!response.ok) throw new Error(`Server error (${response.status})`);
    return response;
  }
  const data = await response.json();
  if (!response.ok || data.success === false) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.data = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

/* ------------------------------------------------------------------ format */

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtNumber(n) {
  return (n ?? 0).toLocaleString();
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

function fmtRelative(iso) {
  if (!iso) return '—';
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(seconds)) return iso;
  if (seconds < 45) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return fmtTime(iso);
}

function fmtDuration(seconds) {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m < 60 ? `${m}m ${s}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

function statusBadge(status) {
  const map = {
    used:      ['ok', 'Used'],
    sent:      ['accent', 'Sent'],
    generated: ['', 'Issued'],
    pending:   ['warn', 'No coupon'],
    revoked:   ['danger', 'Revoked'],
  };
  const [cls, label] = map[status] || ['', status || '—'];
  return `<span class="badge ${cls}"><span class="dot"></span>${escapeHtml(label)}</span>`;
}

function foodBadge(pref) {
  const veg = pref !== 'Non-Vegetarian';
  return `<span class="badge ${veg ? 'veg' : 'nonveg'}">${veg ? 'Veg' : 'Non-veg'}</span>`;
}

/* ------------------------------------------------------------------ dialog */

function confirmDialog({ title, body, confirmLabel = 'Confirm', danger = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement('dialog');
    dlg.innerHTML =
      `<div class="card-head"><h2>${escapeHtml(title)}</h2></div>` +
      `<div class="card-body">${body}</div>` +
      '<div class="card-foot">' +
      '<button class="btn" data-act="cancel">Cancel</button>' +
      `<button class="btn ${danger ? 'danger' : 'primary'}" data-act="ok">${escapeHtml(confirmLabel)}</button>` +
      '</div>';
    document.body.appendChild(dlg);
    dlg.querySelector('[data-act="cancel"]').onclick = () => { dlg.close(); resolve(false); };
    dlg.querySelector('[data-act="ok"]').onclick = () => { dlg.close(); resolve(true); };
    dlg.addEventListener('close', () => dlg.remove());
    dlg.addEventListener('cancel', () => resolve(false));
    dlg.showModal();
  });
}

/* ----------------------------------------------------------------- helpers */

function debounce(fn, wait = 250) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied to clipboard');
  } catch {
    // Clipboard API needs a secure context; this page is often plain http on a LAN.
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); toast('Copied to clipboard'); }
    catch { toast('Could not copy — select and copy manually', 'warn'); }
    ta.remove();
  }
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span>${escapeHtml(label || 'Working…')}`;
  } else {
    button.disabled = false;
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  Theme.apply(Theme.get());
  document.querySelectorAll('[data-theme-toggle]').forEach((el) => {
    el.addEventListener('click', Theme.toggle);
  });
});
