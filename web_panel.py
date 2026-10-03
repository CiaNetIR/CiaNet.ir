"""
web_panel.py — CiaNet Web Panel Backend (FastAPI)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Backend API برای پنل وبِ CiaNet. از main.py توابع utility رو import می‌کنه
(load_config, save_config, get_user, list_users, get_active_subscription, ...)
و یه API REST روی port 8000 فراهم می‌کنه.

نقاط پایانی (Endpoints):
  POST   /api/auth/login          — ورود با username/password
  POST   /api/auth/logout         — خروج
  GET    /api/auth/me             — کاربر فعلی

  GET    /api/dashboard           — آمار کلی
  GET    /api/users               — لیست کاربران (با فیلتر/صفحه‌بندی)
  GET    /api/users/{id}          — جزئیات یک کاربر
  PATCH  /api/users/{id}          — ویرایش کاربر (role, reseller_id, ...)
  DELETE /api/users/{id}          — حذف کامل کاربر
  POST   /api/users/{id}/extend   — تمدید اشتراک

  GET    /api/accounts            — لیست سلف‌بات‌ها (همه)
  GET    /api/accounts/{tag}       — جزئیات یک سلف‌بات
  POST   /api/accounts/{tag}/enable
  POST   /api/accounts/{tag}/disable
  DELETE /api/accounts/{tag}       — حذف
  PATCH  /api/accounts/{tag}/proxy — تنظیم پروکسی

  GET    /api/finance/payments    — لیست پرداخت‌ها
  POST   /api/finance/payments/{id}/approve
  POST   /api/finance/payments/{id}/reject
  GET    /api/finance/stats       — MRR / revenue chart

  GET    /api/tickets             — لیست تیکت‌ها
  GET    /api/tickets/{id}        — جزئیات + تاریخچه
  POST   /api/tickets/{id}/reply  — پاسخ

  GET    /api/audit-log           — جدول logs (با فیلتر)
  GET    /api/version             — اطلاعات نسخه
  POST   /api/version/apply-update
  GET    /api/version/rollback-list
  POST   /api/version/rollback

  GET    /api/settings            — تنظیمات سیستم
  PATCH  /api/settings            — ویرایش

  GET    /api/tools/api-creds     — همه‌ی api_id/api_hash ها
  POST   /api/tools/api-creds     — افزودن api_id/hash جدید
  POST   /api/tools/api-creds/rotate — rotate api_id روی همه‌ی اکانت‌ها

Auth:
  همه‌ی endpoint‌ها نیاز به session cookie دارن. ورود با
  PANEL_ADMIN_USER / PANEL_ADMIN_PASS_HASH env var‌ها.
  password hash با bcrypt (passlib) hash می‌شه.

CORS:
  برای localhost:3000 (Next.js dev) و production domain فعال است.

Run:
  uvicorn web_panel:app --host 127.0.0.1 --port 8000
"""

import asyncio
import hashlib
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project dir on path
_PROJECT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PROJECT_DIR))

from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3

# lazy import main module to avoid circular imports / heavy startup
_main_mod = None
def _main():
    global _main_mod
    if _main_mod is None:
        import main as _m
        _main_mod = _m
    return _main_mod


# ─── Configuration ────────────────────────────────────────────────────
PANEL_ADMIN_USER = os.environ.get("PANEL_ADMIN_USER", "admin").strip()
# bcrypt hash. برای تولید: python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('secret'))"
# در صورت تنظیم‌نبودن، خطا در startup لاگ می‌شه ولی پنل همچنان بالا میاد
# (با empty-hash می‌شه لاگین به‌صورت disabled).
PANEL_ADMIN_PASS_HASH = os.environ.get("PANEL_ADMIN_PASS_HASH", "").strip()
SESSION_SECRET = os.environ.get("PANEL_SESSION_SECRET", "") or secrets.token_hex(32)
SESSION_TTL_SEC = 8 * 3600  # 8 hours

# CORS: dev + production
ALLOWED_ORIGINS = os.environ.get("PANEL_CORS_ORIGINS", "http://localhost:3000").split(",")

DATA_DIR = _main().DATA_DIR if hasattr(_main(), 'DATA_DIR') else (_PROJECT_DIR / "data")
SAAS_DB = _main().DB_PATH if hasattr(_main(), 'DB_PATH') else (DATA_DIR / "saas.db")
BOT_DB = _main().DB_NAME if hasattr(_main(), 'DB_NAME') else (DATA_DIR / "bot_data.db")


# ─── Session store (in-memory) ───────────────────────────────────────
# در production به‌تر است در Redis ذخیره بشه ولی برای single-instance اون
# پنل کافیه. در صورت restart، session‌ها expire می‌شن (کاربر دوباره login کنه).
_sessions: Dict[str, float] = {}  # token -> created_at


def _create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time()
    return token


def _valid_session(request: Request) -> bool:
    token = request.cookies.get("cianet_panel_session")
    if not token:
        return False
    created = _sessions.get(token)
    if not created:
        return False
    if time.time() - created > SESSION_TTL_SEC:
        _sessions.pop(token, None)
        return False
    return True


def _invalidate_session(request: Request) -> None:
    token = request.cookies.get("cianet_panel_session")
    if token:
        _sessions.pop(token, None)


# ─── License-based user auth (separate from admin) ─────────────
# برای GitHub Pages site: کاربر با کد لایسنس لاگین می‌کنه (نه یوزر/پسورد).
# این session جداست از admin session تا تداخل نداشته باشند.
_user_sessions: Dict[str, dict] = {}  # token -> {user_id, created_at}
USER_SESSION_TTL_SEC = 24 * 3600  # 24 hours

def _create_user_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _user_sessions[token] = {"user_id": user_id, "created_at": time.time()}
    return token

def _valid_user_session(request: Request) -> bool:
    token = request.cookies.get("cianet_user_session")
    if not token:
        return False
    s = _user_sessions.get(token)
    if not s:
        return False
    if time.time() - s["created_at"] > USER_SESSION_TTL_SEC:
        _user_sessions.pop(token, None)
        return False
    return True

