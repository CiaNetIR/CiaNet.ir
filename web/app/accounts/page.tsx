"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";
import { Search, ChevronLeft, ChevronRight, Power, PowerOff, Trash2 } from "lucide-react";

export default function AccountsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const params = new URLSearchParams({ q, page: String(page), page_size: "50" });
    try {
      const r = await apiFetch(`/api/accounts?${params}`);
      setItems(r.items || []);
      setTotal(r.total || 0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [page, q]);

  async function handleToggle(tag: string, disabled: boolean) {
    try {
      await apiFetch(`/api/accounts/${tag}/${disabled ? "enable" : "disable"}`, { method: "POST" });
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function handleDelete(tag: string) {
    if (!confirm(`حذف اکانت «${tag}»؟ فایل سشن هم پاک می‌شه.`)) return;
    try {
      await apiFetch(`/api/accounts/${tag}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <AuthShell>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">سلف‌بات‌ها</h1>
          <span className="text-sm text-muted-foreground">مجموع: {formatToman(total)}</span>
        </div>

        <div className="relative">
          <Search className="absolute right-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="جستجو با تگ یا شماره…"
            value={q}
            onChange={(e) => { setQ(e.target.value); setPage(1); }}
            className="w-full rounded-md border border-input bg-background pr-10 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-right">
                <th className="px-3 py-2 font-medium">تگ</th>
                <th className="px-3 py-2 font-medium">شماره</th>
                <th className="px-3 py-2 font-medium">owner_id</th>
                <th className="px-3 py-2 font-medium">وضعیت</th>
                <th className="px-3 py-2 font-medium">پروکسی</th>
                <th className="px-3 py-2 font-medium">منبع</th>
                <th className="px-3 py-2 font-medium">عملیات</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">در حال بارگذاری…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">اکانتی پیدا نشد</td></tr>
              ) : items.map((a) => (
                <tr key={a.tag} className="border-t border-border hover:bg-accent/30">
                  <td className="px-3 py-2 font-mono">{a.tag}</td>
                  <td className="px-3 py-2 text-xs">{a.phone || "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{a.owner_user_id || "—"}</td>
                  <td className="px-3 py-2">
                    {a.disabled ? (
                      <span className="rounded bg-destructive/20 px-2 py-0.5 text-xs text-destructive">غیرفعال</span>
                    ) : a.running ? (
                      <span className="rounded bg-green-500/20 px-2 py-0.5 text-xs text-green-400">در حال اجرا</span>
                    ) : (
                      <span className="rounded bg-yellow-500/20 px-2 py-0.5 text-xs text-yellow-400">متوقف</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {a.proxy_set ? "✓ تنظیم‌شده" : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">{a.provision_source || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleToggle(a.tag, a.disabled)}
                        className={a.disabled ? "text-green-400" : "text-yellow-400"}
                        title={a.disabled ? "فعال‌سازی" : "توقف"}
                      >
                        {a.disabled ? <Power className="h-3.5 w-3.5" /> : <PowerOff className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        onClick={() => handleDelete(a.tag)}
                        className="text-destructive"
                        title="حذف"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            <ChevronRight className="h-4 w-4 inline" /> قبلی
          </button>
          <span className="text-sm text-muted-foreground">صفحه {formatToman(page)}</span>
          <button
            disabled={page * 50 >= total}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            بعدی <ChevronLeft className="h-4 w-4 inline" />
          </button>
        </div>
      </div>
    </AuthShell>
  );
}
