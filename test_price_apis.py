#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Price API Fix Test Suite (v1.6.0)
====================================
Tests all crypto/gold price APIs to make sure they work.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


async def test_single_api(name, fn, expected_min=0.0):
    """تست یک API به‌صورت ایزوله"""
    try:
        result = await fn
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, Exception):
            record(name, False, f"{type(result).__name__}: {str(result)[:60]}")
            return 0.0
        if result and result > expected_min:
            record(name, True, f"{result:,.0f}")
            return result
        record(name, False, "مقدار صفر برگشت")
        return 0.0
    except Exception as e:
        record(name, False, f"{type(e).__name__}: {str(e)[:60]}")
        return 0.0


async def test_crypto():
    print("─" * 60)
    print("💰 تست APIهای کریپتو")
    from main import (
        _nobitex_toman, _wallex_toman, _exir_toman,
        _tabdeal_toman, _coingecko_irr, _get_toman_price,
    )

    for coin in ["usdt", "ton", "trx"]:
        print(f"\n  ━━ {coin.upper()} ━━")
        # هر ۵ منبع موازی تست می‌شن
        results = await asyncio.gather(
            _exir_toman(coin),
            _nobitex_toman(coin),
            _wallex_toman(coin),
            _tabdeal_toman(coin),
            _coingecko_irr(coin),
            return_exceptions=True,
        )
        names = ["Exir", "Nobitex", "Wallex", "Tabdeal", "CoinGecko-IRR"]
        any_works = False
        for n, p in zip(names, results):
            if isinstance(p, Exception):
                pass
            elif p and p > 0:
                any_works = True
                print(f"    ✅ {n:15s} {p:>12,.0f} تومان")
        if not any_works:
            print(f"    ⚠️ هیچ منبعی جواب نداد — مشکل شبکه/سرور")

        # تابع اصلی
        final = await _get_toman_price(coin)
        record(f"_get_toman_price('{coin}')", final > 0,
               f"{final:,.0f} تومان" if final > 0 else "❌ 0 — هیچ منبعی کار نکرد")


async def test_gold():
    print("─" * 60)
    print("🏆 تست APIهای طلا")
    from main import _navasan_repo_gold

    p18, p24 = await _navasan_repo_gold()
    record("طلای ۱۸ عیار", p18 > 0, f"{p18:,.0f} تومان" if p18 > 0 else "0")
    record("طلای ۲۴ عیار", p24 > 0, f"{p24:,.0f} تومان" if p24 > 0 else "0")
    # چک: نسبت ۲۴/۱۸ = ۴/۳ ≈ ۱.۳۳
    if p18 > 0 and p24 > 0:
        ratio = p24 / p18
        record("نسبت ۲۴/۱۸ صحیح است", abs(ratio - (24/18)) < 0.01,
               f"ratio={ratio:.4f} (expected 1.3333)")


def test_endpoints_used():
    print("─" * 60)
    print("🔗 تست: URL منابع")
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # نباید bit24 داشته باشیم (مرده)
    record("بدون bit24.cash", "bit24.cash" not in content,
           "bit24 حذف شد ✓" if "bit24.cash" not in content else "هنوز هست!")

    # باید tabdeal داشته باشیم
    record("شامل tabdeal", "tabdeal" in content, "Tabdeal اضافه شد ✓")

    # باید orderbook جدید Nobitex داشته باشیم
    record("Nobitex /v2/orderbook", "v2/orderbook" in content,
           "اندپوینت جدید ✓")


async def test_handlers_safe():
    print("─" * 60)
    print("🛡 تست: error handling")
    from main import _get_toman_price

    # حتی با کوین نامعتبر هم نباید crash کنه
    for bad in ["invalid_coin", "", "FAKE"]:
        try:
            p = await _get_toman_price(bad)
            if p == 0.0:
                record(f"_get_toman_price('{bad}')", True, "0 (graceful)")
            else:
                record(f"_get_toman_price('{bad}')", True, f"{p:,.0f}")
        except Exception as e:
            record(f"_get_toman_price('{bad}')", False,
                   f"CRASH: {type(e).__name__}")


async def main():
    print("=" * 60)
    print("💰 Price API Fix Test Suite (v1.6.0)")
    print("=" * 60)

    try:
        await test_crypto()
        await test_gold()
        test_endpoints_used()
        await test_handlers_safe()
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