def _get_user_id_from_session(request: Request) -> Optional[int]:
    token = request.cookies.get("cianet_user_session")
    if not token:
        return None
    s = _user_sessions.get(token)
    if not s or time.time() - s["created_at"] > USER_SESSION_TTL_SEC:
        return None
    return s["user_id"]

def _invalidate_user_session(request: Request) -> None:
    token = request.cookies.get("cianet_user_session")
    if token:
        _user_sessions.pop(token, None)

def require_user_auth(request: Request) -> int:
    """Returns user_id if authenticated, else raises 401."""
    uid = _get_user_id_from_session(request)
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized — user login required",
        )
    return uid


def require_auth(request: Request):
    if not _valid_session(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized — login required",
        )


# ─── Password verification (bcrypt) ──────────────────────────────────
def _verify_password(plain: str, hashed: str) -> bool:
    """
    Verify password against hash. Supports:
      - bcrypt (default): $2b$... hash format from passlib
      - sha256 fallback: "sha256:hexdigest" format from install_panel.sh
        when passlib/bcrypt C extension fails to install
    """
    if not hashed:
        return False
    # PATCH (v2.1.4): support sha256 fallback از install_panel.sh
    if hashed.startswith("sha256:"):
        try:
            import hashlib
            expected = hashed[len("sha256:"):]
            actual = hashlib.sha256(plain.encode("utf-8")).hexdigest()
            # constant-time comparison
            if len(expected) != len(actual):
                return False
            return all(a == b for a, b in zip(expected, actual))
        except Exception:
            return False
    # default: bcrypt
    try:
        from passlib.hash import bcrypt
        return bcrypt.verify(plain, hashed)
    except Exception:
        return False


# ─── Pydantic models ──────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class UserUpdate(BaseModel):
    role: Optional[str] = None
    reseller_id: Optional[int] = None
    reseller_max_users: Optional[int] = None
    is_active: Optional[bool] = None


class ExtendRequest(BaseModel):
    days: int
    plan: Optional[str] = None


class ProxyUpdate(BaseModel):
    proxy_type: Optional[str] = None  # "socks5" | "http" | "mtproto" | None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None
    # برای mtproto:
    proxy_secret: Optional[str] = None


class ApiCredAdd(BaseModel):
    api_id: int
    api_hash: str
    label: Optional[str] = None


class TicketReply(BaseModel):
    text: str


class SettingsUpdate(BaseModel):
    maintenance_mode: Optional[bool] = None
    channel_username: Optional[str] = None
    wallet_address_usdt: Optional[str] = None
    min_commit_hash: Optional[str] = None


# ─── v2.8.0: License auth + wallet request models ─────────────
class LicenseLoginRequest(BaseModel):
    license_code: str

class WalletCreditRequest(BaseModel):
    amount: int
    reason: Optional[str] = ""

class WalletDebitRequest(BaseModel):
    amount: int
    reason: Optional[str] = ""

class WalletPayRequest(BaseModel):
    amount: int
    ref: Optional[str] = ""


# ─── FastAPI app ─────────────────────────────────────────────────────
app = FastAPI(
    title="CiaNet Web Panel API",
    description="Backend REST API for the CiaNet selfbot management panel",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    print(f"🌐 CiaNet Web Panel API on http://127.0.0.1:8000", flush=True)
    print(f"   PANEL_ADMIN_USER={PANEL_ADMIN_USER!r}", flush=True)
    if not PANEL_ADMIN_PASS_HASH:
        print("   ⚠️  PANEL_ADMIN_PASS_HASH not set — login disabled!", flush=True)
        print("   Run: python3 -c \"from passlib.hash import bcrypt; print(bcrypt.hash('yourpass'))\"",
              flush=True)
    print(f"   CORS origins: {ALLOWED_ORIGINS}", flush=True)
    print(f"   Data dir: {DATA_DIR}", flush=True)


@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception):
    # در production، جزئیات خطا به کلاینت نشون داده نمی‌شه
    import traceback
    print(f"❌ [web_panel] {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal error: {type(exc).__name__}", "message": str(exc)[:200]},
    )


# ─── Auth endpoints ──────────────────────────────────────────────────
@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, response: Response):
    if not PANEL_ADMIN_PASS_HASH:
        raise HTTPException(503, "Login disabled — set PANEL_ADMIN_PASS_HASH env var")
    # PATCH (v2.1.5): case-insensitive و trim — قبلاً «Admin» و «admin»
    # متفاوت محسوب می‌شدند و کاربر گیج می‌شد.
    if (req.username or "").strip().lower() != PANEL_ADMIN_USER.strip().lower():
        raise HTTPException(401, "Invalid credentials")
    if not _verify_password(req.password, PANEL_ADMIN_PASS_HASH):
        raise HTTPException(401, "Invalid credentials")
    token = _create_session()
    response.set_cookie(
        key="cianet_panel_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SEC,
        secure=False,  # nginx terminates SSL — set to True in production via env
    )
    return {"ok": True, "user": {"username": req.username, "role": "OWNER"}}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    _invalidate_session(request)
    response.delete_cookie("cianet_panel_session")
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    if not _valid_session(request):
        raise HTTPException(401, "Not authenticated")
    return {"user": {"username": PANEL_ADMIN_USER, "role": "OWNER"}}


