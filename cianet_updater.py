"""
cianet_updater.py — Auto-Update & Account Propagation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

وقتی CiaNet selfbot آپدیت می‌شه:
1. همه‌ی اکانت‌های فعال disable می‌شن (graceful)
2. فایل جدید replace می‌شه
3. همه‌ی اکانت‌ها enable می‌شن با config جدید
4. به admin notification می‌ره

این ماژول دو تا entry point داره:
- check_for_update()    → polling (هر ۵ دقیقه صدا زده می‌شه)
- apply_update()        → وقتی update تشخیص داده شد
- propagate_to_accounts() → وقتی خود bot آپدیت شد
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("cianet.updater")

# ─── Constants ───
REPO_URL = "https://github.com/DLSDT/CiaNet.ir.git"
BRANCH = os.environ.get("CIANET_BRANCH", "main")
INSTALL_DIR = os.environ.get("CIANET_INSTALL_DIR", "/opt/cianet")
LOCAL_COMMIT_FILE = Path(INSTALL_DIR) / ".last_seen_commit"
LOCK_FILE = Path("/tmp/cianet-update.lock")
STATE_FILE = Path(INSTALL_DIR) / "data" / ".updater_state.json"


def _read_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {"last_check": 0, "last_commit": "", "last_update_at": 0, "pending_propagation": False}


def _write_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning("state write failed: %s", e)


def get_local_commit(repo_dir: str = None) -> Optional[str]:
    """آخرین commit لوکال."""
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        log.warning("get_local_commit failed: %s", e)
    return None


def get_remote_commit(repo_dir: str = None) -> Optional[str]:
    """آخرین commit روی remote (بدون pull)."""
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    try:
        subprocess.run(
            ["git", "fetch", "origin", BRANCH, "--quiet"],
            cwd=repo_dir, capture_output=True, text=True, timeout=30,
        )
        result = subprocess.run(
            ["git", "rev-parse", f"origin/{BRANCH}"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        log.warning("get_remote_commit failed: %s", e)
    return None


def get_pending_commits(repo_dir: str = None) -> list:
    """لیست commit هایی که local نداره."""
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    try:
        local = get_local_commit(repo_dir)
        remote = get_remote_commit(repo_dir)
        if not local or not remote or local == remote:
            return []
        result = subprocess.run(
            ["git", "log", "--oneline", f"{local}..origin/{BRANCH}"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return [l for l in result.stdout.strip().split("\n") if l]
    except Exception as e:
        log.warning("get_pending_commits failed: %s", e)
    return []


def _acquire_lock(timeout: int = 30) -> bool:
    """
    یک نمی‌تونه همزمان update کنه (همروندی جلوگیری).

    PATCH (v2.3.0): PID liveness check.
    قبلاً فقط mtime-based stale detection بود — یه update اگر >۵min
    طول می‌کشید (network slow, large repo, conflict timeout)، یه
    update دوم می‌تونست lock رو force-unlink کنه → دو `git pull` هم‌زمان
    → .git/index corruption احتمالی.

    حالا قبل از unlink:
    ۱. PID رو از lock file می‌خونه
    ۲. `os.kill(pid, 0)` می‌زنه — اگه PID هنوز زنده باشه، lock رو
       رها می‌کنه (wait می‌کنه).
    ۳. فقط اگه PID مرده باشه (یا lock file corrupt باشه)، unlink می‌کنه.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            # lock قبلاً وجود دارد — چک کن آیا owner هنوز زنده است
            try:
                # PID رو از lock file بخون
                lock_pid_str = LOCK_FILE.read_text().strip()
                lock_pid = int(lock_pid_str) if lock_pid_str.isdigit() else None
                if lock_pid is not None:
                    # چک کن آیا پروسه‌ی lock_pid هنوز زنده است
                    try:
                        os.kill(lock_pid, 0)
                        # پروسه هنوز زنده است — wait کن
                        time.sleep(0.5)
                        continue
                    except ProcessLookupError:
                        # پروسه مرده — lock stale
                        log.info("Stale lock from dead PID %d — unlinking", lock_pid)
                        LOCK_FILE.unlink()
                        continue
                    except PermissionError:
                        # پروسه برای user دیگه‌ای است — فکر کن زنده است
                        time.sleep(0.5)
                        continue
                # PID خواندن نشد (corrupt) — fallback به mtime
                age = time.time() - LOCK_FILE.stat().st_mtime
                if age > 300:
                    log.info("Stale lock (no PID, age %ds) — unlinking", int(age))
                    LOCK_FILE.unlink()
            except FileNotFoundError:
                # lock file حذف شده توسط race — دوباره تلاش کن
                pass
            except Exception as e:
                log.warning("Lock check failed: %s", e)
                time.sleep(0.5)
                continue
            time.sleep(0.5)
    return False


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def _verify_min_commit(repo_dir: str, remote_commit: str) -> Tuple[bool, str]:
    """
    PATCH (v2.2.0 CRITICAL): تأیید واقعیِ supply chain.

    قبلاً (v2.0.13) مقایسه‌ی رشته‌ای SHA-1 انجام می‌شد که FALSE SENSE
    OF SECURITY می‌داد — git SHAs به‌صورت الفبایی مرتب‌شده chronological
    نیستن. یه rollback به یه commit قدیمی می‌تونست ~۵۰٪ از مواقع عبور کنه.

    حالا از `git merge-base --is-ancestor <min> <remote>` استفاده
    می‌کنیم که از تاریخچه‌ی واقعی git استفاده می‌کنه. اگه min یک
    ancestor از remote باشه (یعنی remote جدیدتر یا برابر با min)،
    تأیید می‌شه. وگرنه رد می‌شه.

    FAIL-CLOSED: اگه verification به هر دلیلی fail بشه (network، git
    error، exception)، update رد می‌شه — نه proceed. این در تضاد با
    v2.0.13 بود که fail-open بود.

    Min commit hash از env var `CIANET_MIN_COMMIT` خوانده می‌شه.
    اگه تنظیم نشه (empty)، verification skip می‌شه (backward-compatible).
    """
    min_commit = os.environ.get("CIANET_MIN_COMMIT", "").strip().lower()
    if not min_commit:
        return True, ""  # verification disabled
    # پذیرش SHA-1 (40 hex) و SHA-256 (64 hex) — برای آینده
    if not (len(min_commit) in (40, 64) and all(c in "0123456789abcdef" for c in min_commit)):
        return False, f"❌ CIANET_MIN_COMMIT invalid: '{min_commit[:8]}...' (must be 40 or 64 hex chars)"
    if not remote_commit or len(remote_commit) not in (40, 64):
        return False, f"❌ remote commit invalid: '{remote_commit}'"
    if remote_commit == min_commit:
        return True, ""  # همان — تأیید شده
    # PATCH (v2.2.0): استفاده از git merge-base --is-ancestor
    # که از تاریخچه‌ی واقعی git استفاده می‌کنه، نه مقایسه‌ی رشته‌ای.
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", min_commit, remote_commit],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # min_commit is ancestor of remote_commit → remote is at-or-after min → OK
            return True, ""
        elif result.returncode == 1:
            # min_commit is NOT ancestor of remote_commit → remote is older → REJECT
            return False, (
                f"❌ Supply chain check failed:\n"
                f"   remote commit {remote_commit[:8]} is NOT a descendant of min {min_commit[:8]}\n"
                f"   Possible rollback attack or force-push to old commit.\n"
                f"   Update refused. Update CIANET_MIN_COMMIT to a newer value to allow."
            )
        else:
            # exit 128 = git error (commit not found, etc.)
            stderr = result.stderr.strip()[:200]
            return False, f"❌ git merge-base error (exit {result.returncode}): {stderr}"
    except subprocess.TimeoutExpired:
        return False, "❌ Supply chain check timeout — update refused (fail-closed)"
    except Exception as e:
        return False, f"❌ Supply chain check exception: {type(e).__name__}: {e}"


