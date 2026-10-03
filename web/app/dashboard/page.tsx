"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";
import { Users, Bot, Wallet, MessageSquare, Activity } from "lucide-react";

function StatCard({ title, value, icon: Icon, hint }: any) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{title}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-2 text-3xl font-bold">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch("/api/dashboard")
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <AuthShell><div className="text-muted-foreground">در حال بارگذاری…</div></AuthShell>;
  if (!data || data.error) return (
    <AuthShell>
      <div className="text-destructive">خطا در دریافت آمار: {data?.error || "نامشخص"}</div>
    </AuthShell>
  );

  return (
    <AuthShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">داشبورد</h1>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="کل اکانت‌ها"
            value={formatToman(data.accounts.total)}
            icon={Bot}
            hint={`${formatToman(data.accounts.running)} در حال اجرا`}
          />
          <StatCard
            title="کاربران"
            value={formatToman(data.users.total)}
            icon={Users}
          />
          <StatCard
            title="اشتراک‌های فعال"
            value={formatToman(data.subscriptions.active)}
            icon={Activity}
            hint={`${formatToman(data.subscriptions.expired)} منقضی`}
          />
          <StatCard
            title="تیکت‌های باز"
            value={formatToman(data.tickets.open)}
            icon={MessageSquare}
          />
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <h2 className="text-lg font-semibold mb-4">آمار مالی (۳۰ روز اخیر)</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-sm text-muted-foreground">درآمد ۳۰ روز</div>
              <div className="mt-1 text-2xl font-bold">{formatToman(data.finance.revenue_30d_toman)} تومان</div>
            </div>
            <div>
              <div className="text-sm text-muted-foreground">MRR (تقریبی)</div>
              <div className="mt-1 text-2xl font-bold">{formatToman(data.finance.mrr_toman)} تومان</div>
            </div>
          </div>
          {data.finance.daily_revenue && data.finance.daily_revenue.length > 0 && (
            <div className="mt-4">
              <div className="text-sm text-muted-foreground mb-2">درآمد روزانه</div>
              <div className="space-y-1">
                {data.finance.daily_revenue.slice(-10).map((d: any, i: number) => (
                  <div key={i} className="flex justify-between text-xs">
                    <span className="text-muted-foreground">{d.date}</span>
                    <span>{formatToman(d.amount)} تومان</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <h2 className="text-lg font-semibold mb-3">نسخه</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">local: </span>
              <code className="bg-muted px-2 py-0.5 rounded">{data.version.local_commit?.slice(0, 8) || "—"}</code>
            </div>
            <div>
              <span className="text-muted-foreground">remote: </span>
              <code className="bg-muted px-2 py-0.5 rounded">{data.version.remote_commit?.slice(0, 8) || "—"}</code>
            </div>
          </div>
          {data.version.build && (
            <div className="mt-2 text-xs text-muted-foreground">build: {data.version.build}</div>
          )}
        </div>
      </div>
    </AuthShell>
  );
}
