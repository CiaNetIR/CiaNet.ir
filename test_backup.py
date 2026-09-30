#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup Build Test Suite
========================
Tests that build_backup_zip works correctly with a fresh DB.
"""

import asyncio
import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


def test_init_db_creates_saas_schema():
    print("─" * 60)
    print("🗄 تست: init_db دیتابیس saas را می‌سازد")

    from main import init_db
    init_db()  # idempotent

    import sqlite3
    try:
        conn = sqlite3.connect("saas.db")
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in c.fetchall()}
        required = {"admins", "users", "subscriptions", "licenses",
                    "payments", "orders", "tickets", "dedicated_bots",
                    "pricing", "settings"}
        missing = required - tables
        record("همه جدول‌های ضروری ساخته شدن", not missing,
               f"missing={missing if missing else 'none'}")
    except Exception as e:
        record("اتصال به saas.db", False, str(e))


def test_build_backup_zip():
    print("─" * 60)
    print("📦 تست: ساخت بکاپ ZIP")

    from main import build_backup_zip, _backup_file_name, validate_backup_zip

    test_dir = tempfile.mkdtemp(prefix="bk_test_")
    test_zip = os.path.join(test_dir, _backup_file_name())

    try:
        ok = build_backup_zip(test_zip)
        record("build_backup_zip → True", ok, f"returned {ok}")

        exists = os.path.exists(test_zip)
        record("فایل ZIP ساخته شد", exists,
               f"path={test_zip}" if exists else "MISSING")

        if exists:
            size = os.path.getsize(test_zip)
            record("ZIP غیرخالی", size > 100, f"size={size} bytes")

            # Validate
            v_ok, v_msg = validate_backup_zip(test_zip)
            record("validate_backup_zip → True", v_ok, v_msg[:80])

            # Check manifest
            import zipfile
            with zipfile.ZipFile(test_zip) as zf:
                names = zf.namelist()
                record("شامل backup_manifest.json",
                       "backup_manifest.json" in names,
                       f"files={names}")
                if "backup_manifest.json" in names:
                    with zf.open("backup_manifest.json") as mf:
                        manifest = json.loads(mf.read().decode())
                        record("manifest شامل backup_version",
                               "backup_version" in manifest,
                               f"keys={list(manifest.keys())[:5]}")
                        record("manifest شامل فایل‌ها",
                               len(manifest.get("files", [])) > 0,
                               f"n_files={len(manifest.get('files', []))}")
    except Exception as e:
        import traceback
        record("build_backup_zip بدون exception", False, f"{e}")
        traceback.print_exc()
    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


def test_collect_backup_files():
    print("─" * 60)
    print("📋 تست: فایل‌های قابل بکاپ")

    from main import _collect_backup_files
    files = _collect_backup_files()
    record("_collect_backup_files خروجی دارد", len(files) > 0,
           f"n_files={len(files)}")

    # باید حداقل DB ها و سشن‌ها رو شامل بشه
    has_db = any(f.endswith(".db") for f in files.values())
    record("شامل دیتابیس", has_db, "")


def test_backup_then_validate():
    print("─" * 60)
    print("🔄 تست: چرخه بکاپ → validate")

    from main import build_backup_zip, validate_backup_zip, _backup_file_name

    test_dir = tempfile.mkdtemp(prefix="bk_cycle_")
    test_zip = os.path.join(test_dir, _backup_file_name())

    try:
        # ساخت
        build_ok = build_backup_zip(test_zip)
        record("ساخت موفق", build_ok, "")

        # validate
        if build_ok:
            v_ok, v_msg = validate_backup_zip(test_zip)
            record("validate موفق", v_ok, v_msg[:80])
    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


async def main():
    print("=" * 60)
    print("📦 Backup Build Test Suite")
    print("=" * 60)

    try:
        test_init_db_creates_saas_schema()
        test_collect_backup_files()
        test_build_backup_zip()
        test_backup_then_validate()
    except Exception as e:
        print(f"\n❌ خطای بحرانی: {e}")
        import traceback
        traceback.print_exc()
        return 1

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = len(RESULTS) - passed
    print(f"\n{'='*60}")
    print(f"📊 نتیجه: {passed} موفق / {failed} ناموفق از {len(RESULTS)}")
    print(f"{'='*60}")

    if failed:
        print("\n❌ تست‌های ناموفق:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['details']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
