"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch } from "@/lib/utils";

export default function SettingsPage() {
  const [s, setS] = useState<any>(null);

  async function load() {
    try {
      setS(await apiFetch("/api/settings"));
    } catch {}
  }
  useEffect(() => { load(); }, []);

  async function toggleMaintenance() {
    try {
      await apiFetch("/api/settings", {
        method: "PATCH",
        body: JSON.stringify({ maintenance_mode: !s.maintenance_mode }),
      });
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  if (!s) return <AuthShell><div className="text-muted-foreground">در حال بارگذاری…</div></AuthShell>;

  return (
    <AuthShell>
      <div className="space-y-4 max-w-3xl">
        <h1 className="text-2xl font-bold">تنظیمات سیستم</h1>

        <div className="rounded-lg border border-border bg-card p-5 space-y-4">
          <div>
            <h2 className="font-semibold mb-2">حالت نگهداری (Maintenance Mode)</h2>
            <div className="flex items-center gap-3">
              <button
                onClick={toggleMaintenance}
                className={`rounded-md px-3 py-1.5 text-sm ${
                  s.maintenance_mode
                    ? "bg-yellow-500/20 text-yellow-400"
                    : "bg-green-500/20 text-green-400"
                }`}
              >
                {s.maintenance_mode ? "🟡 فعال (شامل استارت‌های جدید)" : "🟢 غیرفعال"}
              </button>
              <span className="text-xs text-muted-foreground">
                وقتی فعال باشد، استارت‌های جدید رد می‌شوند.
              </span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <h2 className="font-semibold mb-3">اطلاعات سیستم</h2>
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-muted-foreground">panel user</dt>
            <dd className="font-mono">{s.panel_user}</dd>
            <dt className="text-muted-foreground">owner_id (main)</dt>
            <dd className="font-mono">{s.owner_id}</dd>
            <dt className="text-muted-foreground">owner_ids</dt>
            <dd className="font-mono">{s.owner_ids.join(", ")}</dd>
            <dt className="text-muted-foreground">channel_username</dt>
            <dd className="font-mono">{s.channel_username || "—"}</dd>
            <dt className="text-muted-foreground">wallet USDT</dt>
            <dd className="font-mono text-xs">{s.wallet_address_usdt || "—"}</dd>
            <dt className="text-muted-foreground">min_commit_hash</dt>
            <dd className="font-mono text-xs">{s.min_commit_hash || "—"}</dd>
          </dl>
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <h2 className="font-semibold mb-2">⚠️ تنظیمات env-based</h2>
          <p className="text-sm text-muted-foreground">
            تنظیمات env (کانال، کیف پول، min_commit) برای تغییر نیاز به ویرایش فایل env و restart سرویس دارند.
            برای ویرایش:
          </p>
          <pre className="mt-2 rounded bg-muted p-3 text-xs overflow-x-auto">
{`sudo nano /etc/cianet.env
sudo systemctl restart cianet cianet-panel`}
          </pre>
        </div>
      </div>
    </AuthShell>
  );
}