# ─── Dashboard ───────────────────────────────────────────────────────
@app.get("/api/dashboard")
async def dashboard(request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    total_accounts = len(cfg)
    enabled_accounts = sum(1 for a in cfg.values() if isinstance(a, dict) and not a.get("disabled"))
    running_accounts = len(m.ACCOUNTS)  # accounts actually running
    # users in DB
    try:
        with m._conn() as c:
            total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active_subs = c.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
            ).fetchone()[0]
            expired_subs = c.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE status='expired'"
            ).fetchone()[0]
            open_tickets = c.execute(
                "SELECT COUNT(*) FROM tickets WHERE status='open'"
            ).fetchone()[0]
            # PATCH (v2.1.5): table‌های saas.db به این شکل هستند:
            #   purchases (amount, status, approved_at, created_at)
            #   tickets (status: open/closed)
            # قبلاً amount_toman و paid_at استفاده می‌شد که وجود ندارن.
            # MRR rough estimate: sum از همه‌ی purchases با status='approved'
            mrr_row = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM purchases WHERE status='approved'"
            ).fetchone()
            mrr = mrr_row[0] if mrr_row else 0
            # revenue 30d
            rev_30d = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM purchases "
                "WHERE status='approved' AND (approved_at IS NOT NULL AND approved_at >= date('now','-30 days'))"
            ).fetchone()[0]
            # 30-day chart (simple daily revenue)
            daily_rev = c.execute(
                "SELECT date(approved_at) as d, SUM(amount) as v FROM purchases "
                "WHERE status='approved' AND approved_at IS NOT NULL "
                "AND approved_at >= date('now','-30 days') "
                "GROUP BY date(approved_at) ORDER BY d"
            ).fetchall()
    except Exception as e:
        return {"error": f"DB: {e}"}

    return {
        "accounts": {
            "total": total_accounts,
            "enabled": enabled_accounts,
            "running": running_accounts,
            "stopped": total_accounts - enabled_accounts,
        },
        "users": {"total": total_users},
        "subscriptions": {"active": active_subs, "expired": expired_subs},
        "tickets": {"open": open_tickets},
        "finance": {
            "mrr_toman": mrr,
            "revenue_30d_toman": rev_30d,
            "daily_revenue": [{"date": r["d"], "amount": r["v"]} for r in (daily_rev or [])],
        },
        "version": {
            "local_commit": _get_local_commit(),
            "remote_commit": _get_remote_commit(),
            "build": m.BUILD_VERSION if hasattr(m, "BUILD_VERSION") else None,
        },
    }


