/**
 * 登录后的应用外壳：顶部导航 + 内容区。
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "首页" },
  { href: "/scenarios", label: "场景" },
  { href: "/chat", label: "AI Tutor" },
  { href: "/reading", label: "精读" },
  { href: "/wordbook", label: "词书" },
  { href: "/vocabulary", label: "词库" },
  { href: "/leaderboard", label: "排行榜" },
  { href: "/forum", label: "论坛" },
  { href: "/friends", label: "好友" },
  { href: "/settings/ai", label: "AI 模型" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  // 管理员在导航末尾多一个后台入口，普通用户看不到
  const nav =
    user?.role === "ADMIN"
      ? [...NAV, { href: "/admin", label: "管理" }]
      : NAV;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">
              L
            </span>
            <span className="hidden text-base font-semibold text-slate-900 sm:block">
              LinguaScene
            </span>
          </Link>

          <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
            {nav.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/dashboard" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm transition ${
                    active
                      ? "bg-brand-50 font-medium text-brand-700"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-3">
            {user ? (
              <div className="hidden items-center gap-2 sm:flex">
                <span className="chip-brand">🔥 {user.streak}</span>
                <span className="chip-slate">⭐ {user.xp}</span>
              </div>
            ) : null}
            <Link href="/profile" title="个人资料">
              <Avatar
                username={user?.username ?? "?"}
                avatar={user?.avatar}
                className="h-8 w-8 text-sm"
              />
            </Link>
            <button
              onClick={logout}
              className="text-xs text-slate-400 hover:text-slate-600"
            >
              退出
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
