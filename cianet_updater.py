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
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
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
    """یک نمی‌تونه همزمان update کنه (همروندی جلوگیری)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            # چک کن اگه lock قدیمی شد (>5min)
            try:
                age = time.time() - LOCK_FILE.stat().st_mtime
                if age > 300:
                    LOCK_FILE.unlink()
            except Exception:
                pass
            time.sleep(0.5)
    return False


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


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
        # 1. graceful disable همه‌ی اکانت‌ها (اگه event loop فعال نیست)
        try:
            import main as _main_mod
            hook = getattr(_main_mod, "_disable_all_accounts_for_update", None)
            if hook is not None:
                try:
                    loop = asyncio.get_running_loop()
                    # event loop فعال است: schedule کن (و cancel بعد از pull)
                    loop.create_task(hook())
                    time.sleep(2)  # بذار disable تموم شه
                except RuntimeError:
                    # event loop نیست: اجرا کن
                    asyncio.run(hook())
        except ImportError:
            pass  # main.py لود نشده (مثلاً در تست)
        except Exception as e:
            log.warning("disable accounts hook failed (continuing): %s", e)

        # 2. backup
        backup_path = _backup_main_py(repo_dir)

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
        if restart:
            try:
                subprocess.Popen(
                    ["systemctl", "restart", "cianet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                msg += "\n🔄 سلف در حال restart..."
            except Exception as e:
                log.warning("systemctl restart failed: %s", e)

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
        ts = int(time.time())
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
    """
    if not propagation_marker_present():
        return "ℹ️  propagation لازم نیست"

    try:
        # 1. enable همه‌ی اکانت‌ها
        from main import _reenable_all_accounts_after_update
        report = await _reenable_all_accounts_after_update()

        # 2. notify admin
        if admin_bot:
            try:
                from main import ADMIN_ID, _send_admin_notification
                await _send_admin_notification(
                    f"🎉 آپدیت CiaNet اعمال شد!\n\n"
                    f"📊 گزارش:\n{report}\n\n"
                    f"🔗 commit: `{get_local_commit()[:8]}`\n"
                    f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}"
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
