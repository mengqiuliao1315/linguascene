"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { Avatar } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "首页", icon: "🏠" },
  { href: "/scenarios", label: "场景", icon: "🎬" },
  { href: "/chat", label: "AI Tutor", icon: "💬" },
  { href: "/reading", label: "精读", icon: "📖" },
  { href: "/wordbook", label: "词书", icon: "📚" },
  { href: "/vocabulary", label: "词库", icon: "🔤" },
  { href: "/leaderboard", label: "排行榜", icon: "🏆" },
  { href: "/forum", label: "论坛", icon: "🗣️" },
  { href: "/friends", label: "好友", icon: "👥" },
  { href: "/settings/ai", label: "AI 模型", icon: "🤖" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const tabsRef = useRef<HTMLDivElement>(null);

  const nav =
    user?.role === "ADMIN"
      ? [...NAV, { href: "/admin", label: "管理", icon: "🛠️" }]
      : NAV;

  const isActive = (href: string) =>
    pathname === href || (href !== "/dashboard" && pathname.startsWith(href));

  // 手机底部导航全部入口平铺、左右拖动查看，所以要保证当前页那一项在可视区内。
  useEffect(() => {
    const current = tabsRef.current?.querySelector('[data-active="true"]');
    current?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [pathname]);

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

      {/* 手机底部标签栏：全部入口平铺，一屏放不下的左右拖动查看；
          最右侧会露出下一项的一角，提示还能继续滑 */}
      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 pb-safe backdrop-blur md:hidden">
        <div ref={tabsRef} className="scrollbar-none flex overflow-x-auto">
          {nav.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                data-active={active}
                className={`flex shrink-0 flex-col items-center gap-0.5 px-3.5 py-2 ${
                  active ? "text-brand-600" : "text-slate-400"
                }`}
              >
                <span className="text-lg leading-none">{item.icon}</span>
                <span className="whitespace-nowrap text-[11px] font-medium">
                  {item.label}
                </span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}