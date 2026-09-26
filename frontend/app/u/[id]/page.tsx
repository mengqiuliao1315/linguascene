"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Heatmap } from "@/components/Heatmap";
import {
  Avatar,
  EmptyState,
  ProgressBar,
  Spinner,
} from "@/components/ui";
import { RequireAuth, useAuth } from "@/lib/auth";
import { socialApi, type FriendState, type Heatmap as Heat, type UserStats } from "@/lib/social";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3 text-center">
      <p className="text-lg font-semibold text-slate-900">{value}</p>
      <p className="text-[11px] text-slate-400">{label}</p>
      {hint ? <p className="text-[10px] text-brand-600">{hint}</p> : null}
    </div>
  );
}

function Profile() {
  const params = useParams<{ id: string }>();
  const userId = Number(params.id);
  const router = useRouter();
  const { user } = useAuth();

  const [stats, setStats] = useState<UserStats | null>(null);
  const [heat, setHeat] = useState<Heat | null>(null);
  const [state, setState] = useState<FriendState>("none");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    Promise.all([socialApi.userStats(userId), socialApi.userHeatmap(userId, 120)])
      .then(([s, h]) => {
        setStats(s);
        setHeat(h);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));

    socialApi
      .friendStatus(userId)
      .then((r) => setState(r.state))
      .catch(() => setState("none"));
  }, [userId]);

  async function handleFriend() {
    setBusy(true);
    setError("");
    try {
      const r = await socialApi.addFriend(userId);
      setState(r.state);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner />;
  if (error && !stats) return <EmptyState text={error} />;
  if (!stats) return <EmptyState text="用户不存在" />;

  const isMe = user?.id === stats.user_id;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <section className="card space-y-5 p-6">
        <div className="flex items-start gap-4">
          <Avatar
            username={stats.username}
            avatar={stats.avatar}
            className="h-14 w-14 text-xl"
            rounded="rounded-2xl"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-lg font-semibold text-slate-900">
                {stats.username}
              </p>
              {stats.role === "ADMIN" ? <span className="chip-brand">管理员</span> : null}
            </div>
            <p className="text-xs text-slate-400">
              Lv.{stats.level} {stats.level_name} · {stats.cefr_level}
              {stats.created_at
                ? ` · ${new Date(stats.created_at).toLocaleDateString("zh-CN")} 加入`
                : ""}
            </p>
          </div>

          {isMe ? (
            <Link href="/profile" className="btn-ghost !py-2 text-sm">
              编辑资料
            </Link>
          ) : (
            <div className="flex gap-2">
              {state === "friends" ? (
                <>
                  <span className="chip-brand">已是好友</span>
                  <Link href={`/friends?to=${stats.user_id}`} className="btn-primary !py-2 text-sm">
                    聊天
                  </Link>
                </>
              ) : state === "outgoing" ? (
                <span className="chip-slate">申请已发送</span>
              ) : state === "incoming" ? (
                <Link href="/friends" className="btn-primary !py-2 text-sm">
                  去处理申请
                </Link>
              ) : state === "self" ? null : (
                <button
                  onClick={handleFriend}
                  disabled={busy}
                  className="btn-primary !py-2 text-sm"
                >
                  加好友
                </button>
              )}
            </div>
          )}
        </div>

        {error ? (
          <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
        ) : null}

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>经验值 {stats.xp} XP</span>
            <span>贡献值 {stats.contribution}</span>
          </div>
          <ProgressBar value={Math.min(100, (stats.xp % 500) / 5)} />
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="连续打卡" value={stats.streak} />
          <Stat label="累计活跃" value={`${stats.active_days} 天`} />
          <Stat label="贡献值" value={stats.contribution} />
          <Stat label="经验值" value={stats.xp} />
        </div>
      </section>

      <section className="card space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">今日学习</h2>
          <span className="text-[11px] text-slate-400">每天有记录即算打卡</span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="今天学的单词" value={stats.words_today} />
          <Stat label="今天读的文章" value={stats.articles_today} />
          <Stat label="累计单词" value={stats.words_total} />
          <Stat label="完成场景" value={stats.scenarios_done} />
        </div>
      </section>

      <section className="card space-y-4 p-6">
        <h2 className="text-sm font-semibold text-slate-900">贡献</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="发布文章" value={stats.published_articles} />
          <Stat label="发帖" value={stats.forum_posts} />
          <Stat label="评论" value={stats.forum_comments} />
          <Stat label="收到赞" value={stats.likes_received} />
        </div>
      </section>

      <section className="card space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">打卡记录</h2>
          <span className="text-[11px] text-slate-400">
            最长 {heat?.longest_streak ?? 0} 天
          </span>
        </div>
        {heat ? <Heatmap cells={heat.cells} weeks={18} /> : null}
      </section>
    </div>
  );
}

export default function UserProfilePage() {
  return (
    <RequireAuth>
      <AppShell>
        <Profile />
      </AppShell>
    </RequireAuth>
  );
}
