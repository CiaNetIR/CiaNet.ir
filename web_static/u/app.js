/* CiaNet User Panel — simplified same-origin version
   No server URL config needed — site and API are on the same origin.
*/

const STORAGE_KEY_LICENSE = 'cianet_license_code';

function getStoredLicense() {
  return localStorage.getItem(STORAGE_KEY_LICENSE) || '';
}
function setStoredLicense(code) {
  localStorage.setItem(STORAGE_KEY_LICENSE, code);
}
function clearStored() {
  localStorage.removeItem(STORAGE_KEY_LICENSE);
}

function faDigits(n) {
  const fa = ['۰','۱','۲','۳','۴','۵','۶','۷','۸','۹'];
  return String(n).replace(/[0-9]/g, d => fa[+d]);
}

function formatToman(amount) {
  const sign = amount >= 0 ? '+' : '−';
  return sign + faDigits(Math.abs(amount).toLocaleString('en-US'));
}

// BUG-33: unified Persian (fa-IR / Jalali, Persian digits) date+time format
// for all user pages. Accepts an ISO string, epoch-ms number or Date.
// Same Date-based (browser-local) handling as the previous fa-IR call sites.
function fmtDate(v) {
  if (v === null || v === undefined || v === '') return '';
  const d = new Date(v);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' });
}

// ─── API (same origin, relative URLs) ───

// BUG-11u: read the non-HttpOnly CSRF cookie set at user login and
// double-submit it as X-CSRF-Token on every non-GET request.
function getUserCsrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)cianet_user_csrf_token=([^;]*)/);
  return m ? m[1] : '';
}

async function apiCall(method, path, body = null) {
  const opts = {
    method,
    credentials: 'include',
    headers: {},
  };
  if (method && method.toUpperCase() !== 'GET') {
    const csrfToken = getUserCsrfToken();
    if (csrfToken) opts.headers['X-CSRF-Token'] = csrfToken;
  }
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch (err) {
    throw new Error('خطای شبکه — سرور قابل دسترسی نیست.');
  }
  let data;
  try {
    data = await resp.json();
  } catch (e) {
    data = { detail: resp.statusText };
  }
  if (!resp.ok) {
    const msg = data.detail || data.message || `خطای ${resp.status}`;
    throw new Error(msg);
  }
  return data;
}

// ─── Login ───
async function handleLogin() {
  const codeInput = document.getElementById('license-code');
  const errBox = document.getElementById('error');
  const loadingBox = document.getElementById('loading');
  const btn = document.getElementById('login-btn');
  if (!codeInput || !btn) return;

  btn.addEventListener('click', async () => {
    const licenseCode = codeInput.value.trim().toUpperCase();
    if (!licenseCode) {
      errBox.textContent = 'کد لایسنس را وارد کنید.';
      errBox.hidden = false;
      return;
    }
    errBox.hidden = true;
    loadingBox.hidden = false;
    btn.disabled = true;

    try {
      await apiCall('POST', '/api/user/login', { license_code: licenseCode });
      setStoredLicense(licenseCode);
      window.location.href = 'dashboard.html';
    } catch (err) {
      errBox.textContent = err.message;
      errBox.hidden = false;
      loadingBox.hidden = true;
      btn.disabled = false;
    }
  });

  codeInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') btn.click();
  });
}

// ─── Logout ───
function handleLogout() {
  const btn = document.getElementById('logout-btn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    try { await apiCall('POST', '/api/user/logout'); } catch (e) {}
    clearStored();
    window.location.href = 'login.html';
  });
}

// ─── Auth guard ───
async function requireAuth() {
  if (!getStoredLicense()) {
    window.location.href = 'login.html';
    return null;
  }
  try {
    return await apiCall('GET', '/api/user/me');
  } catch (err) {
    window.location.href = 'login.html';
    return null;
  }
}

