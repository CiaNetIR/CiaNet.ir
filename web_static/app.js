// CiaNet Web Panel — vanilla JS single-file SPA (no build step)
// ─────────────────────────────────────────────────────────────────

// ─── API helper ──────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.message || `HTTP ${res.status}`);
  }
  return res.json();
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
        <span>${currentUser ? currentUser.username : "guest"}</span>
        <a href="#" onclick="logout(); return false;" class="text-muted">خروج ↩</a>
      </div>
    </aside>
  `;
}

function layout(content) {
  return `<div class="layout">${sidebar(location.pathname.split("/").pop())}<main class="main">${content}</main></div>`;
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
