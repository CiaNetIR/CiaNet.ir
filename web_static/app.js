// CiaNet Web Panel — vanilla JS single-file SPA (no build step)
// ─────────────────────────────────────────────────────────────────

// ─── API helper ──────────────────────────────────────────────────
// CSRF double-submit (§13.2): سرور بعد از login یک cookie غیر HttpOnly
// به نام cianet_csrf_token ست می‌کنه؛ همان مقدار باید در هدر
// X-CSRF-Token برای همه‌ی درخواست‌های غیر GET ارسال بشه.
function getCsrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)cianet_csrf_token=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (method !== "GET") {
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(path, {
    credentials: "include",
    ...opts,
    headers,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Helpers ─────────────────────────────────────────────────────
// هر مقدار server-controlled که داخل innerHTML می‌ره باید escape بشه.
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// حالت خطای بارگذاری اولیه‌ی صفحه‌ها (سبک dashboard) + دکمه‌ی تلاش مجدد
function renderError(err) {
  const msg = err && err.message ? err.message : String(err);
  document.getElementById("app").innerHTML = layout(`
    <div class="error">خطا: ${escapeHtml(msg)}</div>
    <button class="btn btn-primary mt-2" onclick="location.reload()">🔄 تلاش مجدد</button>
  `);
}

function showToast(msg, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = `toast show ${isError ? "error" : ""}`;
  setTimeout(() => t.classList.remove("show"), 3000);
}

function fmt(n) {
  if (!n && n !== 0) return "۰";
  return new Intl.NumberFormat("fa-IR").format(n);
}
function short(s, n = 8) { return s && s.length > n ? `${s.slice(0, n)}…` : (s || "—"); }

// ─── Auth ────────────────────────────────────────────────────────
let currentUser = null;
async function checkAuth() {
  try {
    const r = await api("/api/auth/me");
    currentUser = r.user;
    return r.user;
  } catch { return null; }
}
async function login(username, password) {
  await api("/api/auth/login", {
    method: "POST", body: JSON.stringify({ username, password })
  });
  location.href = "dashboard.html";
}
async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch {}
  location.href = "login.html";
}

// ─── Sidebar layout ──────────────────────────────────────────────
function sidebar(currentPath) {
  const items = [
    { href: "dashboard.html", label: "داشبورد", icon: "📊" },
    { href: "users.html", label: "کاربران", icon: "👥" },
    { href: "accounts.html", label: "سلف‌بات‌ها", icon: "🤖" },
    { href: "finance.html", label: "امور مالی", icon: "💰" },
    { href: "analytics.html", label: "آنالیتیکس", icon: "📈" },
    { href: "tickets.html", label: "تیکت‌ها", icon: "🎫" },
    { href: "audit.html", label: "Audit Log", icon: "📜" },
    { href: "version.html", label: "نسخه", icon: "🔄" },
    { href: "tools.html", label: "هش و api_id", icon: "🔑" },
    { href: "settings.html", label: "تنظیمات", icon: "⚙️" },
  ];
  return `
    <aside class="sidebar">
      <div class="logo">🌐 CiaNet Panel</div>
      <nav>
        ${items.map(it => `
          <a href="${it.href}" class="${currentPath === it.href ? "active" : ""}">
            <span>${it.icon}</span> ${it.label}
          </a>
        `).join("")}
      </nav>
      <div class="user">
        <span>${currentUser ? escapeHtml(currentUser.username) : "guest"}</span>
        <a href="#" onclick="logout(); return false;" class="text-muted">خروج ↩</a>
      </div>
    </aside>
  `;
}

function layout(content) {
  return `<div class="layout">
    <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-label="منو">☰</button>
    <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
    ${sidebar(location.pathname.split("/").pop())}
    <main class="main">${content}</main>
  </div>`;
}

// boot guard: اگر login نشده و در صفحه‌ی login نیست، redirect کن
async function authGuard() {
  if (location.pathname.endsWith("login.html")) return;
  const user = await checkAuth();
  if (!user) {
    location.href = "login.html";
  }
}

// auto-run auth guard on every page
authGuard();

// ─── Mobile sidebar toggle (BUG-10) — RTL: منو از سمت راست ────────
document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element)) return;
  const toggle = e.target.closest("#sidebarToggle");
  if (toggle) {
    const sb = document.querySelector(".sidebar");
    const bd = document.querySelector(".sidebar-backdrop");
    if (!sb) return;
    const open = sb.classList.toggle("open");
    if (bd) bd.classList.toggle("show", open);
    toggle.textContent = open ? "✕" : "☰";
    return;
  }
  if (e.target.classList.contains("sidebar-backdrop")) {
    const sb = document.querySelector(".sidebar");
    const tg = document.getElementById("sidebarToggle");
    if (sb) sb.classList.remove("open");
    e.target.classList.remove("show");
    if (tg) tg.textContent = "☰";
  }
});
