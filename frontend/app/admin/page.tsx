"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Avatar, EmptyState, Modal, Spinner } from "@/components/ui";
import { BASE_PATH, api } from "@/lib/api";
import { RequireAdmin } from "@/lib/auth";
import type { AdminUser, CreatedCredentials } from "@/lib/types";

const LEVELS = ["A1", "A2", "B1", "B2", "C1"];

function parseServerTime(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`);
}

function suggestPassword(): string {
  const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from({ length: 10 }, () =>
    chars.charAt(Math.floor(Math.random() * chars.length))
  ).join("");
}

function buildShareText(account: {
  username: string;
  email: string;
  password: string;
}): string {
  const origin =
    typeof window === "undefined" ? "" : `${window.location.origin}${BASE_PATH}`;
  const rows: Array<[string, string]> = [
    ["🔗 网址", origin],
    ["👤 用户名", account.username],
    ["📧 邮箱", account.email],
    ["🔑 密码", account.password],
  ];
  const rule = "━━━━━━━━━━━━━━━━━━━━";
  return [
    "🎓 LinguaScene 英语学习平台",
    rule,
    ...rows.map(([key, value]) => `${key}：${value}`),
    rule,
    "用邮箱 + 密码登录，登录后可在「个人资料」里改成自己好记的密码。",
  ].join("\n");
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {

  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

function AdminConsole() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [created, setCreated] = useState<CreatedCredentials | null>(null);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState(suggestPassword);
  const [cefr, setCefr] = useState("B1");
  const [role, setRole] = useState<"USER" | "ADMIN">("USER");
  const [creating, setCreating] = useState(false);

  const [busyId, setBusyId] = useState<number | null>(null);

  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [editUsername, setEditUsername] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  const load = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    return api
      .adminUsers()
      .then(setUsers)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => {
        if (!silent) setLoading(false);
      });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => void load(true), 15000);
    const onFocus = () => void load(true);
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    setCreated(null);
    setCreating(true);
    try {
      const result = await api.adminCreateUser({
        username: username.trim(),
        email: email.trim(),
        password,
        cefr_level: cefr,
        role,
      });
      setCreated(result);
      setUsername("");
      setEmail("");
      setPassword(suggestPassword());
      setCefr("B1");
      setRole("USER");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  async function handleReset(user: AdminUser) {
    const input = window.prompt(
      `设置 ${user.username} 的新密码（留空则随机生成一个）`,
      suggestPassword()
    );
    if (input === null) return;

    const next = input.trim() || suggestPassword();
    if (next.length < 8) {
      setError("密码至少 8 位");
      return;
    }

    setBusyId(user.id);
    setError("");
    try {
      const result = await api.adminResetPassword(user.id, next);
      setCreated({
        id: user.id,
        username: user.username,
        email: user.email,
        password: result.password || next,
      });
      setNotice("密码已更新，请把新密码发给对方");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置失败");
    } finally {
      setBusyId(null);
    }
  }

  async function shareAccount(user: AdminUser) {
    setError("");
    setNotice("");
    setBusyId(user.id);
    try {
      const credentials = await api.adminCredentials(user.id);
      setCreated(credentials);
      const ok = await writeClipboard(buildShareText(credentials));
      setNotice(
        ok
          ? `已复制 ${user.username} 的账号信息`
          : "复制失败，请从下方卡片手动复制"
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "分享失败");
    } finally {
      setBusyId(null);
    }
  }

  function openEdit(user: AdminUser) {
    setEditing(user);
    setEditUsername(user.username);
    setEditEmail(user.email);
    setEditPassword("");
  }

  async function handleSaveEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setSavingEdit(true);
    setError("");
    setNotice("");
    try {
      const payload: {
        username?: string;
        email?: string;
        password?: string;
      } = {};
      if (editUsername.trim() !== editing.username) {
        payload.username = editUsername.trim();
      }
      if (editEmail.trim() !== editing.email) {
        payload.email = editEmail.trim();
      }
      if (editPassword) payload.password = editPassword;

      if (Object.keys(payload).length === 0) {
        setEditing(null);
        return;
      }

      const updated = await api.adminUpdateUser(editing.id, payload);
      setEditing(null);
      if (payload.password) {
        setCreated({
          id: updated.id,
          username: updated.username,
          email: updated.email,
          password: payload.password,
        });
        setNotice(`已更新 ${updated.username}，新密码只显示这一次`);
      } else {
        setNotice(`已更新 ${updated.username} 的账号信息`);
      }
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleRole(user: AdminUser) {
    const next = user.role === "ADMIN" ? "USER" : "ADMIN";
    setBusyId(user.id);
    setError("");
    try {
      await api.adminUpdateRole(user.id, next);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(user: AdminUser) {
    if (
      !window.confirm(
        `删除 ${user.username}？\n\n该账号的学习记录、词库、成就都会一并删除，不可恢复。`
      )
    ) {
      return;
    }
    setBusyId(user.id);
    setError("");
    try {
      await api.adminDeleteUser(user.id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  }

  async function copyCredentials(credentials: CreatedCredentials) {
    if (await writeClipboard(buildShareText(credentials))) {
      setNotice("已复制账号信息");
    } else {
      setError("复制失败，请手动选中复制");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold text-slate-900">账号管理</h1>
        <span className="text-xs text-slate-400">
          共 {users.length} 个账号
        </span>
      </div>

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-xl bg-brand-50 px-3 py-2 text-xs text-brand-700">
          {notice}
        </p>
      ) : null}

      {created ? (
        <div className="card space-y-3 border-brand-200 bg-brand-50/40 p-5">
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <div className="rounded-xl bg-white px-3 py-2">
              <p className="text-[11px] text-slate-400">邮箱</p>
              <p className="font-mono text-slate-800">{created.email}</p>
            </div>
            <div className="rounded-xl bg-white px-3 py-2">
              <p className="text-[11px] text-slate-400">密码</p>
              <p className="font-mono text-slate-800">{created.password}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => copyCredentials(created)}
              className="btn-primary !py-2 text-xs"
            >
              复制账号信息
            </button>
            <button
              onClick={() => setCreated(null)}
              className="btn-ghost !py-2 text-xs"
            >
              关闭
            </button>
          </div>
        </div>
      ) : null}

      <form onSubmit={handleCreate} className="card space-y-4 p-6">
        <p className="section-title">新建账号</p>

        <div className="grid gap-3 sm:grid-cols-2">
          <input
            required
            minLength={2}
            maxLength={32}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="用户名"
            className="input"
          />
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="邮箱（登录用）"
            className="input"
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex gap-2">
            <input
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="初始密码"
              className="input font-mono"
            />
            <button
              type="button"
              onClick={() => setPassword(suggestPassword())}
              className="btn-ghost shrink-0 !px-3 text-xs"
            >
              换一个
            </button>
          </div>

          <div className="flex gap-3">
            <select
              value={cefr}
              onChange={(event) => setCefr(event.target.value)}
              className="input"
            >
              {LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
            <select
              value={role}
              onChange={(event) =>
                setRole(event.target.value as "USER" | "ADMIN")
              }
              className="input"
            >
              <option value="USER">普通用户</option>
              <option value="ADMIN">管理员</option>
            </select>
          </div>
        </div>

        <button
          type="submit"
          disabled={creating}
          className="btn-primary w-full"
        >
          {creating ? "创建中…" : "创建账号"}
        </button>
      </form>

      {loading ? (
        <Spinner />
      ) : users.length === 0 ? (
        <EmptyState text="还没有账号" />
      ) : (
        <div className="card divide-y divide-slate-100 p-0">
          {users.map((user) => (
            <div
              key={user.id}
              className="flex flex-wrap items-center gap-4 px-5 py-4"
            >
              <Avatar
                username={user.username}
                avatar={user.avatar}
                className="h-9 w-9 text-sm"
              />

              <div className="min-w-[10rem] flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-slate-900">
                    {user.username}
                  </p>
                  {user.role === "ADMIN" ? (
                    <span className="chip-brand">管理员</span>
                  ) : null}
                </div>
                <p className="text-xs text-slate-400">{user.email}</p>
                {user.password_updated_at ? (
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    密码更新于{" "}
                    {parseServerTime(user.password_updated_at).toLocaleString("zh-CN")}
                  </p>
                ) : null}
              </div>

              <div className="flex items-center gap-4 text-xs text-slate-500">
                <span>{user.cefr_level}</span>
                <span>⭐ {user.xp}</span>
                <span>🔥 {user.streak}</span>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => shareAccount(user)}
                  disabled={busyId === user.id}
                  className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 transition hover:border-brand-300 hover:bg-brand-100"
                >
                  分享
                </button>
                <button
                  onClick={() => openEdit(user)}
                  disabled={busyId === user.id}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-brand-300"
                >
                  编辑
                </button>
                <button
                  onClick={() => handleReset(user)}
                  disabled={busyId === user.id}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-brand-300"
                >
                  改密码
                </button>
                <button
                  onClick={() => handleRole(user)}
                  disabled={busyId === user.id}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-brand-300"
                >
                  {user.role === "ADMIN" ? "降为用户" : "设为管理员"}
                </button>
                <button
                  onClick={() => handleDelete(user)}
                  disabled={busyId === user.id}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-rose-500 transition hover:border-rose-300"
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing ? `编辑 ${editing.username}` : ""}
      >
        {editing ? (
          <form onSubmit={handleSaveEdit} className="space-y-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-slate-500">用户名</span>
              <input
                required
                minLength={2}
                maxLength={32}
                value={editUsername}
                onChange={(event) => setEditUsername(event.target.value)}
                className="input"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-slate-500">
                邮箱（登录用）
              </span>
              <input
                type="email"
                required
                value={editEmail}
                onChange={(event) => setEditEmail(event.target.value)}
                className="input"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-slate-500">
                新密码（留空则不修改）
              </span>
              <div className="flex gap-2">
                <input
                  type="text"
                  minLength={8}
                  value={editPassword}
                  onChange={(event) => setEditPassword(event.target.value)}
                  placeholder="至少 8 位"
                  className="input font-mono text-xs"
                />
                <button
                  type="button"
                  onClick={() => setEditPassword(suggestPassword())}
                  className="btn-ghost shrink-0 !px-3 text-xs"
                >
                  随机
                </button>
              </div>
            </label>
            <div className="flex gap-2 pt-1">
              <button
                type="submit"
                disabled={savingEdit}
                className="btn-primary flex-1"
              >
                {savingEdit ? "保存中…" : "保存"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="btn-ghost"
              >
                取消
              </button>
            </div>
          </form>
        ) : null}
      </Modal>
    </div>
  );
}

export default function AdminPage() {
  return (
    <RequireAdmin>
      <AppShell>
        <AdminConsole />
      </AppShell>
    </RequireAdmin>
  );
}
