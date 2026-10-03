import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export async function apiFetch<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

export function formatToman(n: number | null | undefined): string {
  if (!n) return "۰";
  return new Intl.NumberFormat("fa-IR").format(n);
}

export function formatNum(n: number | null | undefined): string {
  if (!n) return "۰";
  return new Intl.NumberFormat("en-US").format(n);
}

export function shortHash(s: string | null | undefined, len = 8): string {
  if (!s) return "—";
  return s.length > len ? `${s.slice(0, len)}…` : s;
}
