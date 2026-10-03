"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";
import { Check, X } from "lucide-react";

export default function FinancePage() {
  const [stats, setStats] = useState<any>(null);
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const params = new URLSearchParams({ status_filter: filter, page: String(page), page_size: "50" });
    try {
      const [s, p] = await Promise.all([
        apiFetch("/api/finance/stats"),
        apiFetch(`/api/finance/payments?${params}`),
      ]);
      setStats(s);
      setItems(p.items || []);
      setTotal(p.total || 0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [filter, page]);

  async function handleAction(id: number, action: "approve" | "reject") {
    try {
      await apiFetch(`/api/finance/payments/${id}/${action}`, { method: "POST" });
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <AuthShell>
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">امور مالی</h1>

        {stats && !stats.error && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="text-sm text-muted-foreground">MRR کل</div>
              <div className="mt-1 text-2xl font-bold">{formatToman(stats.mrr_total_toman)}</div>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="text-sm text-muted-foreground">درآمد ۳۰ روز</div>
              <div className="mt-1 text-2xl font-bold">{formatToman(stats.revenue_30d_toman)}</div>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="text-sm text-muted-foreground">تعداد پرداخت‌ها</div>
              <div className="mt-1 text-2xl font-bold">{formatToman(total)}</div>
            </div>
          </div>
        )}

        <div className="flex gap-2">
          {["", "pending", "approved", "rejected"].map((f) => (
            <button
              key={f}
              onClick={() => { setFilter(f); setPage(1); }}
              className={`rounded-md px-3 py-1.5 text-sm ${
                filter === f ? "bg-primary text-primary-foreground" : "border border-border"
              }`}
            >
              {f || "همه"}
            </button>
          ))}
        </div>

        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-right">
                <th className="px-3 py-2 font-medium">ID</th>
                <th className="px-3 py-2 font-medium">user_id</th>
                <th className="px-3 py-2 font-medium">مبلغ</th>
                <th className="px-3 py-2 font-medium">روش</th>
                <th className="px-3 py-2 font-medium">وضعیت</th>
                <th className="px-3 py-2 font-medium">تاریخ</th>
                <th className="px-3 py-2 font-medium">عملیات</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">در حال بارگذاری…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">پرداختی پیدا نشد</td></tr>
              ) : items.map((p) => (
                <tr key={p.id} className="border-t border-border hover:bg-accent/30">
                  <td className="px-3 py-2 font-mono text-xs">{p.id}</td>
                  <td className="px-3 py-2 font-mono text-xs">{p.user_id}</td>
                  <td className="px-3 py-2">{formatToman(p.amount_toman)}</td>
                  <td className="px-3 py-2 text-xs">{p.method || "—"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${
                      p.status === "approved" ? "bg-green-500/20 text-green-400" :
                      p.status === "rejected" ? "bg-destructive/20 text-destructive" :
                      "bg-yellow-500/20 text-yellow-400"
                    }`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs">{p.paid_at || p.created_at || "—"}</td>
                  <td className="px-3 py-2">
                    {p.status === "pending" && (
                      <div className="flex gap-2">
                        <button onClick={() => handleAction(p.id, "approve")} className="text-green-400">
                          <Check className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => handleAction(p.id, "reject")} className="text-destructive">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AuthShell>
  );
}
