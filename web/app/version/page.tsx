"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch } from "@/lib/utils";
import { Download, RotateCcw, RefreshCw } from "lucide-react";

export default function VersionPage() {
  const [info, setInfo] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setInfo(await apiFetch("/api/version"));
    } catch {}
  }
  useEffect(() => { load(); }, []);

  async function applyUpdate() {
    if (!confirm("اعمال آپدیت؟ سرویس restart می‌شه.")) return;
    setBusy(true);
    try {
      const r = await apiFetch("/api/version/apply-update", { method: "POST" });
      alert(r.message || r.note);
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function rollback(filename: string) {
    if (!confirm(`Rollback به ${filename}؟ سرویس restart می‌شه.`)) return;
    setBusy(true);
    try {
      const r = await apiFetch("/api/version/rollback", {
        method: "POST",
        body: JSON.stringify({ filename }),
      });
      alert(`✅ ${r.message || "Rollback applied"}\nbackup: ${r.backup}`);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!info) return <AuthShell><div className="text-muted-foreground">در حال بارگذاری…</div></AuthShell>;

  return (
    <AuthShell>
      <div className="space-y-4 max-w-3xl">
        <h1 className="text-2xl font-bold">مدیریت نسخه</h1>

        <div className="rounded-lg border border-border bg-card p-5 space-y-3">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <div className="text-muted-foreground">ورژن محلی</div>
              <code className="bg-muted px-2 py-1 rounded mt-1 inline-block">{info.local_commit?.slice(0, 8) || "—"}</code>
            </div>
            <div>
              <div className="text-muted-foreground">آخرین remote</div>
              <code className="bg-muted px-2 py-1 rounded mt-1 inline-block">{info.remote_commit?.slice(0, 8) || "—"}</code>
            </div>
          </div>

          {info.is_up_to_date ? (
            <div className="rounded bg-green-500/10 px-3 py-2 text-sm text-green-400">✅ آپ‌تو‌دِیت هستی</div>
          ) : (
            <div className="rounded bg-yellow-500/10 px-3 py-2 text-sm text-yellow-400">
              📥 {info.pending_commits?.length || 0} commit جدید منتظر apply
              {info.pending_commits && (
                <ul className="mt-2 space-y-0.5 text-xs">
                  {info.pending_commits.slice(0, 5).map((c: string, i: number) => (
                    <li key={i} className="font-mono">{c.slice(0, 60)}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button
              onClick={load}
              disabled={busy}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
            >
              <RefreshCw className="h-4 w-4 inline" /> چک آپدیت
            </button>
            {!info.is_up_to_date && (
              <button
                onClick={applyUpdate}
                disabled={busy}
                className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
              >
                <Download className="h-4 w-4 inline" /> اعمال آپدیت
              </button>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <h2 className="font-semibold mb-3">↩️ نسخه‌های قابل rollback</h2>
          {info.rollback_files && info.rollback_files.length > 0 ? (
            <div className="space-y-1">
              {info.rollback_files.map((f: string) => (
                <div key={f} className="flex items-center justify-between text-sm border border-border rounded p-2">
                  <code className="text-xs">{f}</code>
                  <button
                    onClick={() => rollback(f)}
                    disabled={busy}
                    className="text-destructive hover:text-destructive/80"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">هیچ نسخه‌ی پشتیبانی موجود نیست</div>
          )}
        </div>
      </div>
    </AuthShell>
  );
}
