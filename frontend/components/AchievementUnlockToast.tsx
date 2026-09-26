"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Achievement } from "@/lib/types";

const POLL_MS = 20000;

const TOAST_MS = 5200;

export function AchievementUnlockToast() {
  const { user } = useAuth();
  const pathname = usePathname();
  const [queue, setQueue] = useState<Achievement[]>([]);
  const [current, setCurrent] = useState<Achievement | null>(null);

  const seen = useRef<Set<string>>(new Set());
  const checking = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const check = useCallback(async () => {
    if (checking.current) return;
    checking.current = true;
    try {
      const pending = await api.pendingAchievements();
      const fresh = pending.filter((item) => !seen.current.has(item.code));
      if (fresh.length) {
        for (const item of fresh) seen.current.add(item.code);
        setQueue((prev) => [...prev, ...fresh]);
      }
    } catch {

    } finally {
      checking.current = false;
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    check();

    function onFocus() {
      check();
    }
    window.addEventListener("focus", onFocus);
    const interval = setInterval(check, POLL_MS);
    return () => {
      window.removeEventListener("focus", onFocus);
      clearInterval(interval);
    };
  }, [user, pathname, check]);

  useEffect(() => {
    if (current || queue.length === 0) return;
    const [next, ...rest] = queue;
    setQueue(rest);
    setCurrent(next);
  }, [queue, current]);

  const dismiss = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    setCurrent((shown) => {
      if (shown) {

        api.ackAchievements([shown.code]).catch(() => {});
      }
      return null;
    });
  }, []);

  useEffect(() => {
    if (!current) return;
    timer.current = setTimeout(dismiss, TOAST_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, [current, dismiss]);

  if (!current) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex justify-center px-4">
      <div
        role="status"
        aria-live="polite"
        className="achv-toast pointer-events-auto flex max-w-sm items-center gap-3 rounded-2xl border border-brand-200 bg-white px-4 py-3 shadow-card"
      >
        <span className="text-2xl" aria-hidden>
          {current.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium text-brand-600">成就解锁</p>
          <p className="truncate text-sm font-semibold text-slate-900">
            {current.name}
          </p>
          <p className="truncate text-xs text-slate-500">
            {current.description}
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="关闭"
          className="text-slate-300 transition hover:text-slate-500"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
