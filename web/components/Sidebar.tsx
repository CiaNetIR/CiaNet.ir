"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Users, Bot, Wallet, MessageSquare,
  History, GitBranch, Settings, KeyRound, LogOut, ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "داشبورد", icon: LayoutDashboard },
  { href: "/users", label: "کاربران", icon: Users },
  { href: "/accounts", label: "سلف‌بات‌ها", icon: Bot },
  { href: "/finance", label: "امور مالی", icon: Wallet },
  { href: "/tickets", label: "تیکت‌ها", icon: MessageSquare },
  { href: "/audit", label: "Audit Log", icon: History },
  { href: "/version", label: "نسخه", icon: GitBranch },
  { href: "/tools", label: "هش و api_id", icon: KeyRound },
  { href: "/settings", label: "تنظیمات", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<{ username: string; role: string } | null>(null);

  useEffect(() => {
    fetch("/api/auth/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setUser(d?.user || null))
      .catch(() => setUser(null));
  }, [pathname]);

  if (pathname === "/login") return null;

  return (
    <aside className="fixed inset-y-0 right-0 w-64 border-l border-border bg-card z-40">
      <div className="flex h-16 items-center gap-2 px-6 border-b border-border">
        <ShieldCheck className="h-6 w-6 text-primary" />
        <span className="font-bold text-lg">CiaNet Panel</span>
      </div>

      <nav className="flex flex-col gap-1 p-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="absolute bottom-0 left-0 right-0 p-3 border-t border-border">
        {user ? (
          <div className="flex items-center justify-between">
            <div className="text-xs">
              <div className="font-medium">{user.username}</div>
              <div className="text-muted-foreground">{user.role}</div>
            </div>
            <button
              onClick={async () => {
                await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
                router.push("/login");
              }}
              className="text-muted-foreground hover:text-foreground"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <Link href="/login" className="text-xs text-muted-foreground hover:text-foreground">
            ورود
          </Link>
        )}
      </div>
    </aside>
  );
}
