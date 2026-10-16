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
import functools
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

# v2.9.5: تنظیم HOME برای git (safe.directory نیاز داره)
# اگه HOME ست نشده باشه (مثلاً در systemd)، git نمی‌تونه
# config رو بخونه و safe.directory fail می‌شه.
if not os.environ.get("HOME"):
    os.environ["HOME"] = INSTALL_DIR

# v2.8.13: Set safe.directory at module load time (not inside apply_update).
# این جلوی خطای "dubious ownership" رو می‌گیره وقتی سرویس با user=cianet
# اجرا می‌شه ولی repo با root clone شده. قبلاً فقط داخل apply_update این
# کار انجام می‌شد، ولی check_for_update قبل از apply_update اجرا می‌شد و
# شکست می‌خورد.
try:
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", INSTALL_DIR],
        capture_output=True, text=True, timeout=5,
    )
except Exception as _e:
    log.warning("initial safe.directory setup failed: %s", _e)
LOCAL_COMMIT_FILE = Path(INSTALL_DIR) / ".last_seen_commit"
LOCK_FILE = Path("/tmp/cianet-update.lock")
STATE_FILE = Path(INSTALL_DIR) / "data" / ".updater_state.json"


def _read_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {"last_check": 0, "last_commit": "", "last_update_at": 0, "pending_propagation": False, "rolled_back": False, "rolled_back_at": 0}


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
        # v2.8.13: لاگ کردن stderr به‌جای بلعیدن سایلنت
        log.warning("get_local_commit git failed (rc=%d): %s",
                    result.returncode, result.stderr.strip()[:200])
    except Exception as e:
        log.warning("get_local_commit failed: %s", e)
    return None