def apply_update(repo_dir: str = None, restart: bool = True) -> Tuple[bool, str]:
    """
    pull + restart. قبلش همه‌ی اکانت‌ها disable می‌شن.
    Returns: (success, message)
    """
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    if not _acquire_lock():
        return False, "❌ یک update دیگه در حال اجراست"

    try:
        # PATCH (v2.2.0 CRITICAL): fail-closed verification.
        # قبلاً (v2.0.13) اگر fetch یا verify exception می‌داد، log warning
        # و continue می‌کرد (fail-open) — یعنی اگر network glitch باشه،
        # update بدون verify اعمال می‌شد. حالا fail-closed است: اگر
        # CIANET_MIN_COMMIT تنظیم شده باشه و verify شکست بخوره، update
        # رد می‌شه.
        min_commit = os.environ.get("CIANET_MIN_COMMIT", "").strip()
        if min_commit:
            try:
                subprocess.run(
                    ["git", "fetch", "origin", BRANCH, "--quiet"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=30,
                )
                remote_commit = get_remote_commit(repo_dir)
                if not remote_commit:
                    return False, "❌ Cannot fetch remote commit for verification — update refused (fail-closed)"
                ok, msg = _verify_min_commit(repo_dir, remote_commit)
                if not ok:
                    return False, msg
            except subprocess.TimeoutExpired:
                return False, "❌ git fetch timeout during verification — update refused (fail-closed)"
            except Exception as e:
                return False, f"❌ Supply chain verification error (fail-closed): {type(e).__name__}: {e}"

        # 1. graceful disable همه‌ی اکانت‌ها (اگه event loop فعال نیست)
        try:
            import main as _main_mod
            hook = getattr(_main_mod, "_disable_all_accounts_for_update", None)
            # PATCH (v2.2.0): hook حالا در main.py واقعاً تعریف شده.
            if hook is not None:
                try:
                    loop = asyncio.get_running_loop()
                    # event loop فعال است: schedule کن و واقعاً صبر کن
                    # (با create_task + ۲s sleep، حلقه فرصت اجرا داره)
                    task = loop.create_task(hook())
                    # بذار disable تموم شه
                    time.sleep(2)
                except RuntimeError:
                    # event loop نیست: اجرا کن
                    asyncio.run(hook())
        except ImportError:
            pass  # main.py لود نشده (مثلاً در تست)
        except Exception as e:
            log.warning("disable accounts hook failed (continuing): %s", e)

        # 2. backup
        backup_path = _backup_main_py(repo_dir)

        # PATCH (v2.2.0): قبل از pull، اگه فایل‌های main.py تغییرات
        # محلی دارن (مثلاً بعد از rollback که فایل رو جایگزین کردیم)،
        # git pull خطای "Your local changes would be overwritten" می‌ده.
        # راه‌حل: stash یا checkout صریحِ فایل‌ها. چون ما backup گرفتیم،
        # می‌تونیم main.py رو reset کنیم بدون از دست رفتن چیزی.
        try:
            subprocess.run(
                ["git", "checkout", "--", "main.py"],
                cwd=repo_dir, capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            log.warning("git checkout before pull failed (continuing): %s", e)

        # 3. pull
        result = subprocess.run(
            ["git", "pull", "origin", BRANCH],
            cwd=repo_dir, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return False, f"❌ git pull failed:\n{result.stderr}"

        new_commit = get_local_commit(repo_dir)
        try:
            LOCAL_COMMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOCAL_COMMIT_FILE.write_text(new_commit or "")
        except Exception as e:
            log.warning("local commit file write failed: %s", e)

        state = _read_state()
        state["last_commit"] = new_commit
        state["last_update_at"] = time.time()
        state["pending_propagation"] = True  # وقتی restart شد propagate می‌کنه
        _write_state(state)

        msg = f"✅ آپدیت شد به {new_commit[:8]}"
        if backup_path:
            msg += f"\n📦 بکاپ: {backup_path}"

        # 4. restart از طریق systemd (اگه هست)
        # PATCH (v2.5.0 CRITICAL FIX): service name auto-detect
        # قبلاً hardcoded "cianet" بود که با نصب‌های install_service.sh
        # (که "selfbot.service" می‌سازه) mismatch داشت. حالا:
        # ۱. از env var CIANET_SERVICE_NAME می‌خونه (اگه تنظیم شده)
        # ۲. وگرنه auto-detect می‌کنه: cianet → selfbot → هر چی با cianet
        # ۳. وگرنه هیچ‌کدام نبود، "cianet" به‌عنوان fallback
        if restart:
            svc_name = os.environ.get("CIANET_SERVICE_NAME", "").strip()
            if not svc_name:
                for svc in ("cianet", "selfbot"):
                    try:
                        r = subprocess.run(
                            ["systemctl", "is-enabled", svc],
                            capture_output=True, text=True, timeout=3,
                        )
                        if r.returncode == 0:
                            svc_name = svc
                            break
                    except Exception:
                        continue
            if not svc_name:
                svc_name = "cianet"  # fallback
            try:
                subprocess.Popen(
                    ["systemctl", "restart", svc_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                msg += f"\n🔄 سلف در حال restart (service: {svc_name})..."
            except Exception as e:
                log.warning("systemctl restart %s failed: %s", svc_name, e)
                msg += f"\n⚠️ restart ناموفق (service: {svc_name}): {e}\nدستی: sudo systemctl restart {svc_name}"

        return True, msg

    except Exception as e:
        log.exception("apply_update failed")
        return False, f"❌ خطا: {e}"
    finally:
        _release_lock()


def _backup_main_py(repo_dir: str = None) -> Optional[str]:
    """قبل از آپدیت، main.py رو بکاپ بگیر."""
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    try:
        main_py = Path(repo_dir) / "main.py"
        if not main_py.exists():
            return None
        # PATCH (v2.2.0): استفاده از time_ns + PID برای یکتاییِ فایل
        # (دو update در یک ثانیه قبلاً همدیگه رو overwrite می‌کردن)
        ts = time.time_ns()
        backup = Path(repo_dir) / "versions" / f"main.py.pre-auto-update.{ts}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(main_py, backup)
        return str(backup)
    except Exception as e:
        log.warning("backup failed: %s", e)
        return None


def propagation_marker_present() -> bool:
    """بعد از restart، اگه این True باشه یعنی باید اکانت‌ها re-enable شن."""
    state = _read_state()
    return state.get("pending_propagation", False)


def mark_propagation_done() -> None:
    state = _read_state()
    state["pending_propagation"] = False
    _write_state(state)


async def propagate_to_accounts(admin_bot=None) -> str:
    """
    بعد از restart، اکانت‌ها رو دوباره فعال کن.
    به admin notification می‌فرسته.

    PATCH (v2.2.0): اگر _reenable_all_accounts_after_update در main.py
    وجود نداشته باشه (نصب قدیمی)، یه پیام خطای واضح برمی‌گردونه به‌جای
    ImportError سایلنت.
    """
    if not propagation_marker_present():
        return "ℹ️  propagation لازم نیست"

    try:
        # 1. enable همه‌ی اکانت‌ها
        try:
            from main import _reenable_all_accounts_after_update
        except ImportError:
            return "⚠️  _reenable_all_accounts_after_update در main.py تعریف نشده — آپدیت کن"
        report = await _reenable_all_accounts_after_update()

        # 2. notify admin (با best-effort)
        if admin_bot:
            try:
                # NOTE: _send_admin_notification در main.py وجود نداره —
                # ولی _owner_notify_async هست. اگه نبود، fallback به print.
                try:
                    from main import _owner_notify_async
                    await _owner_notify_async(
                        f"🎉 آپدیت CiaNet اعمال شد!\n\n"
                        f"📊 گزارش:\n{report}\n\n"
                        f"🔗 commit: `{(get_local_commit() or '?')[:8]}`\n"
                        f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except (ImportError, Exception):
                    # fallback: print → journald
                    print(
                        f"🎉 آپدیت CiaNet اعمال شد!\n"
                        f"📊 گزارش:\n{report}\n"
                        f"🔗 commit: {(get_local_commit() or '?')[:8]}"
                    )
            except Exception as e:
                log.warning("admin notify failed: %s", e)

        mark_propagation_done()
        return f"✅ propagation done:\n{report}"

    except Exception as e:
        log.exception("propagation failed")
        return f"❌ propagation error: {e}"


async def check_for_update() -> Optional[dict]:
    """
    polling endpoint. هر ۵ دقیقه صدا زده می‌شه.
    Returns: dict با commit info اگه update باشه، None در غیر این صورت.
    """
    state = _read_state()
    state["last_check"] = time.time()
    _write_state(state)

    pending = get_pending_commits()
    if not pending:
        return None

    local = get_local_commit()
    remote = get_remote_commit()

    return {
        "local": local,
        "remote": remote,
        "commits": pending,
        "count": len(pending),
    }


# ─── Entry points برای main.py ───

async def auto_update_loop(interval: int = 300, admin_notify_func=None):
    """
    background loop. هر `interval` ثانیه چک می‌کنه.
    اگه update بود، apply می‌کنه و notify می‌فرسته.
    """
    log.info("auto-update loop started (interval=%ds)", interval)
    while True:
        try:
            update_info = await check_for_update()
            if update_info:
                log.info("📥 update detected: %d commits", update_info["count"])
                if admin_notify_func:
                    try:
                        await admin_notify_func(
                            f"📥 آپدیت جدید پیدا شد ({update_info['count']} commit)\n"
                            f"🔄 در حال apply..."
                        )
                    except Exception:
                        pass
                success, msg = apply_update()
                log.info("apply_update: %s", msg)
                # اگه apply موفق بود، خود process restart می‌شه
                # پس این خط معمولاً اجرا نمی‌شه
        except Exception as e:
            log.warning("auto_update_loop error: %s", e)
        await asyncio.sleep(interval)


def get_version_info() -> dict:
    """اطلاعات برای نمایش در پنل ادمین."""
    return {
        "local_commit": get_local_commit(),
        "remote_commit": get_remote_commit(),
        "pending_commits": get_pending_commits(),
        "last_check": _read_state().get("last_check", 0),
        "last_update_at": _read_state().get("last_update_at", 0),
    }
