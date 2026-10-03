"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";

export default function AuditPage() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [actorId, setActorId] = useState("");
  const [action, setAction] = useState("");

  async function load() {
    const params = new URLSearchParams({ page: String(page), page_size: "100" });
    if (actorId) params.set("actor_id", actorId);
    if (action) params.set("action", action);
    try {
      const r = await apiFetch(`/api/audit-log?${params}`);
      setItems(r.items || []);
      setTotal(r.total || 0);
    } catch {}
  }

  useEffect(() => { load(); }, [page, actorId, action]);

  return (
    <AuthShell>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Audit Log</h1>
          <span className="text-sm text-muted-foreground">مجموع: {formatToman(total)}</span>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <input
            type="text"
            placeholder="فیلتر با actor_id…"
            value={actorId}
            onChange={(e) => { setActorId(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
          <input
            type="text"
            placeholder="فیلتر با action…"
            value={action}
            onChange={(e) => { setAction(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
        </div>

        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-right">
                <th className="px-3 py-2 font-medium">ID</th>
                <th className="px-3 py-2 font-medium">actor_id</th>
                <th className="px-3 py-2 font-medium">action</th>
                <th className="px-3 py-2 font-medium">details</th>
                <th className="px-3 py-2 font-medium">زمان</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr><td colSpan={5} className="text-center py-8 text-muted-foreground">رکوردی پیدا نشد</td></tr>
              ) : items.map((l) => (
                <tr key={l.id} className="border-t border-border hover:bg-accent/30">
                  <td className="px-3 py-2 font-mono text-xs">{l.id}</td>
                  <td className="px-3 py-2 font-mono text-xs">{l.actor_id}</td>
                  <td className="px-3 py-2 font-mono text-xs">{l.action}</td>
                  <td className="px-3 py-2 text-xs max-w-md truncate">{l.details || "—"}</td>
                  <td className="px-3 py-2 text-xs">{l.created_at || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AuthShell>
  );
}
