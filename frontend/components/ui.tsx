/**
 * 通用 UI 原语。保持无解释文案：界面本身承担说明职责。
 */
"use client";

import Link from "next/link";
import { useEffect, type ReactNode } from "react";

/** 居中弹层。点击遮罩或按 Esc 关闭；不做焦点陷阱，够用即可。 */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  maxWidth = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  maxWidth?: string;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        className={`card w-full ${maxWidth} max-h-[85vh] overflow-y-auto p-6`}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {title ? (
          <div className="mb-4 flex items-start justify-between gap-4">
            <h2 className="text-base font-semibold text-slate-900">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="text-slate-400 transition hover:text-slate-600"
            >
              ✕
            </button>
          </div>
        ) : null}
        <div className="space-y-4">{children}</div>
        {footer ? <div className="mt-6 flex gap-2">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`card p-5 ${className}`}>{children}</div>;
}

export function ProgressBar({
  value,
  className = "",
}: {
  value: number;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className={`h-2 w-full overflow-hidden rounded-full bg-slate-100 ${className}`}>
      <div
        className="h-full rounded-full bg-brand-600 transition-all duration-300"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export function Stars({ value }: { value: number }) {
  return (
    <span className="text-sm tracking-tight">
      {Array.from({ length: 5 }).map((_, index) => (
        <span key={index} className={index < value ? "text-amber-400" : "text-slate-200"}>
          ★
        </span>
      ))}
    </span>
  );
}

export function LevelBadge({ level, name }: { level: number; name: string }) {
  return (
    <span className="chip-brand">
      Lv.{level} {name}
    </span>
  );
}

export function ScenarioCard({
  id,
  icon,
  title,
  titleZh,
  level,
  minutes,
  role,
  onHover,
}: {
  id: number;
  icon: string;
  title: string;
  titleZh?: string;
  level: string;
  minutes: number;
  role: string;
  /** 鼠标移上来时调一次：给调用方机会先把它那句开场白备好。 */
  onHover?: () => void;
}) {
  return (
    <Link
      href={`/scenarios/${id}`}
      onMouseEnter={onHover}
      className="card group flex flex-col gap-3 p-5 transition hover:border-brand-300 hover:shadow-lg"
    >
      <div className="flex items-start justify-between">
        <span className="text-3xl">{icon}</span>
        <span className="chip-slate">{level}</span>
      </div>
      <div>
        <p className="font-semibold text-slate-900 group-hover:text-brand-700">
          {title}
        </p>
        {titleZh ? <p className="text-xs text-slate-400">{titleZh}</p> : null}
      </div>
      <div className="mt-auto flex items-center justify-between text-xs text-slate-500">
        <span>{role}</span>
        <span>{minutes} min</span>
      </div>
    </Link>
  );
}

export function Avatar({
  username,
  avatar,
  className = "h-9 w-9 text-sm",
  rounded = "rounded-full",
}: {
  username: string;
  avatar?: string | null;
  className?: string;
  rounded?: string;
}) {
  // 没有头像时退回用户名首字母，保证列表里永远有东西可看
  if (avatar) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- 头像是本地 /api 资源，无需 next/image 优化
      <img
        src={avatar}
        alt={username}
        className={`${className} ${rounded} object-cover`}
      />
    );
  }
  return (
    <span
      className={`${className} ${rounded} flex items-center justify-center bg-brand-100 font-semibold text-brand-700`}
    >
      {username[0]?.toUpperCase() ?? "?"}
    </span>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="card flex items-center justify-center p-10 text-sm text-slate-400">
      {text}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center justify-center p-8 ${className}`}>
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
      {children}
    </p>
  );
}

export function SectionHeader({
  title,
  action,
}: {
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      {action}
    </div>
  );
}

export function StatPill({
  icon,
  value,
  label,
}: {
  icon: string;
  value: ReactNode;
  label?: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
      <span>{icon}</span>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-slate-900">{value}</p>
        {label ? <p className="text-[11px] text-slate-400">{label}</p> : null}
      </div>
    </div>
  );
}
