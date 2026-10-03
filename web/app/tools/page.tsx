"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";
import { Plus, RefreshCw } from "lucide-react";

export default function ToolsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const r = await apiFetch("/api/tools/api-creds");
      setItems(r.items || []);
    } catch {}
  }
  useEffect(() => { load(); }, []);

  async function addCred() {
    if (!apiId || !apiHash) return;
    setBusy(true);
    try {
      await apiFetch("/api/tools/api-creds", {
        method: "POST",
        body: JSON.stringify({ api_id: parseInt(apiId), api_hash: apiHash, label }),
      });
      setApiId(""); setApiHash(""); setLabel("");
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function rotate() {
    if (!confirm("Rotate api_id/api_hash روی همه‌ی اکانت‌ها؟")) return;
    setBusy(true);
    try {
      const r = await apiFetch("/api/tools/api-creds/rotate", { method: "POST" });
      alert(`✅ ${r.rotated_count} اکانت update شد (pool: ${r.pool_size})`);
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">هش‌ها و api_id</h1>

        <div className="rounded-lg border border-border bg-card p-5">
          <h2 className="font-semibold mb-3">افزودن api_id/api_hash جدید</h2>
          <div className="grid grid-cols-3 gap-2">
            <input
              type="number"
              placeholder="api_id"
              value={apiId}
              onChange={(e) => setApiId(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
            <input
              type="text"
              placeholder="api_hash"
              value={apiHash}
              onChange={(e) => setApiHash(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
            />
            <input
              type="text"
              placeholder="label (اختیاری)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <button
            onClick={addCred}
            disabled={busy}
            className="mt-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
          >
            <Plus className="h-4 w-4 inline" /> افزودن
          </button>
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold">api_id/api_hash های موجود</h2>
            <button
              onClick={rotate}
              disabled={busy}
              className="rounded-md border border-border px-3 py-1 text-xs hover:bg-accent"
            >
              <RefreshCw className="h-3 w-3 inline" /> rotate روی همه‌ی اکانت‌ها
            </button>
          </div>
          {items.length === 0 ? (
            <div className="text-sm text-muted-foreground">هنوز api_id/api_hash ثبت نشده</div>
          ) : (
            <div className="space-y-2">
              {items.map((c, i) => (
                <div key={i} className="border border-border rounded p-3 text-sm">
                  <div className="flex justify-between">
                    <span className="font-mono">api_id: {c.api_id}</span>
                    <span className="text-xs text-muted-foreground">used by {formatToman(c.used_by.length)}</span>
                  </div>
                  <div className="font-mono text-xs text-muted-foreground mt-1 break-all">
                    hash: {c.api_hash.slice(0, 16)}…
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    اکانت‌ها: {c.used_by.slice(0, 5).join(", ")}{c.used_by.length > 5 ? "…" : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </AuthShell>
  );
}