def get_remote_commit(repo_dir: str = None) -> Optional[str]:
    """آخرین commit روی remote (بدون pull)."""
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    try:
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", BRANCH, "--quiet"],
            cwd=repo_dir, capture_output=True, text=True, timeout=30,
        )
        # v2.8.13: لاگ stderr اگه fetch شکست خورد
        if fetch_result.returncode != 0:
            log.warning("get_remote_commit fetch failed (rc=%d): %s",
                        fetch_result.returncode, fetch_result.stderr.strip()[:200])
        result = subprocess.run(
            ["git", "rev-parse", f"origin/{BRANCH}"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        log.warning("get_remote_commit rev-parse failed (rc=%d): %s",
                    result.returncode, result.stderr.strip()[:200])
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


def has_local_modifications(repo_dir: str = None) -> bool:
    """v2.8.1: چک کن آیا main.py یا web_panel.py نسبت به git HEAD
    تغییر کرده — مثلاً بعد از rollback یا replace دستی.

    این تابع `git diff HEAD -- main.py web_panel.py` را اجرا می‌کند.
    اگه خروجی غیر خالی باشد، یعنی فایل‌های نصب‌شده با git HEAD یکسان
    نیستند — کاربر یا rollback کرده یا فایل‌ها را دستی replace کرده.
    """
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", "main.py", "web_panel.py"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except Exception as e:
        log.warning("has_local_modifications failed: %s", e)
    return False


def mark_rolled_back() -> None:
    """v2.8.1: بعد از rollback، این تابع رو صدا بزن تا state flag
    ست بشه و آپدیتر بدونه که بعد از restart باید update check
    رو فوراً انجام بده."""
    state = _read_state()
    state["rolled_back"] = True
    state["rolled_back_at"] = time.time()
    _write_state(state)
    # پاک کردن .last_seen_commit تا check_for_update بدونه باید
    # فوراً re-detect کنه
    try:
        if LOCAL_COMMIT_FILE.exists():
            LOCAL_COMMIT_FILE.unlink()
    except Exception:
        pass


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
            # v2.13.4 (UP-MED-4): create lock with 0o600 instead of 0o644 to
            # prevent local users from rewriting the PID and staging a
            # permanent DoS of the auto-update path.
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            # Defense-in-depth: enforce 0o600 even if the file pre-existed
            # with looser bits and was unlinked/recreated (best-effort).
            try:
                os.chmod(str(LOCK_FILE), 0o600)
            except OSError:
                pass
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


def apply_update(repo_dir: str = None, restart: bool = True, main_loop: object = None) -> Tuple[bool, str]:
    """
    pull + restart. قبلش همه‌ی اکانت‌ها disable می‌شن.
    Returns: (success, message)

    v2.13.4 patches:
      - UP-HIGH-2: pin `git reset --hard` to the supply-chain-verified SHA
        instead of `origin/{BRANCH}` to eliminate the verify/reset TOCTOU
        window. Also collapses the redundant fetches in this function to
        a single fetch (the one inside get_remote_commit).
      - UP-MED-3: accept an optional `main_loop` so callers running this
        sync function in a thread executor can hand the main asyncio loop
        in. When provided, the disable-accounts hook is scheduled on the
        main loop via `run_coroutine_threadsafe` (the hook's Telethon
        coroutines are bound to that loop). Without `main_loop`, fall back
        to the previous best-effort behaviour but log the failure loudly.
      - v2.14.2 (BUG-18a/BUG-18b): after the reset and before the restart —
        best-effort `pip install -r requirements.txt` with the running
        interpreter (service venv) so new dependencies exist before the
        restart (a missing dep previously meant an ImportError crash-loop
        after restart); the ast.parse sanity check is extended from
        main.py only to [main.py, web_panel.py] — a syntax-broken
        web_panel.py previously passed the check and crashed the panel.
        Both are best-effort and never block the update on failure.
    """
    if repo_dir is None:
        repo_dir = INSTALL_DIR
    if not _acquire_lock():
        return False, "❌ یک update دیگه در حال اجراست"

    # v2.13.4 (UP-HIGH-2): SHA verified by the supply-chain check.
    # `git reset --hard` will be pinned to this SHA (not origin/BRANCH)
    # to eliminate the TOCTOU window between verify and reset.
    verified_commit_sha: Optional[str] = None

    try:
        # PATCH (v2.2.0 CRITICAL): fail-closed verification.
        # قبلاً (v2.0.13) اگر fetch یا verify exception می‌داد، log warning
        # و continue می‌کرد (fail-open) — یعنی اگر network glitch باشه،
        # update بدون verify اعمال می‌شد. حالا fail-closed است: اگر
        # CIANET_MIN_COMMIT تنظیم شده باشه و verify شکست بخوره، update
        # رد می‌شه.
        #
        # v2.13.4 (UP-HIGH-2): the redundant `git fetch` before
        # `get_remote_commit` has been removed — `get_remote_commit`
        # already runs a fetch internally, so the previous double-fetch
        # just widened the TOCTOU window for no benefit.
        min_commit = os.environ.get("CIANET_MIN_COMMIT", "").strip()
        if min_commit:
            try:
                remote_commit = get_remote_commit(repo_dir)
                if not remote_commit:
                    return False, "❌ Cannot fetch remote commit for verification — update refused (fail-closed)"
                ok, msg = _verify_min_commit(repo_dir, remote_commit)
                if not ok:
                    return False, msg
                # Pin the destructive reset to the verified SHA. This is
                # the SHA actually passed to `git merge-base --is-ancestor`
                # inside `_verify_min_commit`, so resetting to it is
                # exactly what was approved.
                verified_commit_sha = remote_commit
            except subprocess.TimeoutExpired:
                return False, "❌ git fetch timeout during verification — update refused (fail-closed)"
            except Exception as e:
                return False, f"❌ Supply chain verification error (fail-closed): {type(e).__name__}: {e}"

        # 1. graceful disable همه‌ی اکانت‌ها (اگه event loop فعال نیست)
        # v2.13.4 (UP-MED-3): this function is typically invoked via
        # `loop.run_in_executor(None, apply_update)` from main.py, which
        # runs in a worker thread with no running asyncio loop. The
        # disable hook (_disable_all_accounts_for_update) calls Telethon
        # coroutines that are bound to the MAIN loop. The previous code
        # used `asyncio.run(hook())` from the worker thread, which built
        # a new loop and failed with "Future attached to a different
        # loop" — silently swallowed by the broad `except Exception`.
        # When the caller passes `main_loop`, schedule the hook on it
        # via `run_coroutine_threadsafe` so the Telethon coroutines run
        # on their home loop. When `main_loop` is not provided, keep the
        # legacy best-effort path but log failures explicitly.
        disable_hook_ok = False
        try:
            import main as _main_mod
            hook = getattr(_main_mod, "_disable_all_accounts_for_update", None)
            # PATCH (v2.2.0): hook حالا در main.py واقعاً تعریف شده.
            if hook is not None:
                if main_loop is not None:
                    try:
                        fut = asyncio.run_coroutine_threadsafe(hook(), main_loop)
                        fut.result(timeout=20)
                        disable_hook_ok = True
                    except Exception as e:
                        log.error(
                            "disable accounts hook failed on main_loop "
                            "(continuing — accounts may be killed by SIGTERM "
                            "during restart): %s: %s", type(e).__name__, e
                        )
                else:
                    try:
                        loop = asyncio.get_running_loop()
                        # event loop فعال است: schedule کن و واقعاً صبر کن
                        # (با create_task + ۲s sleep، حلقه فرصت اجرا داره)
                        task = loop.create_task(hook())
                        # بذار disable تموم شه
                        time.sleep(2)
                        disable_hook_ok = True
                    except RuntimeError:
                        # event loop نیست: fallback به asyncio.run (legacy)
                        try:
                            asyncio.run(hook())
                            disable_hook_ok = True
                        except Exception as e:
                            log.error(
                                "disable accounts hook failed in asyncio.run "
                                "(continuing — accounts may be killed by SIGTERM "
                                "during restart): %s: %s", type(e).__name__, e
                            )
        except ImportError:
            pass  # main.py لود نشده (مثلاً در تست)
        except Exception as e:
            log.warning("disable accounts hook setup failed (continuing): %s", e)

        # 2. backup
        backup_path = _backup_main_py(repo_dir)

        # PATCH (v2.6.4 CRITICAL): قبل از هر چیز، safe.directory رو تنظیم کن
        # تا git روی سرورهایی که repo با user دیگه‌ای clone شده خطای
        # "dubious ownership" نده و pull سایلنت fail نشه.
        try:
            subprocess.run(
                ["git", "config", "--global", "--add", "safe.directory", repo_dir],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass

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

        # v2.14.2 (BUG-18b): commitِ فعلی رو قبل از reset یادداشت کن —
        # اگر بعد از reset یکی از فایل‌های جدید SyntaxError داشت،
        # web_panel.py رو از همین commit (نسخه‌ی قبل از آپدیت) برمی‌گردونیم.
        pre_reset_commit = get_local_commit(repo_dir)

        # 3. fetch + reset --hard (به‌جای pull) — این همیشه کار می‌کنه
        # حتی اگه local changes یا dubious ownership باشه.
        # PATCH (v2.6.4): git pull می‌تونه به‌خاطر local changes fail کنه.
        # git fetch + reset --hard همیشه کار می‌کنه و مطمئن‌تره.
        #
        # v2.13.4 (UP-HIGH-2): pin the destructive reset to the SHA that
        # was actually verified by `_verify_min_commit`. The previous
        # code re-fetched `origin/{BRANCH}` between verify and reset,
        # which let a force-push to the upstream branch land a malicious
        # commit during the verify/reset window. When we have a verified
        # SHA, the SHA is already present in the local object database
        # (it was just fetched by get_remote_commit), so no additional
        # fetch is needed. When verification was skipped (CIANET_MIN_COMMIT
        # unset), fall back to the legacy origin/{BRANCH} path but do
        # exactly one fetch.
        if verified_commit_sha:
            reset_result = subprocess.run(
                ["git", "reset", "--hard", verified_commit_sha],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            if reset_result.returncode != 0:
                return False, f"❌ git reset --hard failed:\n{reset_result.stderr}"
            # Defense-in-depth: confirm HEAD actually points at the
            # verified SHA. A misconfigured git config or hook could
            # otherwise leave us on a different commit.
            actual_head = get_local_commit(repo_dir)
            if actual_head and actual_head != verified_commit_sha:
                log.error(
                    "post-reset HEAD %s != verified SHA %s — refusing to proceed",
                    actual_head[:8], verified_commit_sha[:8]
                )
                return False, (
                    f"❌ Supply chain TOCTOU check failed: HEAD after reset "
                    f"({actual_head[:8]}) != verified SHA ({verified_commit_sha[:8]}). "
                    f"Update refused — possible repository tampering."
                )
        else:
            fetch_result = subprocess.run(
                ["git", "fetch", "origin", BRANCH, "--quiet"],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            if fetch_result.returncode != 0:
                return False, f"❌ git fetch failed:\n{fetch_result.stderr}"

            reset_result = subprocess.run(
                ["git", "reset", "--hard", f"origin/{BRANCH}"],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            if reset_result.returncode != 0:
                return False, f"❌ git reset --hard failed:\n{reset_result.stderr}"

        # v2.12.9 CRITICAL (QA-DEBUG C1): پس از reset --hard، فایلِ main.py
        # جدید رو با ast.parse اعتبارسنجی کن. اگه SyntaxError داشت، یعنی
        # commitِ خراب از GitHub اومده — auto-rollback کن به backup که قبل
        # از reset گرفتیم. بدون این چک، systemd بعد از restart ده‌بار در
        # ۵ دقیقه کِرش می‌خورد و rate-limit می‌شد و کل سرویس down می‌شد.
        #
        # v2.14.2 (BUG-18b): چک syntax به هر دو فایل کلیدی گسترش یافت —
        # main.py و web_panel.py. قبلاً فقط main.py چک می‌شد؛ یک
        # web_panel.py با SyntaxError از این چک رد می‌شد و بعد از restart
        # پنل وب روی کد خراب بالا می‌آمد. (cianet_updater.py خودش در حال
        # replace شدن است — چک کردنش ممکن نیست و لازم هم نیست.)
        new_main_path = os.path.join(repo_dir, "main.py")
        try:
            import ast as _ast
            for _sanity_name in ("main.py", "web_panel.py"):
                _sanity_path = os.path.join(repo_dir, _sanity_name)
                if not os.path.isfile(_sanity_path):
                    continue  # فایل در این نصب موجود نیست (نصب قدیمی) — skip
                with open(_sanity_path, "r", encoding="utf-8") as _f:
                    _src = _f.read()
                _ast.parse(_src, filename=_sanity_path)
        except SyntaxError as _se:
            _bad_file = os.path.basename(getattr(_se, "filename", None) or "main.py")
            log.error("❌ new %s has SyntaxError: %s — rolling back", _bad_file, _se)
            # v2.14.2 (BUG-18b): web_panel.py هم (best-effort از git) به
            # نسخه‌ی قبل از reset برگردونده می‌شه تا پنل روی کد خراب بالا
            # نیاید. backup فقط از main.py گرفته می‌شه (§14.1 گام ۳ / §14.5)،
            # پس برای web_panel.py از commitِ قبل از reset استفاده می‌کنیم.
            if pre_reset_commit:
                try:
                    _wp_rb = subprocess.run(
                        ["git", "checkout", pre_reset_commit, "--", "web_panel.py"],
                        cwd=repo_dir, capture_output=True, text=True, timeout=15,
                    )
                    if _wp_rb.returncode != 0:
                        log.warning(
                            "⚠️ بازگردانی web_panel.py به نسخه‌ی قبل از آپدیت ناموفق بود (ادامه می‌دهیم): %s",
                            _wp_rb.stderr.strip()[:200]
                        )
                except Exception as _wp_e:
                    log.warning(
                        "⚠️ بازگردانی web_panel.py به نسخه‌ی قبل از آپدیت ناموفق بود (ادامه می‌دهیم): %s",
                        _wp_e
                    )
            # rollback: backup رو برگردون
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, new_main_path)
                    log.info("✅ rolled back to %s", backup_path)
                    state = _read_state()
                    state["rolled_back"] = True
                    state["rolled_back_at"] = time.time()
                    state["rollback_reason"] = f"syntax_error: {_se.msg}"
                    _write_state(state)
                    return False, (
                        f"❌ آپدیت ناموفق: {_bad_file} جدید SyntaxError داشت "
                        f"(خط {_se.lineno}: {_se.msg}). به backup برگشتیم:\n"
                        f"{backup_path}\n\nربات روی نسخه‌ی قبلی ادامه می‌دهد."
                    )
                except Exception as _re:
                    log.exception("rollback failed: %s", _re)
                    return False, (
                        f"❌ آپدیت ناموفق و rollback هم ناموفق: {_re}\n"
                        f"⚠️ ربات ممکن است down باشد — دستی restore کنید: "
                        f"cp {backup_path} {new_main_path}"
                    )
            else:
                return False, (
                    f"❌ آپدیت ناموفق: {_bad_file} جدید SyntaxError داشت و "
                    f"backup پیدا نشد. ربات ممکن است down باشد."
                )

        # حذف __pycache__ تا کد قدیمی cached اجرا نشه
        import shutil as _shutil
        pycache = os.path.join(repo_dir, "__pycache__")
        if os.path.isdir(pycache):
            try:
                _shutil.rmtree(pycache)
            except Exception:
                pass

        # v2.14.2 (BUG-18a): بعد از reset و قبل از restart،
        # dependencyهای جدیدِ requirements.txt رو نصب کن (best-effort).
        # بدون این، اگر یک آپدیت dependency جدید لازم داشته باشه، سرویس
        # بعد از restart روی ImportError چرخه‌ی crash می‌افتاد. از
        # sys.executable استفاده می‌کنیم تا دقیقاً همان python داخل venv
        # سرویس (مثل install.sh → .venv/bin/python) استفاده بشه. شکستِ pip
        # آپدیت/restart رو بلاک نمی‌کنه — فقط لاگ می‌شه.
        try:
            import sys as _sys
            _req_path = os.path.join(repo_dir, "requirements.txt")
            if os.path.isfile(_req_path):
                _pip = subprocess.run(
                    [_sys.executable, "-m", "pip", "install", "-r", _req_path],
                    capture_output=True, text=True, timeout=300,
                )
                if _pip.returncode == 0:
                    log.info("✅ نصب requirements.txt بعد از آپدیت انجام شد")
                else:
                    log.warning(
                        "⚠️ نصب requirements.txt بعد از آپدیت ناموفق بود "
                        "(ادامه می‌دهیم — اگر dependency جدیدی لازم باشد سرویس "
                        "بعد از restart ممکن است بالا نیاید؛ دستی اجرا کنید: "
                        "%s -m pip install -r requirements.txt): %s",
                        _sys.executable, _pip.stderr.strip()[-300:]
                    )
        except Exception as _pip_e:
            log.warning(
                "⚠️ نصب requirements.txt بعد از آپدیت ناموفق بود (ادامه می‌دهیم): %s",
                _pip_e
            )

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
        state["rolled_back"] = False  # v2.8.1: بعد از آپدیت موفق، flag rollback پاک می‌شه
        state["rolled_back_at"] = 0
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
            # v2.9.6: اگه non-root اجرا می‌شه، اول sudo systemctl رو امتحان کن
            # (با sudoers rule که در install.sh نصب می‌شه). اگه اون نشد،
            # plain systemctl، اگه اون هم نشد، SIGTERM fallback.
            import os as _os_uid
            _is_root = hasattr(_os_uid, "geteuid") and _os_uid.geteuid() == 0
            _restart_done = False
            try:
                # Stage 1: sudo systemctl (اگه sudoers نصب باشه)
                if not _is_root:
                    rc = subprocess.run(
                        ["sudo", "-n", "systemctl", "restart", svc_name],
                        capture_output=True, text=True, timeout=10,
                    )
                    if rc.returncode == 0:
                        msg += f"\n🔄 سرویس در حال restart ({svc_name})..."
                        _restart_done = True
                # Stage 2: plain systemctl (اگه polkit rule نصب باشه)
                if not _restart_done:
                    rc = subprocess.run(
                        ["systemctl", "restart", svc_name],
                        capture_output=True, text=True, timeout=10,
                    )
                    if rc.returncode == 0:
                        msg += f"\n🔄 سرویس در حال restart ({svc_name})..."
                        _restart_done = True
                # Stage 3: SIGTERM fallback (systemd با Restart=always دوباره می‌سازه)
                if not _restart_done:
                    log.warning("systemctl restart failed — fallback to SIGTERM")
                    msg += f"\n⚠️ systemctl restart ناموفق — استفاده از SIGTERM..."
                    import signal as _signal
                    os.kill(os.getpid(), _signal.SIGTERM)
                    _restart_done = True
            except Exception as e:
                log.warning("restart failed: %s — fallback to SIGTERM", e)
                msg += f"\n⚠️ restart ناموفق ({e}) — استفاده از SIGTERM..."
                try:
                    import signal as _signal
                    os.kill(os.getpid(), _signal.SIGTERM)
                    _restart_done = True
                except Exception:
                    msg += f"\n❌ SIGTERM هم ناموفق — دستی بزن: sudo systemctl restart {svc_name}"

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
        # v2.13.0 (DEBUG-2 BACKUP-CHMOD): explicit chmod 0600 — قبلاً با
        # default umask (0644) روی دیسک ذخیره می‌شد و world-readable بود.
        # این backup‌ها source code هستند (نه credentials) ولی logic قدیمی
        # رو برای مهاجمی که سیستم رو مطالعه می‌کنه، expose می‌کنند. 0600
        # فقط owner رو read/write می‌کنه.
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass  # best-effort — اگه FS از chmod پشتیبانی نکنه (مثلاً FAT)
        # v2.12.23 (QA10-STABILITY BUG#5): پاکسازی backup‌های قدیمی.
        # فقط ۱۰ تا backup اخیر رو نگه دار. بقیه حذف بشن تا disk پر نشه.
        try:
            _cleanup_old_backups(backup.parent)
        except Exception as _ce:
            log.warning("backup cleanup failed (continuing): %s", _ce)
        return str(backup)
    except Exception as e:
        log.warning("backup failed: %s", e)
        return None


def _cleanup_old_backups(versions_dir: Path, keep: int = 10) -> None:
    """v2.12.23: پاکسازی backup‌های قدیمی — فقط `keep` تا اخیر رو نگه دار.

    فایل‌های با الگوی `main.py.pre-auto-update.*` و `main.py.pre-rollback.*`
    رو بر اساس modification time مرتب می‌کنه و قدیمی‌ترها رو حذف می‌کنه.
    این از پر شدنِ disk بعد از ماه‌ها auto-update جلوگیری می‌کنه.
    """
    if not versions_dir.exists():
        return
    backups = sorted(
        versions_dir.glob("main.py.pre-auto-update.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,  # جدیدترین اول
    )
    # هم rollback backups رو در نظر بگیر
    backups += sorted(
        versions_dir.glob("main.py.pre-rollback.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # نگه‌داشتنِ `keep` تا اخیر (به‌ترتیبِ زمان)
    # backups لیست مسطح هست، نه مرتب به‌صورت واحد. بذار با همون mtime
    # مرتب کن:
    all_backups = sorted(
        list(versions_dir.glob("main.py.pre-auto-update.*"))
        + list(versions_dir.glob("main.py.pre-rollback.*")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in all_backups[keep:]:
        try:
            old.unlink()
            log.info("cleaned up old backup: %s", old.name)
        except Exception:
            pass


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

async def auto_update_loop(interval: int = 300, admin_notify_func=None, main_loop: object = None):
    """
    background loop. هر `interval` ثانیه چک می‌کنه.
    اگه update بود، apply می‌کنه و notify می‌فرسته.

    v2.14.2 (BUG-18c / §14.1 گام ۷): پارامتر `main_loop` اضافه شد و به
    apply_update پاس می‌شه تا disable-accounts hook واقعاً از طریق
    asyncio.run_coroutine_threadsafe روی event loop اصلی اجرا بشه — قبلاً
    apply_update() بدون main_loop صدا زده می‌شد و wiring این پارامتر در
    apply_update عملاً dead code بود. اگه main_loop پاس نشه، همون loop ای
    که این coroutine رویش در حال اجراست (loop اصلی سرویس) capture می‌شه.
    """
    if main_loop is None:
        try:
            main_loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning(
                "auto_update_loop: event loop اصلی در دسترس نیست — "
                "disable hook در مسیر legacy اجرا می‌شود"
            )
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
                # v2.14.2 (BUG-18c): apply_update در thread executor اجرا
                # می‌شه (تا git fetch/reset حدوداً ۱۰۰ ثانیه‌ای حلقه رو block
                # نکنه) و main_loop هم به آن پاس می‌شه تا §14.1 گام ۷ برقرار
                # باشه — همان الگویی که main.py و web_panel.py استفاده
                # می‌کنن، ولی با loop وصل‌شده.
                if main_loop is not None:
                    success, msg = await main_loop.run_in_executor(
                        None, functools.partial(apply_update, main_loop=main_loop)
                    )
                else:
                    success, msg = apply_update()
                log.info("apply_update: %s", msg)
                # اگه apply موفق بود، خود process restart می‌شه
                # پس این خط معمولاً اجرا نمی‌شه
        except Exception as e:
            log.warning("auto_update_loop error: %s", e)
        await asyncio.sleep(interval)


def get_version_info() -> dict:
    """اطلاعات برای نمایش در پنل ادمین."""
    state = _read_state()
    return {
        "local_commit": get_local_commit(),
        "remote_commit": get_remote_commit(),
        "pending_commits": get_pending_commits(),
        "has_local_mods": has_local_modifications(),
        "rolled_back": state.get("rolled_back", False),
        "rolled_back_at": state.get("rolled_back_at", 0),
        "last_check": state.get("last_check", 0),
        "last_update_at": state.get("last_update_at", 0),
    }
