"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";
import { Search, ChevronLeft, ChevronRight, Trash2, Edit } from "lucide-react";

export default function UsersPage() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const params = new URLSearchParams({ q, page: String(page), page_size: "50" });
    try {
      const r = await apiFetch(`/api/users?${params}`);
      setItems(r.items || []);
      setTotal(r.total || 0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [page, q]);

  async function handleDelete(uid: number) {
    if (!confirm(`حذف کامل کاربر ${uid}؟ این عمل قابل بازگشت نیست.`)) return;
    try {
      await apiFetch(`/api/users/${uid}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function handleExtend(uid: number) {
    const days = prompt("تعداد روز تمدید:", "30");
    if (!days) return;
    try {
      await apiFetch(`/api/users/${uid}/extend`, {
        method: "POST",
        body: JSON.stringify({ days: parseInt(days) }),
      });
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <AuthShell>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">کاربران</h1>
          <span className="text-sm text-muted-foreground">مجموع: {formatToman(total)}</span>
        </div>

        <div className="relative">
          <Search className="absolute right-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="جستجو با ایدی عددی یا یوزرنیم…"
            value={q}
            onChange={(e) => { setQ(e.target.value); setPage(1); }}
            className="w-full rounded-md border border-input bg-background pr-10 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-right">
                <th className="px-3 py-2 font-medium">user_id</th>
                <th className="px-3 py-2 font-medium">username</th>
                <th className="px-3 py-2 font-medium">نقش</th>
                <th className="px-3 py-2 font-medium">پلن</th>
                <th className="px-3 py-2 font-medium">اشتراک</th>
                <th className="px-3 py-2 font-medium">تاریخ انقضا</th>
                <th className="px-3 py-2 font-medium">عملیات</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">در حال بارگذاری…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">کاربری پیدا نشد</td></tr>
              ) : items.map((u) => (
                <tr key={u.user_id} className="border-t border-border hover:bg-accent/30">
                  <td className="px-3 py-2 font-mono text-xs">{u.user_id}</td>
                  <td className="px-3 py-2">{u.username || "—"}</td>
                  <td className="px-3 py-2">
                    <span className="rounded bg-accent px-2 py-0.5 text-xs">{u.role}</span>
                  </td>
                  <td className="px-3 py-2">{u.plan || "—"}</td>
                  <td className="px-3 py-2">
                    {u.sub_status === "active" ? "✅ فعال" : u.sub_status === "expired" ? "❌ منقضی" : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">{u.expire_date || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleExtend(u.user_id)}
                        className="text-xs text-blue-400 hover:text-blue-300"
                        title="تمدید"
                      >
                        <Edit className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(u.user_id)}
                        className="text-xs text-destructive hover:text-destructive/80"
                        title="حذف کامل"
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
