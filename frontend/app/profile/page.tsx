"use client";

import { useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  Avatar,
  EmptyState,
  ErrorText,
  ProgressBar,
  Spinner,
} from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth, useAuth } from "@/lib/auth";
import type {
  Achievement,
  CefrLevel,
  GamificationProfile,
  Theme,
} from "@/lib/types";

const LEVELS: CefrLevel[] = ["A1", "A2", "B1", "B2", "C1"];
const INTERESTS = ["Daily Life", "Travel", "Workplace", "Technology", "Culture"];

function AccountCard() {
  const { user, setUser } = useAuth();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [avatarError, setAvatarError] = useState("");

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [pwError, setPwError] = useState("");
  const [pwNotice, setPwNotice] = useState("");

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [identityPassword, setIdentityPassword] = useState("");
  const [savingIdentity, setSavingIdentity] = useState(false);
  const [identityError, setIdentityError] = useState("");
  const [identityNotice, setIdentityNotice] = useState("");

  useEffect(() => {
    if (!user) return;
    setUsername(user.username);
    setEmail(user.email);
  }, [user?.username, user?.email]);

  if (!user) return null;

  const identityDirty = username !== user.username || email !== user.email;

  async function handleIdentity(event: React.FormEvent) {
    event.preventDefault();
    setIdentityError("");
    setIdentityNotice("");
    if (!identityDirty) {
      setIdentityNotice("用户名与邮箱没有变化");
      return;
    }
    if (!identityPassword) {
      setIdentityError("修改用户名或邮箱需要输入当前密码");
      return;
    }
    setSavingIdentity(true);
    try {
      const updated = await api.updateMe({
        username: username.trim(),
        email: email.trim(),
        current_password: identityPassword,
      });
      setUser(updated);
      setIdentityPassword("");
      setIdentityNotice("账号信息已更新");
    } catch (err) {
      setIdentityError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSavingIdentity(false);
    }
  }

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setAvatarError("");
    setUploading(true);
    try {
      setUser(await api.uploadAvatar(file));
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);

      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleRemoveAvatar() {
    setAvatarError("");
    try {
      setUser(await api.removeAvatar());
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handlePassword(event: React.FormEvent) {
    event.preventDefault();
    setPwError("");
    setPwNotice("");
    if (next !== confirm) {
      setPwError("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setPwNotice("密码已更新，下次登录请用新密码");
    } catch (err) {
      setPwError(err instanceof Error ? err.message : "修改失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card space-y-6 p-6">
      <p className="section-title">账号设置</p>

      <div className="flex items-center gap-4">
        <Avatar
          username={user.username}
          avatar={user.avatar}
          className="h-16 w-16 text-xl"
          rounded="rounded-2xl"
        />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="btn-primary !py-2 text-xs"
            >
              {uploading ? "上传中…" : "上传头像"}
            </button>
            {user.avatar ? (
              <button
                type="button"
                onClick={handleRemoveAvatar}
                className="btn-ghost !py-2 text-xs"
              >
                移除
              </button>
            ) : null}
          </div>
          <p className="text-[11px] text-slate-400">
            PNG / JPG / WEBP / GIF，不超过 2MB
          </p>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            onChange={handleFile}
            className="hidden"
          />
        </div>
      </div>
      <ErrorText>{avatarError}</ErrorText>

      <form
        onSubmit={handleIdentity}
        className="space-y-3 border-t border-slate-100 pt-4"
      >
        <p className="text-sm font-medium text-slate-800">账号信息</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-[11px] text-slate-400">用户名</span>
            <input
              required
              minLength={2}
              maxLength={32}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="input"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] text-slate-400">邮箱（登录用）</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="input"
            />
          </label>
        </div>
        {identityDirty ? (
          <input
            type="password"
            required
            value={identityPassword}
            onChange={(event) => setIdentityPassword(event.target.value)}
            placeholder="当前密码（确认是本人操作）"
            className="input"
          />
        ) : null}
        <ErrorText>{identityError}</ErrorText>
        {identityNotice ? (
          <p className="rounded-xl bg-brand-50 px-3 py-2 text-xs text-brand-700">
            {identityNotice}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={savingIdentity || !identityDirty}
          className="btn-primary w-full sm:w-auto"
        >
          {savingIdentity ? "保存中…" : "保存账号信息"}
        </button>
      </form>

      <form onSubmit={handlePassword} className="space-y-3 border-t border-slate-100 pt-4">
        <p className="text-sm font-medium text-slate-800">修改登录密码</p>
        <input
          type="password"
          required
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          placeholder="当前密码"
          className="input"
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            type="password"
            required
            minLength={8}
            value={next}
            onChange={(event) => setNext(event.target.value)}
            placeholder="新密码（至少 8 位）"
            className="input"
          />
          <input
            type="password"
            required
            minLength={8}
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            placeholder="确认新密码"
            className="input"
          />
        </div>
        <ErrorText>{pwError}</ErrorText>
        {pwNotice ? (
          <p className="rounded-xl bg-brand-50 px-3 py-2 text-xs text-brand-700">
            {pwNotice}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={saving}
          className="btn-primary w-full sm:w-auto"
        >
          {saving ? "保存中…" : "更新密码"}
        </button>
      </form>
    </section>
  );
}

function formatDay(iso: string): string {
  const date = new Date(iso);
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

function ProfileView() {
  const { user, setUser } = useAuth();
  const [profile, setProfile] = useState<GamificationProfile | null>(null);
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  function load() {
    Promise.all([
      api.gamificationProfile(),
      api.achievements(),
      api.themes(),
    ])
      .then(([profileData, achievementData, themeData]) => {
        setProfile(profileData);
        setAchievements(achievementData);
        setThemes(themeData);
      })
      .catch(() => setMessage("加载失败"))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleLevelChange(level: CefrLevel) {
    const updated = await api.updateMe({ cefr_level: level });
    setUser(updated);
  }

  async function handleInterestToggle(value: string) {
    if (!user) return;
    const next = user.interests.includes(value)
      ? user.interests.filter((item) => item !== value)
      : [...user.interests, value];
    const updated = await api.updateMe({ interests: next });
    setUser(updated);
  }

  async function handleTheme(code: string) {
    setMessage("");
    try {
      const updated = await api.updateMe({ theme: code });
      setUser(updated);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "切换失败");
    }
  }

  if (loading) return <Spinner />;
  if (!profile || !user) return <EmptyState text={message || "加载失败"} />;

  const unlockedCount = achievements.filter((item) => item.unlocked).length;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <section className="card space-y-5 p-6">
        <div className="flex items-center gap-4">
          <Avatar
            username={user.username}
            avatar={user.avatar}
            className="h-14 w-14 text-xl"
            rounded="rounded-2xl"
          />
          <div className="flex-1">
            <p className="text-lg font-semibold text-slate-900">
              {user.username}
            </p>
            <p className="text-xs text-slate-400">{user.email}</p>
          </div>
          <div className="text-right">
            <p className="text-sm font-medium text-slate-900">
              Lv.{profile.level} {profile.level_name}
            </p>
            <p className="text-xs text-slate-400">⭐ {profile.xp} XP</p>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>距离下一级还需 {profile.xp_to_next} XP</span>
            <span>{profile.level_progress}%</span>
          </div>
          <ProgressBar value={profile.level_progress} />
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl bg-slate-50 p-3 text-center">
            <p className="text-lg font-semibold text-slate-900">
              {profile.streak}
            </p>
            <p className="text-[11px] text-slate-400">连续打卡</p>
          </div>
          <div className="rounded-xl bg-slate-50 p-3 text-center">
            <p className="text-lg font-semibold text-slate-900">
              {profile.weekly_xp}
            </p>
            <p className="text-[11px] text-slate-400">本周 XP</p>
          </div>
          <div className="rounded-xl bg-slate-50 p-3 text-center">
            <p className="text-lg font-semibold text-slate-900">
              {profile.xp}
            </p>
            <p className="text-[11px] text-slate-400">经验值</p>
          </div>
          <div className="rounded-xl bg-slate-50 p-3 text-center">
            <p className="text-lg font-semibold text-slate-900">
              {unlockedCount}/{achievements.length}
            </p>
            <p className="text-[11px] text-slate-400">成就</p>
          </div>
        </div>

        <div className="flex gap-1.5">
          {["一", "二", "三", "四", "五", "六", "日"].map((label, index) => {
            const date = new Date();
            const monday = new Date(date);
            monday.setDate(date.getDate() - ((date.getDay() + 6) % 7) + index);
            const key = monday.toISOString().slice(0, 10);
            const active = profile.active_days.includes(key);
            return (
              <div key={label} className="flex-1 text-center">
                <div
                  className={`mx-auto flex h-8 w-8 items-center justify-center rounded-lg text-xs ${
                    active
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-400"
                  }`}
                >
                  {active ? "✓" : label}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <AccountCard />

      <section className="card space-y-4 p-6">
        <p className="section-title">英语等级</p>
        <div className="flex flex-wrap gap-2">
          {LEVELS.map((level) => (
            <button
              key={level}
              onClick={() => handleLevelChange(level)}
              className={`rounded-xl px-4 py-2 text-sm transition ${
                user.cefr_level === level
                  ? "bg-brand-600 text-white"
                  : "border border-slate-200 bg-white text-slate-600 hover:border-brand-300"
              }`}
            >
              {level}
            </button>
          ))}
        </div>

        <p className="section-title pt-2">关注方向</p>
        <div className="flex flex-wrap gap-2">
          {INTERESTS.map((item) => (
            <button
              key={item}
              onClick={() => handleInterestToggle(item)}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                user.interests.includes(item)
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-slate-200 bg-white text-slate-600 hover:border-brand-300"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <p className="section-title">成就</p>
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
          {achievements.map((item) => (
            <div
              key={item.code}
              title={item.description}
              className={`card flex flex-col items-center gap-1.5 p-3 text-center ${
                item.unlocked ? "" : "opacity-60"
              }`}
            >
              <span className={`text-xl ${item.unlocked ? "" : "grayscale"}`}>
                {item.icon}
              </span>
              <span className="text-[11px] font-medium text-slate-700">
                {item.name}
              </span>
              {item.unlocked ? (
                <span className="text-[10px] text-brand-600">
                  {item.unlocked_at ? formatDay(item.unlocked_at) : "已解锁"}
                </span>
              ) : (

                <div className="w-full space-y-1">
                  <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-brand-400"
                      style={{
                        width: `${
                          item.target > 0
                            ? Math.min(100, (item.progress / item.target) * 100)
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                  <span className="block text-[10px] text-slate-400">
                    {item.progress}/{item.target}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <p className="section-title">皮肤</p>
        {message ? (
          <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
            {message}
          </p>
        ) : null}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {themes.map((item) => (
            <div key={item.code} className="card space-y-3 p-4">
              <div className="flex h-12 items-center gap-1 overflow-hidden rounded-lg">
                {item.colors.map((color) => (
                  <span
                    key={color}
                    className="h-full flex-1"
                    style={{ backgroundColor: color }}
                  />
                ))}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-800">
                  {item.name}
                </span>
              </div>
              <button
                onClick={() => handleTheme(item.code)}
                disabled={user.theme === item.code}
                className={`w-full rounded-xl py-2 text-xs transition ${
                  user.theme === item.code
                    ? "bg-brand-50 text-brand-600"
                    : "border border-slate-200 text-slate-600 hover:border-brand-300"
                }`}
              >
                {user.theme === item.code ? "使用中" : "使用"}
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <RequireAuth>
      <AppShell>
        <ProfileView />
      </AppShell>
    </RequireAuth>
  );
}