// ─── Dashboard ───
async function loadDashboard() {
  const me = await requireAuth();
  if (!me) return;

  document.getElementById('user-id').textContent = me.user_id;
  document.getElementById('username').textContent = me.username || '—';
  document.getElementById('role').textContent = me.role || '—';
  document.getElementById('balance').textContent = faDigits(me.wallet_balance.toLocaleString('en-US'));
  document.getElementById('bots-count').textContent = faDigits(me.n_selfbots);

  const subStatus = me.subscription?.active ? 'فعال' : 'منقضی';
  document.getElementById('sub-status').textContent = subStatus;
  document.getElementById('sub-detail').textContent =
    me.subscription?.active
      ? `${faDigits(me.subscription.days_left)} روز باقی‌مانده` + (me.subscription.plan ? ` · ${me.subscription.plan}` : '')
      : (me.subscription?.plan || 'بدون اشتراک');

  try {
    const wallet = await apiCall('GET', '/api/user/wallet');
    renderTxs(wallet.transactions.slice(0, 5), 'recent-txs');
  } catch (err) {
    document.getElementById('recent-txs').textContent = 'خطا در بارگذاری.';
  }
}

// ─── Wallet ───
let _txsAll = [];
async function loadWallet() {
  const me = await requireAuth();
  if (!me) return;
  document.getElementById('balance').textContent = faDigits(me.wallet_balance.toLocaleString('en-US'));

  try {
    const data = await apiCall('GET', '/api/user/wallet/transactions?limit=50');
    _txsAll = data.transactions || [];
    renderTxs(_txsAll.slice(0, 20), 'tx-list');
  } catch (err) {
    document.getElementById('tx-list').textContent = 'خطا در بارگذاری.';
  }
}

// ─── Tx renderer ───
function renderTxs(txs, containerId) {
  const c = document.getElementById(containerId);
  if (!c) return;
  if (!txs || txs.length === 0) {
    c.textContent = '(تراکنشی ثبت نشده)';
    return;
  }
  c.innerHTML = '';
  for (const t of txs) {
    const div = document.createElement('div');
    div.className = 'tx-item ' + txClass(t.type);
    const amount = t.amount;
    const sign = amount >= 0 ? 'positive' : 'negative';
    const amtStr = (amount >= 0 ? '+' : '−') + faDigits(Math.abs(amount).toLocaleString('en-US')) + ' Toman';
    const dateStr = fmtDate(t.created_at);
    const reason = t.reason || '—';
    div.innerHTML = `
      <div class="tx-amount ${sign}">${amtStr}</div>
      <div class="tx-detail">
        <span class="reason">${escapeHtml(reason)}</span>
        <span class="date">${dateStr} · ${escapeHtml(txTypeLabel(t.type))}</span>
      </div>
      <div class="tx-balance">موجودی: ${faDigits(t.balance_after.toLocaleString('en-US'))}</div>
    `;
    c.appendChild(div);
  }
}

function txClass(type) {
  if (type === 'credit' || type === 'refund') return 'credit';
  if (type === 'debit' || type === 'payment') return 'debit';
  return '';
}

function txTypeLabel(type) {
  return ({
    'credit': 'شارژ',
    'debit': 'کسر',
    'payment': 'پرداخت',
    'admin_adjust': 'تنظیم',
    'refund': 'بازگشت',
  })[type] || type;
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

// ─── Settings ───
async function loadSettings() {
  const me = await requireAuth();
  if (!me) return;
  const lic = document.getElementById('license-input');
  if (lic) lic.value = getStoredLicense();
}

// ─── Router ───
async function init() {
  await handleLogin();
  handleLogout();
  const path = location.pathname;
  if (path.endsWith('dashboard.html')) await loadDashboard();
  else if (path.endsWith('wallet.html')) await loadWallet();
  else if (path.endsWith('settings.html')) await loadSettings();
}

document.addEventListener('DOMContentLoaded', init);