# ─── Users endpoints ─────────────────────────────────────────────────
@app.get("/api/users")
async def users_list(
    request: Request,
    q: str = "",
    role: str = "",
    page: int = 1,
    page_size: int = 50,
    _: None = Depends(require_auth),
):
    m = _main()
    offset = (max(1, page) - 1) * page_size
    where = []
    params = []
    if q:
        try:
            uid_int = int(q)
            where.append("(user_id = ? OR username LIKE ? OR first_name LIKE ?)")
            params.extend([uid_int, f"%{q}%", f"%{q}%"])
        except ValueError:
            where.append("(username LIKE ? OR first_name LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
    if role:
        where.append("user_id IN (SELECT user_id FROM admins WHERE role=?)")
        params.append(role)
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        with m._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM users {where_clause}", params).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM users {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            # join با admins برای role
            for r in rows:
                ar = c.execute(
                    "SELECT role, reseller_max_users FROM admins WHERE user_id=?",
                    (r["user_id"],),
                ).fetchone()
                r_dict = dict(r)
                r_dict["role"] = ar["role"] if ar else "USER"
                r_dict["reseller_max_users"] = ar["reseller_max_users"] if ar else None
                # sub info
                sub = c.execute(
                    "SELECT plan, status, expire_date FROM subscriptions "
                    "WHERE user_id=? ORDER BY id DESC LIMIT 1",
                    (r["user_id"],),
                ).fetchone()
                r_dict["plan"] = sub["plan"] if sub else None
                r_dict["sub_status"] = sub["status"] if sub else None
                r_dict["expire_date"] = sub["expire_date"] if sub else None
            return {
                "items": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.get("/api/users/{user_id}")
async def user_detail(user_id: int, request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, "User not found")
            r = dict(row)
            ar = c.execute(
                "SELECT role, added_by, reseller_max_users, created_at FROM admins WHERE user_id=?",
                (user_id,),
            ).fetchone()
            r["role"] = ar["role"] if ar else "USER"
            r["reseller_max_users"] = ar["reseller_max_users"] if ar else None
            subs = c.execute(
                "SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
            r["subscriptions"] = [dict(s) for s in subs]
            # user's accounts
            cfg = m.load_config()
            r["accounts"] = [
                {"tag": tag, **acc}
                for tag, acc in cfg.items()
                if isinstance(acc, dict) and acc.get("owner_user_id") == user_id
            ]
            return r
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.patch("/api/users/{user_id}")
async def user_update(user_id: int, update: UserUpdate, request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            existing = c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not existing:
                raise HTTPException(404, "User not found")
            if update.role:
                if update.role not in ("ADMIN", "RESELLER", "USER"):
                    raise HTTPException(400, "Invalid role")
                if update.role == "USER":
                    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
                else:
                    c.execute(
                        "INSERT OR REPLACE INTO admins (user_id, role, added_by, reseller_max_users, created_at) "
                        "VALUES (?, ?, ?, ?, datetime('now'))",
                        (user_id, update.role, m.ADMIN_ID, update.reseller_max_users or 0),
                    )
            if update.reseller_id is not None:
                c.execute("UPDATE users SET reseller_id=? WHERE user_id=?", (update.reseller_id, user_id))
            c.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.delete("/api/users/{user_id}")
async def user_delete(user_id: int, request: Request, _: None = Depends(require_auth)):
    m = _main()
    if user_id == m.ADMIN_ID:
        raise HTTPException(400, "Cannot delete OWNER")
    try:
        # استفاده از delete_user_completely_async که به‌صورت اتمیک همه‌چیز رو پاک می‌کنه
        # ولی چون اینجا sync هست، یک نسخه‌ی ساده‌تر اینجا اجرا می‌کنیم
        with m._conn() as c:
            # FK order
            c.execute("DELETE FROM ticket_messages WHERE ticket_id IN (SELECT id FROM tickets WHERE user_id=?)", (user_id,))
            c.execute("DELETE FROM tickets WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM subscriptions WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM purchases WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM permission_grants WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
            c.commit()
        # remove from config.json
        cfg = m.load_config()
        to_remove = [
            tag for tag, acc in cfg.items()
            if isinstance(acc, dict) and acc.get("owner_user_id") == user_id
        ]
        for tag in to_remove:
            cfg.pop(tag, None)
            # remove session files
            for suffix in ("", "-journal", "-shm", "-wal"):
                p = os.path.join(m.SESSIONS_DIR, f"{tag}.session{suffix}")
                try:
                    os.remove(p)
                except OSError:
                    pass
        if to_remove:
            m.save_config(cfg)
        return {"ok": True, "removed_accounts": to_remove}
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.post("/api/users/{user_id}/extend")
async def user_extend(user_id: int, req: ExtendRequest, request: Request, _: None = Depends(require_auth)):
    m = _main()
    if req.days <= 0 or req.days > 3650:
        raise HTTPException(400, "days must be 1-3650")
    try:
        with m._conn() as c:
            # آخرین اشتراک فعال/منقضی‌شده رو extension کن، یا یکی بساز
            # PATCH (v2.1.5): status رو هم SELECT کن تا در شرط استفاده بشه
            sub = c.execute(
                "SELECT id, expire_date, plan, status FROM subscriptions "
                "WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            from datetime import datetime, timedelta
            if sub and sub["status"] == "active":
                # extend از expire_date فعلی
                try:
                    base = datetime.fromisoformat(sub["expire_date"])
                except Exception:
                    base = datetime.now()
                new_expire = base + timedelta(days=req.days)
                c.execute(
                    "UPDATE subscriptions SET expire_date=? WHERE id=?",
                    (new_expire.isoformat(), sub["id"]),
                )
            else:
                # ساب جدید
                new_expire = datetime.now() + timedelta(days=req.days)
                # اگه sub بود ولی status != active، plan قبلی رو نگه دار
                plan_name = "basic"
                if sub and sub["plan"]:
                    plan_name = sub["plan"]
                if req.plan:
                    plan_name = req.plan
                c.execute(
                    "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status) "
                    "VALUES (?, ?, ?, ?, 'active')",
                    (user_id, plan_name,
                     datetime.now().isoformat(), new_expire.isoformat()),
                )
            c.commit()
        return {"ok": True, "new_expire": new_expire.isoformat()}
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


# ─── Accounts (selfbots) endpoints ───────────────────────────────────
@app.get("/api/accounts")
async def accounts_list(
    request: Request,
    q: str = "",
    page: int = 1,
    page_size: int = 50,
    _: None = Depends(require_auth),
):
    m = _main()
    cfg = m.load_config()
    items = []
    for tag, acc in cfg.items():
        if not isinstance(acc, dict):
            continue
        if q:
            q_l = q.lower()
            if q_l not in tag.lower() and q_l not in (acc.get("phone") or "").lower():
                continue
        entry = m.ACCOUNTS.get(tag)
        is_running = entry is not None
        items.append({
            "tag": tag,
            "phone": acc.get("phone"),
            "type": acc.get("type", "user"),
            "owner_user_id": acc.get("owner_user_id"),
            "disabled": bool(acc.get("disabled")),
            "disabled_reason": acc.get("disabled_reason"),
            "proxy_set": bool(acc.get("proxy")),
            "provision_source": acc.get("provision_source"),
            "running": is_running,
            "runtime_status": m.BOT_STATUS.get(tag, "stopped") if is_running else "stopped",
        })
    total = len(items)
    # pagination
    offset = (max(1, page) - 1) * page_size
    paged = items[offset:offset+page_size]
    return {"items": paged, "total": total, "page": page, "page_size": page_size}


@app.get("/api/accounts/{tag}")
async def account_detail(tag: str, request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    if tag not in cfg:
        raise HTTPException(404, "Account not found")
    acc = cfg[tag]
    entry = m.ACCOUNTS.get(tag)
    return {
        "tag": tag,
        "acc": acc,
        "running": entry is not None,
        "runtime_status": m.BOT_STATUS.get(tag, "stopped") if entry else "stopped",
        "ban_count": getattr(entry.bot, "ban_count", 0) if entry and hasattr(entry, "bot") else 0,
        "fatal_auth_error": getattr(entry.bot, "_fatal_auth_error", False) if entry and hasattr(entry, "bot") else False,
    }


@app.post("/api/accounts/{tag}/enable")
async def account_enable(tag: str, request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    if tag not in cfg:
        raise HTTPException(404, "Account not found")
    if not cfg[tag].get("disabled"):
        return {"ok": True, "message": "Already enabled"}
    cfg[tag]["disabled"] = False
    cfg[tag].pop("disabled_reason", None)
    m.save_config(cfg)
    # schedule runtime start (async) — اما چون sync، فقط flag رو ست می‌کنیم
    # سرویس خودش در next restart یا تله‌گرام callback اکانت رو start می‌کنه
    # برای start فوری، می‌تونیم create_task بزنیم اگه event loop داشته باشیم
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(m.ensure_started(tag, cfg[tag], caller="web_panel.enable"))
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/accounts/{tag}/disable")
async def account_disable(tag: str, request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    if tag not in cfg:
        raise HTTPException(404, "Account not found")
    cfg[tag]["disabled"] = True
    cfg[tag]["disabled_reason"] = "manual_web_panel"
    m.save_config(cfg)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(m.ensure_stopped(tag, "web_panel.disable"))
    except Exception:
        pass
    return {"ok": True}


@app.delete("/api/accounts/{tag}")
async def account_delete(tag: str, request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    if tag not in cfg:
        raise HTTPException(404, "Account not found")
    # stop runtime first
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            await loop.run_in_executor(
                None,
                lambda: asyncio.run(m.ensure_stopped(tag, "web_panel.delete"))
            )
    except Exception:
        pass
    cfg.pop(tag, None)
    m.save_config(cfg)
    # remove session files
    for suffix in ("", "-journal", "-shm", "-wal"):
        p = os.path.join(m.SESSIONS_DIR, f"{tag}.session{suffix}")
        try:
            os.remove(p)
        except OSError:
            pass
    return {"ok": True}


@app.patch("/api/accounts/{tag}/proxy")
async def account_proxy_update(tag: str, update: ProxyUpdate, request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    if tag not in cfg:
        raise HTTPException(404, "Account not found")
    if update.proxy_type is None:
        cfg[tag].pop("proxy", None)
    else:
        proxy_cfg: Dict[str, Any] = {"type": update.proxy_type}
        if update.proxy_host:
            proxy_cfg["host"] = update.proxy_host
        if update.proxy_port:
            proxy_cfg["port"] = update.proxy_port
        if update.proxy_user:
            proxy_cfg["user"] = update.proxy_user
        if update.proxy_pass:
            proxy_cfg["pass"] = update.proxy_pass
        if update.proxy_secret:
            proxy_cfg["secret"] = update.proxy_secret
        cfg[tag]["proxy"] = proxy_cfg
    m.save_config(cfg)
    return {"ok": True}


# ─── Finance endpoints ───────────────────────────────────────────────
@app.get("/api/finance/payments")
async def finance_payments(
    request: Request,
    status_filter: str = "",
    page: int = 1,
    page_size: int = 50,
    _: None = Depends(require_auth),
):
    m = _main()
    where = []
    params = []
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (max(1, page) - 1) * page_size
    try:
        with m._conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) FROM purchases {where_clause}", params
            ).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM purchases {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        # اگر جدول purchases وجود نداشت
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "error": str(e)}


@app.post("/api/finance/payments/{pay_id}/approve")
async def finance_approve(pay_id: int, request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            # PATCH (v2.1.5): approved_at رو هم ست کن
            r = c.execute(
                "UPDATE purchases SET status='approved', approved_at=datetime('now') WHERE id=?",
                (pay_id,),
            )
            c.commit()
            if r.rowcount == 0:
                raise HTTPException(404, "Payment not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.post("/api/finance/payments/{pay_id}/reject")
async def finance_reject(pay_id: int, request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            r = c.execute("UPDATE purchases SET status='rejected' WHERE id=?", (pay_id,))
            c.commit()
            if r.rowcount == 0:
                raise HTTPException(404, "Payment not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.get("/api/finance/stats")
async def finance_stats(request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            # PATCH (v2.1.5): amount (نه amount_toman)، approved_at (نه paid_at)
            mrr = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM purchases WHERE status='approved'"
            ).fetchone()[0]
            rev_30d = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM purchases "
                "WHERE status='approved' AND approved_at IS NOT NULL "
                "AND approved_at >= date('now','-30 days')"
            ).fetchone()[0]
            daily = c.execute(
                "SELECT date(approved_at) as d, SUM(amount) as v FROM purchases "
                "WHERE status='approved' AND approved_at IS NOT NULL "
                "AND approved_at >= date('now','-30 days') "
                "GROUP BY date(approved_at) ORDER BY d"
            ).fetchall()
            return {
                "mrr_total_toman": mrr,
                "revenue_30d_toman": rev_30d,
                "daily": [{"date": r["d"], "amount": r["v"]} for r in daily],
            }
    except Exception as e:
        return {"error": str(e)}


# ─── Tickets ─────────────────────────────────────────────────────────
@app.get("/api/tickets")
async def tickets_list(
    request: Request,
    status_filter: str = "open",
    page: int = 1,
    page_size: int = 50,
    _: None = Depends(require_auth),
):
    m = _main()
    where = []
    params = []
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (max(1, page) - 1) * page_size
    try:
        with m._conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) FROM tickets {where_clause}", params
            ).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM tickets {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "error": str(e)}


@app.get("/api/tickets/{ticket_id}")
async def ticket_detail(ticket_id: int, request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            t = c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if not t:
                raise HTTPException(404, "Ticket not found")
            msgs = c.execute(
                "SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id",
                (ticket_id,),
            ).fetchall()
            return {"ticket": dict(t), "messages": [dict(m_) for m_ in msgs]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.post("/api/tickets/{ticket_id}/reply")
async def ticket_reply(ticket_id: int, reply: TicketReply, request: Request, _: None = Depends(require_auth)):
    m = _main()
    try:
        with m._conn() as c:
            t = c.execute("SELECT 1 FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if not t:
                raise HTTPException(404, "Ticket not found")
            # PATCH (v2.1.5): ticket_messages schema:
            #   (ticket_id, sender_role, sender_id, text, created_at)
            # قبلاً body و sent_at استفاده می‌شد که وجود ندارن.
            c.execute(
                "INSERT INTO ticket_messages (ticket_id, sender_role, sender_id, text, created_at) "
                "VALUES (?, 'admin', ?, ?, datetime('now'))",
                (ticket_id, m.ADMIN_ID, reply.text),
            )
            # PATCH (v2.1.5): tickets status enum: open/closed (نه answered)
            c.execute("UPDATE tickets SET status='closed' WHERE id=?", (ticket_id,))
            c.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


# ─── Audit log ────────────────────────────────────────────────────────
@app.get("/api/audit-log")
async def audit_log(
    request: Request,
    actor_id: int = 0,
    action: str = "",
    page: int = 1,
    page_size: int = 100,
    _: None = Depends(require_auth),
):
    m = _main()
    where = []
    params = []
    if actor_id:
        where.append("actor_id=?")
        params.append(actor_id)
    if action:
        where.append("action LIKE ?")
        params.append(f"%{action}%")
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (max(1, page) - 1) * page_size
    try:
        with m._conn() as c:
            # جدول logs وجود نداشت → table info
            try:
                total = c.execute(
                    f"SELECT COUNT(*) FROM logs {where_clause}", params
                ).fetchone()[0]
                rows = c.execute(
                    f"SELECT * FROM logs {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                    params + [page_size, offset],
                ).fetchall()
                return {"items": [dict(r) for r in rows], "total": total}
            except sqlite3.OperationalError:
                return {"items": [], "total": 0, "error": "logs table not found"}
    except Exception as e:
        return {"items": [], "total": 0, "error": str(e)}


# ─── Version management ──────────────────────────────────────────────
def _get_local_commit() -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_PROJECT_DIR),
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _get_remote_commit() -> str:
    try:
        import subprocess
        subprocess.run(
            ["git", "fetch", "origin", "main", "--quiet"],
            cwd=str(_PROJECT_DIR), capture_output=True, text=True, timeout=15,
        )
        r = subprocess.run(
            ["git", "rev-parse", "origin/main"], cwd=str(_PROJECT_DIR),
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


@app.get("/api/version")
async def version_info(request: Request, _: None = Depends(require_auth)):
    local = _get_local_commit()
    remote = _get_remote_commit()
    pending = []
    if local and remote and local != remote:
        try:
            import subprocess
            r = subprocess.run(
                ["git", "log", "--oneline", f"{local}..origin/main"],
                cwd=str(_PROJECT_DIR), capture_output=True, text=True, timeout=5,
            )
            pending = [l for l in r.stdout.strip().split("\n") if l]
        except Exception:
            pass
    # rollback candidates
    rollback_files = []
    versions_dir = _PROJECT_DIR / "versions"
    if versions_dir.exists():
        for f in sorted(versions_dir.glob("main.py.pre-*"), reverse=True)[:10]:
            rollback_files.append(f.name)
        for f in sorted(versions_dir.glob("v*.py"), reverse=True)[:10]:
            rollback_files.append(f.name)
    return {
        "local_commit": local,
        "remote_commit": remote,
        "pending_commits": pending,
        "is_up_to_date": local == remote,
        "rollback_files": rollback_files,
    }


@app.post("/api/version/apply-update")
async def version_apply(request: Request, _: None = Depends(require_auth)):
    # این endpoint از cianet_updater.apply_update استفاده می‌کنه
    # و در thread executor اجرا می‌شه تا event loop block نشه
    try:
        from cianet_updater import apply_update
        loop = asyncio.get_event_loop()
        success, msg = await loop.run_in_executor(None, apply_update)
        if success:
            return {"ok": True, "message": msg, "note": "Service will restart automatically"}
        else:
            return {"ok": False, "message": msg}
    except Exception as e:
        raise HTTPException(500, f"Update failed: {e}")


@app.post("/api/version/rollback")
async def version_rollback(request: Request, body: dict, _: None = Depends(require_auth)):
    """Body: {"filename": "main.py.pre-rollback.1727..."}"""
    filename = body.get("filename")
    if not filename:
        raise HTTPException(400, "filename required")
    # security: filename نباید path traversal داشته باشه
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    main_py = _PROJECT_DIR / "main.py"
    versions_dir = _PROJECT_DIR / "versions"
    src = versions_dir / filename
    if not src.is_file():
        raise HTTPException(404, f"Version file not found: {filename}")
    # backup current
    import shutil, time as _time
    ts = int(_time.time())
    backup = versions_dir / f"main.py.pre-rollback.{ts}"
    shutil.copy2(main_py, backup)
    # replace
    shutil.copy2(src, main_py)
    # restart
    try:
        import subprocess
        subprocess.Popen(
            ["systemctl", "restart", "cianet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return {"ok": True, "warning": f"Manual restart needed: {e}", "backup": backup.name}
    return {"ok": True, "backup": backup.name, "message": "Rollback applied, restarting"}


# ─── Settings ─────────────────────────────────────────────────────────
@app.get("/api/settings")
async def settings_get(request: Request, _: None = Depends(require_auth)):
    return {
        "maintenance_mode": bool(_main()._MAINTENANCE_MODE if hasattr(_main(), '_MAINTENANCE_MODE') else False),
        "channel_username": os.environ.get("CIANET_CHANNEL", ""),
        "wallet_address_usdt": os.environ.get("CIANET_WALLET_USDT", ""),
        "min_commit_hash": os.environ.get("CIANET_MIN_COMMIT", ""),
        "panel_user": PANEL_ADMIN_USER,
        "owner_id": _main().ADMIN_ID,
        "owner_ids": list(_main().OWNER_IDS) if hasattr(_main(), 'OWNER_IDS') else [_main().ADMIN_ID],
    }


@app.patch("/api/settings")
async def settings_update(update: SettingsUpdate, request: Request, _: None = Depends(require_auth)):
    m = _main()
    if update.maintenance_mode is not None:
        if hasattr(m, '_MAINTENANCE_MODE'):
            m._MAINTENANCE_MODE = update.maintenance_mode
    # برای env-based settings، نمی‌تونیم در runtime عوض کنیم — این فقط read-only نمایش می‌ده
    return {
        "ok": True,
        "note": "Env-based settings require server restart to take effect",
        "applied": {"maintenance_mode": update.maintenance_mode},
    }


# ─── Tools: api_id / api_hash ────────────────────────────────────────
@app.get("/api/tools/api-creds")
async def tools_api_creds(request: Request, _: None = Depends(require_auth)):
    m = _main()
    cfg = m.load_config()
    seen = {}
    for tag, acc in cfg.items():
        if not isinstance(acc, dict):
            continue
        api_id = acc.get("api_id")
        api_hash = acc.get("api_hash")
        if api_id and api_hash:
            key = (api_id, api_hash)
            if key not in seen:
                seen[key] = {"api_id": api_id, "api_hash": api_hash, "used_by": []}
            seen[key]["used_by"].append(tag)
    return {"items": list(seen.values())}


@app.post("/api/tools/api-creds")
async def tools_api_creds_add(cred: ApiCredAdd, request: Request, _: None = Depends(require_auth)):
    """Add a new api_id/api_hash pair — applied to newly-added accounts going forward."""
    # در حال حاضر، api_id/api_hash به‌صورت per-account در config.json ذخیره می‌شه.
    # این endpoint فقط در یک جدول جدا ذخیره می‌کنه برای استفاده‌ی آینده.
    # در v1.1 می‌تونیم api_id pool رو پیاده‌سازی کنیم.
    try:
        creds_file = _PROJECT_DIR / "data" / "api_creds.json"
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if creds_file.exists():
            existing = json.loads(creds_file.read_text() or "[]")
        existing.append({
            "api_id": cred.api_id,
            "api_hash": cred.api_hash,
            "label": cred.label,
            "added_at": int(time.time()),
        })
        creds_file.write_text(json.dumps(existing, indent=2))
        return {"ok": True, "total": len(existing)}
    except Exception as e:
        raise HTTPException(500, f"Save failed: {e}")


@app.post("/api/tools/api-creds/rotate")
async def tools_api_creds_rotate(request: Request, _: None = Depends(require_auth)):
    """Rotate api_id/api_hash on ALL accounts to the next one in the pool."""
    creds_file = _PROJECT_DIR / "data" / "api_creds.json"
    if not creds_file.exists():
        raise HTTPException(400, "No api creds pool — add one first via POST /api/tools/api-creds")
    pool = json.loads(creds_file.read_text() or "[]")
    if len(pool) < 2:
        raise HTTPException(400, "Need at least 2 creds in pool to rotate")
    m = _main()
    cfg = m.load_config()
    rotated = 0
    for tag, acc in cfg.items():
        if not isinstance(acc, dict):
            continue
        # انتخاب pool[i % len(pool)] بر اساس hash tag
        import hashlib
        idx = int(hashlib.md5(tag.encode()).hexdigest(), 16) % len(pool)
        new = pool[idx]
        if acc.get("api_id") != new["api_id"]:
            acc["api_id"] = new["api_id"]
            acc["api_hash"] = new["api_hash"]
            rotated += 1
    m.save_config(cfg)
    return {"ok": True, "rotated_count": rotated, "pool_size": len(pool)}


# ─── User License-Auth API (for GitHub Pages site) ────────────────
# این endpoint‌ها با cookie جدا (cianet_user_session) کار می‌کنند
# تا با session ادمین تداخل نداشته باشند. کاربر با کد لایسنس لاگین
# می‌کند — فقط لایسنس‌های فعال‌شده (که user_id دارند) پذیرفته می‌شوند.

@app.post("/api/user/login")
async def user_license_login(req: LicenseLoginRequest, response: Response):
    """ورود با کد لایسنس — فقط لایسنس‌های فعال‌شده قابل‌استفاده.

    اگر لایسنس قبلاً فعال‌شده (در جدول subscriptions با status='active'
    یا 'expired')، user_id صاحب‌اش پیدا می‌شود و session ساخته می‌شود.
    اگر لایسنس هنوز فعال‌نشده (used_count=0) یا منقضی شده/is_active=0،
    ورود رد می‌شود.
    """
    m = _main()
    code = (req.license_code or "").strip().upper()
    if not code:
        raise HTTPException(400, "کد لایسنس خالی است")
    with m._conn() as c:
        lic = c.execute("SELECT * FROM licenses WHERE code = ?", (code,)).fetchone()
        if lic is None:
            raise HTTPException(404, "چنین لایسنسی وجود ندارد")
        lic = dict(lic)
        if not lic.get("is_active"):
            raise HTTPException(403, "این لایسنس غیرفعال است")
        if lic.get("used_count", 0) < 1:
            raise HTTPException(403, "این لایسنس هنوز فعال نشده — اول در ربات /start بزن و فعالش کن")
        # user_id از طریق subscriptions پیدا می‌شود (آخرین اشتراکِ ساخته‌شده با این license_id)
        sub = c.execute(
            "SELECT user_id FROM subscriptions WHERE license_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (lic["id"],),
        ).fetchone()
        if sub is None:
            raise HTTPException(403, "این لایسنس فعال شده ولی کاربرش پیدا نشد — با پشتیبانی تماس بگیر")
        user_id = int(sub["user_id"])
    token = _create_user_session(user_id)
    response.set_cookie(
        key="cianet_user_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=USER_SESSION_TTL_SEC,
        secure=False,  # در production روی True
    )
    return {"ok": True, "user_id": user_id}


@app.post("/api/user/logout")
async def user_logout(request: Request, response: Response):
    _invalidate_user_session(request)
    response.delete_cookie("cianet_user_session")
    return {"ok": True}


@app.get("/api/user/me")
async def user_me(request: Request):
    """اطلاعات کاربر فعلی — موجودی، اشتراک فعال، تعداد سلف‌بات‌ها."""
    uid = require_user_auth(request)
    m = _main()
    u = m.get_user(uid)
    if not u:
        raise HTTPException(404, "کاربر پیدا نشد")
    balance = m.get_wallet_balance(uid)
    sub_st = m.SaaSBot._user_sub_status_static(uid) if hasattr(m.SaaSBot, "_user_sub_status_static") else {"active": False, "days": 0, "plan": None}
    cfg = m.load_config()
    n_bots = len(m.accounts_of_user(cfg, uid))
    return {
        "user_id": uid,
        "username": u.get("username"),
        "first_name": u.get("first_name"),
        "role": m.get_role(uid, m.OWNER_ID),
        "wallet_balance": balance,
        "subscription": {
            "active": sub_st.get("active", False),
            "days_left": sub_st.get("days", 0),
            "plan": sub_st.get("plan"),
        },
        "n_selfbots": n_bots,
    }


@app.get("/api/user/wallet")
async def user_wallet(request: Request):
    """موجودی + ۱۰ تراکنش آخر کاربر."""
    uid = require_user_auth(request)
    m = _main()
    balance = m.get_wallet_balance(uid)
    txs = m.list_wallet_transactions(uid, limit=10)
    return {
        "balance": balance,
        "transactions": [
            {
                "id": t["id"],
                "amount": int(t["amount"]),
                "balance_after": int(t["balance_after"]),
                "type": t["type"],
                "reason": t.get("reason") or t.get("ref") or "",
                "created_at": t["created_at"],
            }
            for t in txs
        ],
    }


@app.get("/api/user/wallet/transactions")
async def user_wallet_transactions(request: Request, limit: int = 50):
    """تاریخچه‌ی کامل‌تر — تا ۱۰۰ تراکنش آخر."""
    uid = require_user_auth(request)
    if limit > 100:
        limit = 100
    m = _main()
    txs = m.list_wallet_transactions(uid, limit=limit)
    return {
        "transactions": [
            {
                "id": t["id"],
                "amount": int(t["amount"]),
                "balance_after": int(t["balance_after"]),
                "type": t["type"],
                "reason": t.get("reason") or t.get("ref") or "",
                "created_at": t["created_at"],
            }
            for t in txs
        ],
    }


@app.post("/api/user/pay-from-wallet")
async def user_pay_from_wallet(req: WalletPayRequest, request: Request):
    """پرداخت از کیف پول — برای تکمیل سفارش.

    این endpoint پول را از کیف پول کاربر کم می‌کند و در audit log ثبت
    می‌کند، ولی سفارش را خودش تأیید نمی‌کند (owner باید بعد از webhook
    سفارش را به‌صورت دستی تأیید کند). در نسخه‌ی بعدی می‌توان آن را به
    یک webhook داخلی وصل کرد که سفارش را همزمان تأیید کند.
    """
    uid = require_user_auth(request)
    m = _main()
    if req.amount <= 0:
        raise HTTPException(400, "مبلغ باید مثبت باشد")
    r = m.wallet_pay_from_balance(uid, req.amount, ref=req.ref or "")
    if r.get("ok"):
        return {"ok": True, "balance": r["balance"], "tx_id": r["tx_id"]}
    err_map = {
        "insufficient_balance": (400, f"موجودی کافی نیست — موجودی فعلی: {r.get('balance', 0)} Toman"),
        "user_not_found": (404, "کاربر پیدا نشد"),
        "invalid_amount": (400, "مبلغ نامعتبر"),
    }
    code, msg = err_map.get(r.get("error"), (500, "خطای ناشناخته"))
    raise HTTPException(code, msg)


# ─── Admin wallet endpoints (added to admin API) ─────────────────

@app.get("/api/users/{user_id}/wallet")
async def admin_get_user_wallet(user_id: int, request: Request, _: None = Depends(require_auth)):
    """موجودی + ۲۰ تراکنش آخر یک کاربر — فقط برای ادمین."""
    m = _main()
    u = m.get_user(user_id)
    if not u:
        raise HTTPException(404, "کاربر پیدا نشد")
    balance = m.get_wallet_balance(user_id)
    txs = m.list_wallet_transactions(user_id, limit=20)
    return {
        "user_id": user_id,
        "username": u.get("username"),
        "balance": balance,
        "transactions": [
            {
                "id": t["id"],
                "amount": int(t["amount"]),
                "balance_after": int(t["balance_after"]),
                "type": t["type"],
                "reason": t.get("reason") or t.get("ref") or "",
                "created_by": t.get("created_by"),
                "created_at": t["created_at"],
            }
            for t in txs
        ],
    }


@app.post("/api/users/{user_id}/wallet/credit")
async def admin_credit_user_wallet(user_id: int, req: WalletCreditRequest,
                                  request: Request, _: None = Depends(require_auth)):
    """شارژ کیف پول کاربر — فقط OWNER/ADMIN.

    توجه: این endpoint از session ادمین استفاده می‌کند، ولی نقش
    سازنده در main.py از DB خوانده می‌شود تا اعتماد به claim سمت
    کلاینت کافی نباشد. اگر session ادمین معتبر باشد ولی نقش او در
    DB تغییر کرده باشد (مثلاً از ADMIN به RESELLER)، این endpoint
    permission_denied برمی‌گرداند.
    """
    m = _main()
    # actor_id را از session می‌گیریم — ولی نقش را از DB می‌خوانیم.
    # session ادمین همیشه OWNER است در حال حاضر (single-admin panel).
    # در آینده‌ی multi-admin، باید actor_id واقعی از session استخراج شود.
    actor_id = m.OWNER_ID  # single-admin فرض می‌شود
    r = m.wallet_credit(user_id, req.amount, actor_id, reason=req.reason or "")
    if r.get("ok"):
        return {"ok": True, "balance": r["balance"], "tx_id": r["tx_id"]}
    err_map = {
        "permission_denied": (403, "شما مجاز به این عمل نیستید"),
        "user_not_found": (404, "کاربر پیدا نشد"),
        "invalid_amount": (400, "مبلغ نامعتبر"),
    }
    code, msg = err_map.get(r.get("error"), (500, "خطای ناشناخته"))
    raise HTTPException(code, msg)


@app.post("/api/users/{user_id}/wallet/debit")
async def admin_debit_user_wallet(user_id: int, req: WalletDebitRequest,
                                  request: Request, _: None = Depends(require_auth)):
    """کسر از کیف پول کاربر — فقط OWNER/ADMIN."""
    m = _main()
    actor_id = m.OWNER_ID
    r = m.wallet_debit(user_id, req.amount, actor_id, reason=req.reason or "")
    if r.get("ok"):
        return {"ok": True, "balance": r["balance"], "tx_id": r["tx_id"]}
    err_map = {
        "permission_denied": (403, "شما مجاز به این عمل نیستید"),
        "user_not_found": (404, "کاربر پیدا نشد"),
        "invalid_amount": (400, "مبلغ نامعتبر"),
        "insufficient_balance": (400, f"موجودی کاربر کافی نیست — موجودی فعلی: {r.get('balance', 0)} Toman"),
    }
    code, msg = err_map.get(r.get("error"), (500, "خطای ناشناخته"))
    raise HTTPException(code, msg)


# ─── Health check (public) ───────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "time": time.time()}


# ─── Static frontend (web_static/) ──────────────────────────────────
# PATCH (v2.1.5): یک frontend استاتیک ساده‌تر با vanilla JS که نیاز به
# npm build نداره. اگر `web_static/` وجود داشته باشد، mount می‌شه.
# قبلاً فقط Next.js روی port 3000 نیاز بود — حالا هر دو کار می‌کنن.
_WEB_STATIC_DIR = _PROJECT_DIR / "web_static"
if _WEB_STATIC_DIR.exists() and _WEB_STATIC_DIR.is_dir():
    # mount روی /app/* — صفحات HTML در web_static/
    app.mount("/app", StaticFiles(directory=str(_WEB_STATIC_DIR), html=True), name="web_static")

    # Root redirect → /app/login.html (اگه session نیست) یا /app/dashboard.html
    @app.get("/")
    async def root_redirect(request: Request):
        if _valid_session(request):
            return JSONResponse(
                status_code=307,
                headers={"Location": "/app/dashboard.html"},
                content={"redirect": "/app/dashboard.html"},
            )
        return JSONResponse(
            status_code=307,
            headers={"Location": "/app/login.html"},
            content={"redirect": "/app/login.html"},
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web_panel:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=False,
    )
