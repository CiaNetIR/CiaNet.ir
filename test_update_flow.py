"""
test_update_flow.py — تست‌های E2E سیستم Auto-Update
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

۹ سناریوی واقعی از چرخه‌ی آپدیت:
1. check_for_update بدون تغییر → None
2. شبیه‌سازی remote ahead → pending commits لیست می‌شه
3. acquire lock → release lock → concurrent update rejected
4. apply_update با فایل mock → success
5. apply_update بدون تغییر → success
6. propagation_marker round-trip
7. get_version_info → keys درست
8. backup main.py قبل از update
9. invalid commit handling
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# sys.path
sys.path.insert(0, str(Path(__file__).parent))

import cianet_updater as upd


class TestCheckForUpdate(unittest.IsolatedAsyncioTestCase):
    """۱+۲: چک کردن update."""

    async def test_check_returns_none_when_no_update(self):
        """اگه local == remote، None برمی‌گرده."""
        with patch.object(upd, "get_local_commit", return_value="abc123"):
            with patch.object(upd, "get_remote_commit", return_value="abc123"):
                result = await upd.check_for_update()
                self.assertIsNone(result)

    async def test_check_returns_info_when_update_available(self):
        """اگه remote ahead، dict با commits برمی‌گرده."""
        with patch.object(upd, "get_local_commit", return_value="local123"):
            with patch.object(upd, "get_remote_commit", return_value="remote456"):
                with patch.object(upd, "get_pending_commits",
                                  return_value=["abc fix bug", "def add feature"]):
                    result = await upd.check_for_update()
                    self.assertIsNotNone(result)
                    self.assertEqual(result["local"], "local123")
                    self.assertEqual(result["remote"], "remote456")
                    self.assertEqual(result["count"], 2)
                    self.assertEqual(len(result["commits"]), 2)


class TestLocking(unittest.IsolatedAsyncioTestCase):
    """۳: concurrent update باید reject بشه."""

    async def test_concurrent_update_locked(self):
        """اگه یکی update داره می‌کنه، دومی lock می‌شه."""
        # پاک کردن lock قبلی
        if upd.LOCK_FILE.exists():
            upd.LOCK_FILE.unlink()
        # acquire first
        ok1 = upd._acquire_lock(timeout=2)
        self.assertTrue(ok1)
        # دومی باید fail شه (یا wait کنه و fail شه)
        ok2 = upd._acquire_lock(timeout=1)
        self.assertFalse(ok2)
        upd._release_lock()
        # الان باید بتونه acquire کنه
        ok3 = upd._acquire_lock(timeout=2)
        self.assertTrue(ok3)
        upd._release_lock()


class TestApplyUpdate(unittest.IsolatedAsyncioTestCase):
    """۴+۵: apply_update با mock."""

    async def test_apply_update_success(self):
        """موفق: pull + restart می‌کنه."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # mock git pull
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Already up to date."
            mock_result.stderr = ""
            with patch("cianet_updater.subprocess.run", return_value=mock_result):
                with patch.object(upd, "get_local_commit", return_value="newcommit123"):
                    with patch.object(upd, "_backup_main_py", return_value=None):
                        # restart رو غیرفعال کن (وگرنه واقعی اجرا می‌شه)
                        with patch("cianet_updater.subprocess.Popen") as mock_popen:
                            # mock the main.py hook
                            with patch.dict("sys.modules", {
                                "main": MagicMock(
                                    _disable_all_accounts_for_update=AsyncMock(return_value="ok"),
                                ),
                            }):
                                success, msg = upd.apply_update(repo_dir=tmpdir, restart=False)
                                self.assertTrue(success)
                                self.assertIn("newcommi", msg)  # 8 chars
                                self.assertIn("آپدیت شد", msg)

    async def test_apply_update_git_pull_fails(self):
        """اگه git pull fail بشه، error برمی‌گرده."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "fatal: not a git repo"
            with patch("cianet_updater.subprocess.run", return_value=mock_result):
                with patch.dict("sys.modules", {
                    "main": MagicMock(
                        _disable_all_accounts_for_update=AsyncMock(return_value="ok"),
                    ),
                }):
                    success, msg = upd.apply_update(repo_dir=tmpdir, restart=False)
                    self.assertFalse(success)
                    self.assertIn("git pull failed", msg)


class TestPropagationMarker(unittest.TestCase):
    """۶: state file."""

    def setUp(self):
        """state file رو به temp منتقل کن."""
        self._orig_state_file = upd.STATE_FILE
        self._tmpdir = tempfile.mkdtemp()
        upd.STATE_FILE = Path(self._tmpdir) / "state.json"

    def tearDown(self):
        upd.STATE_FILE = self._orig_state_file
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_propagation_marker_round_trip(self):
        """set + read = True، clear + read = False."""
        # اول False
        self.assertFalse(upd.propagation_marker_present())

        # set True
        state = upd._read_state()
        state["pending_propagation"] = True
        upd._write_state(state)

        # حالا True
        self.assertTrue(upd.propagation_marker_present())

        # mark done
        upd.mark_propagation_done()
        self.assertFalse(upd.propagation_marker_present())


class TestVersionInfo(unittest.TestCase):
    """۷: get_version_info."""

    def test_returns_expected_keys(self):
        """باید local_commit, remote_commit, pending_commits داشته باشه."""
        with patch.object(upd, "get_local_commit", return_value="loc"):
            with patch.object(upd, "get_remote_commit", return_value="rem"):
                with patch.object(upd, "get_pending_commits", return_value=["x"]):
                    info = upd.get_version_info()
                    self.assertIn("local_commit", info)
                    self.assertIn("remote_commit", info)
                    self.assertIn("pending_commits", info)
                    self.assertIn("last_check", info)
                    self.assertIn("last_update_at", info)


class TestBackup(unittest.TestCase):
    """۸: backup main.py."""

    def test_backup_main_py(self):
        """اگه main.py وجود داشته باشه، backup ساخته می‌شه."""
        with tempfile.TemporaryDirectory() as tmpdir:
            main_py = Path(tmpdir) / "main.py"
            main_py.write_text("# main")
            backup = upd._backup_main_py(tmpdir)
            self.assertIsNotNone(backup)
            self.assertTrue(Path(backup).exists())
            self.assertEqual(Path(backup).read_text(), "# main")
            self.assertIn("pre-auto-update", backup)

    def test_backup_no_main_py(self):
        """اگه main.py نباشه، None برمی‌گرده."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup = upd._backup_main_py(tmpdir)
            self.assertIsNone(backup)


class TestInvalidCommits(unittest.TestCase):
    """۹: invalid handling."""

    def test_get_local_commit_handles_missing_repo(self):
        """اگه git repo نباشه، None برمی‌گرده (نه exception)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = upd.get_local_commit(tmpdir)
            self.assertIsNone(result)

    def test_get_pending_commits_empty(self):
        """اگه git نباشه، لیست خالی برمی‌گرده."""
        with tempfile.TemporaryDirectory() as tmpdir:
            commits = upd.get_pending_commits(tmpdir)
            self.assertEqual(commits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
