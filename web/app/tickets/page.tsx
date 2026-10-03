"use client";

import { useEffect, useState } from "react";
import AuthShell from "@/components/AuthShell";
import { apiFetch, formatToman } from "@/lib/utils";
import { Send } from "lucide-react";

export default function TicketsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState("open");
  const [selected, setSelected] = useState<any>(null);
  const [reply, setReply] = useState("");

  async function load() {
    try {
      const r = await apiFetch(`/api/tickets?status_filter=${filter}`);
      setItems(r.items || []);
    } catch {}
  }

  useEffect(() => { load(); }, [filter]);

  async function openTicket(id: number) {
    try {
      const r = await apiFetch(`/api/tickets/${id}`);
      setSelected(r);
      setReply("");
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function sendReply() {
    if (!selected || !reply.trim()) return;
    try {
      await apiFetch(`/api/tickets/${selected.ticket.id}/reply`, {
        method: "POST",
        body: JSON.stringify({ text: reply }),
      });
      await openTicket(selected.ticket.id);
      setReply("");
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <AuthShell>
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">تیکت‌ها</h1>

        <div className="flex gap-2">
          {["open", "answered", "closed", ""].map((f) => (
            <button
              key={f}
              onClick={() => { setFilter(f); setSelected(null); }}
              className={`rounded-md px-3 py-1.5 text-sm ${
                filter === f ? "bg-primary text-primary-foreground" : "border border-border"
              }`}
            >
              {f || "همه"}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1 rounded-lg border border-border bg-card overflow-hidden max-h-[600px] overflow-y-auto">
            {items.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">تیکتی پیدا نشد</div>
            ) : items.map((t) => (
              <button
                key={t.id}
                onClick={() => openTicket(t.id)}
                className={`w-full text-right p-3 border-b border-border hover:bg-accent/30 ${
                  selected?.ticket.id === t.id ? "bg-accent" : ""
                }`}
              >
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>#{t.id}</span>
                  <span>{t.status}</span>
                </div>
                <div className="mt-1 text-sm font-medium truncate">{t.subject || "—"}</div>
                <div className="text-xs text-muted-foreground">user: {t.user_id}</div>
              </button>
            ))}
          </div>

          <div className="lg:col-span-2 rounded-lg border border-border bg-card p-4">
            {!selected ? (
              <div className="text-center py-12 text-sm text-muted-foreground">یک تیکت انتخاب کن</div>
            ) : (
              <div className="space-y-3">
                <div className="flex justify-between">
                  <h3 className="font-semibold">#{selected.ticket.id} — {selected.ticket.subject || "بدون موضوع"}</h3>
                  <span className="text-xs text-muted-foreground">{selected.ticket.status}</span>
                </div>
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {selected.messages.map((m: any) => (
                    <div key={m.id} className={`rounded p-2 text-sm ${
                      m.sender_id === selected.ticket.user_id ? "bg-muted" : "bg-primary/10"
                    }`}>
                      <div className="text-xs text-muted-foreground mb-1">user {m.sender_id}</div>
                      <div className="whitespace-pre-wrap">{m.body}</div>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <textarea
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="پاسخ…"
                    rows={2}
                    className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  />
                  <button
                    onClick={sendReply}
                    className="rounded-md bg-primary px-3 py-2 text-primary-foreground"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </AuthShell>
  );
}
