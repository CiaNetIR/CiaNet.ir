"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";

export default function AuthShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/auth/me", { credentials: "include" })
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(() => setLoading(false))
      .catch(() => {
        router.replace("/login");
      });
  }, [router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-muted-foreground">
        <div className="animate-pulse">در حال بارگذاری…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <main className="mr-64 p-6">{children}</main>
    </div>
  );
}
