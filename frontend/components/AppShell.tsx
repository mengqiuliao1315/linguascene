"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Avatar, Modal } from "@/components/ui";
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

// 手机底部标签栏：只保留最高频入口，其余收进「更多」，
// 避免把桌面端 10 项横向滚动导航原样塞进小屏。
const MOBILE_TABS = [
  { href: "/dashboard", label: "首页", icon: "🏠" },
  { href: "/scenarios", label: "场景", icon: "🎬" },
  { href: "/chat", label: "AI Tutor", icon: "💬" },
  { href: "/reading", label: "精读", icon: "📖" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [moreOpen, setMoreOpen] = useState(false);

  const nav =
    user?.role === "ADMIN"
      ? [...NAV, { href: "/admin", label: "管理" }]
      : NAV;

  const isActive = (href: string) =>
    pathname === href || (href !== "/dashboard" && pathname.startsWith(href));

  return (
    <div className="min-h-dvh bg-slate-50">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 md:gap-6">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">
              L
            </span>
            <span className="text-base font-semibold text-slate-900">
              LinguaScene
            </span>
          </Link>

          <nav className="hidden flex-1 items-center gap-1 md:flex">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm transition ${
                  isActive(item.href)
                    ? "bg-brand-50 font-medium text-brand-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2 md:gap-3">
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

      <main className="mx-auto max-w-6xl px-4 py-6 pb-safe-nav">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 pb-safe backdrop-blur md:hidden">
        <div className="mx-auto flex max-w-6xl">
          {MOBILE_TABS.map((tab) => {
            const active = isActive(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`flex flex-1 flex-col items-center gap-0.5 py-2 ${
                  active ? "text-brand-600" : "text-slate-400"
                }`}
              >
                <span className="text-lg leading-none">{tab.icon}</span>
                <span className="text-[11px] font-medium">{tab.label}</span>
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            className="flex flex-1 flex-col items-center gap-0.5 py-2 text-slate-400"
          >
            <span className="text-lg leading-none">⋯</span>
            <span className="text-[11px] font-medium">更多</span>
          </button>
        </div>
      </nav>

      <Modal
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        title="更多功能"
        maxWidth="max-w-sm"
      >
        <div className="grid grid-cols-2 gap-2">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMoreOpen(false)}
              className={`rounded-xl border px-3 py-2.5 text-sm transition ${
                isActive(item.href)
                  ? "border-brand-200 bg-brand-50 font-medium text-brand-700"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>
        <button
          type="button"
          onClick={logout}
          className="btn-ghost w-full"
        >
          退出登录
        </button>
      </Modal>
    </div>
  );
}