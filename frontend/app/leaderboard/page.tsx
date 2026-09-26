"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Avatar, EmptyState, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import {
  socialApi,
  type FriendState,
  type LeaderRow,
  type Leaderboard,
} from "@/lib/social";

type Metric = "xp" | "streak" | "contribution";

const TABS: { key: Metric; label: string }[] = [
  { key: "xp", label: "经验值" },
  { key: "streak", label: "连续打卡" },
  { key: "contribution", label: "贡献值" },
];

const MEDALS = ["🥇", "🥈", "🥉"];

const METRIC_LABEL: Record<Metric, string> = {
  xp: "累计经验值",
  streak: "连续打卡天数",
  contribution: "社区贡献值",
};

const UNIT: Record<Metric, string> = { xp: "XP", streak: "天", contribution: "贡献" };

function formatValue(metric: Metric, value: number): string {
  return `${value} ${UNIT[metric]}`;
}

function Podium({ rows, metric }: { rows: LeaderRow[]; metric: Metric }) {
  const order = [rows[1], rows[0], rows[2]].filter(Boolean) as LeaderRow[];
  const heights: Record<number, number> = { 1: 92, 2: 64, 3: 52 };
  const blocks: Record<number, string> = {
    1: "bg-gradient-to-b from-brand-500 to-brand-700",
    2: "bg-gradient-to-b from-brand-300 to-brand-400",
    3: "bg-gradient-to-b from-brand-200 to-brand-300",
  };

  return (
    <div className="card p-5">
      <div className="flex items-end justify-center gap-4">
        {order.map((row) => {
          const rank = rows.indexOf(row) + 1;
          return (
            <Link
              key={row.user_id}
              href={`/u/${row.user_id}`}
              className="group flex w-24 flex-col items-center"
            >
              <div className="relative">
                <Avatar
                  username={row.username}
                  avatar={row.avatar}
                  className={
                    rank === 1
                      ? "h-16 w-16 text-xl ring-4 ring-amber-100"
                      : "h-14 w-14 text-lg"
                  }
                />
                <span className="absolute -right-2 -top-2 text-lg leading-none drop-shadow-sm">
                  {MEDALS[rank - 1]}
                </span>
              </div>
              <p
                className={`mt-2 w-full truncate text-center text-xs ${
                  row.is_me ? "font-semibold text-brand-700" : "text-slate-700"
                }`}
              >
                {row.username}
              </p>
              <p className="text-[11px] text-slate-400">Lv.{row.level}</p>
              <div
                className={`mt-2 flex w-full flex-col items-center justify-center gap-0.5 rounded-t-xl text-white ${blocks[rank]}`}
                style={{ height: heights[rank] }}
              >
                <span className="text-sm font-semibold leading-none">{row.value}</span>
                <span className="text-[10px] leading-none text-white/80">
                  {UNIT[metric]}
                </span>
              </div>
            </Link>
          );
        })}
      </div>
      <p className="mt-3 text-center text-[11px] text-slate-400">
        {METRIC_LABEL[metric]} · 前三名
      </p>
    </div>
  );
}

function RankRow({
  row,
  metric,
  peak,
  friendState,
  onAddFriend,
  adding,
}: {
  row: LeaderRow;
  metric: Metric;
  peak: number;
  friendState: FriendState | undefined;
  onAddFriend: (userId: number) => void;
  adding: boolean;
}) {
  const width = Math.max(4, Math.round((row.value / peak) * 100));
  const badge =
    row.rank === 1
      ? "bg-amber-100 text-amber-700"
      : row.rank === 2
        ? "bg-slate-200 text-slate-600"
        : row.rank === 3
          ? "bg-orange-100 text-orange-700"
          : "bg-slate-100 text-slate-500";

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 transition hover:bg-slate-50 sm:px-5 ${
        row.is_me ? "bg-brand-50/70" : ""
      }`}
    >
      <Link
        href={`/u/${row.user_id}`}
        className="flex min-w-0 flex-1 items-center gap-3"
      >
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${badge}`}
        >
          {row.rank <= 3 ? MEDALS[row.rank - 1] : row.rank}
        </span>

        <Avatar username={row.username} avatar={row.avatar} className="h-9 w-9 text-sm" />

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p
              className={`truncate text-sm ${
                row.is_me ? "font-semibold text-brand-700" : "text-slate-800"
              }`}
            >
              {row.username}
            </p>
            {row.is_me ? (
              <span className="shrink-0 rounded-full bg-brand-100 px-1.5 py-0.5 text-[10px] font-medium text-brand-700">
                我
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex items-center gap-2">
            <div className="h-1.5 w-full max-w-[160px] overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full ${row.is_me ? "bg-brand-600" : "bg-brand-400"}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="truncate text-[11px] text-slate-400">
              Lv.{row.level} {row.level_name} · 🔥 {row.streak}
            </span>
          </div>
        </div>

        <span className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
          {formatValue(metric, row.value)}
        </span>
      </Link>

      {!row.is_me ? (
        <div className="shrink-0">
          {friendState === "friends" ? (
            <span className="chip-slate">已是好友</span>
          ) : friendState === "outgoing" ? (
            <span className="chip-slate">已申请</span>
          ) : friendState === "incoming" ? (
            <Link href="/friends" className="chip-brand">
              待处理
            </Link>
          ) : (
            <button
              onClick={() => onAddFriend(row.user_id)}
              disabled={adding}
              className="btn-primary !py-1.5 text-xs disabled:opacity-60"
            >
              加好友
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Board() {
  const [metric, setMetric] = useState<Metric>("xp");
  const [data, setData] = useState<Leaderboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [friendStates, setFriendStates] = useState<Record<number, FriendState>>({});
  const [pending, setPending] = useState<number | null>(null);

  const loadFriendStates = useCallback(async () => {
    try {
      const [friends, requests] = await Promise.all([
        socialApi.friends(),
        socialApi.friendRequests(),
      ]);
      const next: Record<number, FriendState> = {};
      for (const friend of friends) next[friend.user_id] = "friends";
      for (const req of requests.incoming) next[req.user_id] = "incoming";
      for (const req of requests.outgoing) next[req.user_id] = "outgoing";
      setFriendStates(next);
    } catch {

    }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    socialApi
      .leaderboard(metric)
      .then((next) => {
        if (alive) setData(next);
      })
      .catch((err) => {
        if (alive) {
          setData(null);
          setError(err instanceof Error ? err.message : "加载失败");
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [metric]);

  useEffect(() => {
    void loadFriendStates();
  }, [loadFriendStates]);

  async function handleAddFriend(userId: number) {
    setPending(userId);
    setError("");
    try {
      const result = await socialApi.addFriend(userId);
      setFriendStates((prev) => ({ ...prev, [userId]: result.state }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
      void loadFriendStates();
    } finally {
      setPending(null);
    }
  }

  const entries = data?.entries ?? [];
  const top3 = entries.slice(0, 3);
  const peak = Math.max(1, ...entries.map((row) => row.value));

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">排行榜</h1>
          <p className="text-xs text-slate-400">{METRIC_LABEL[metric]}</p>
        </div>
        <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setMetric(key)}
              className={`rounded-lg px-3.5 py-1.5 text-sm transition ${
                metric === key
                  ? "bg-white font-medium text-brand-700 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState text={error} />
      ) : entries.length === 0 ? (
        <EmptyState text="还没有排名数据" />
      ) : (
        <>
          {top3.length >= 3 ? <Podium rows={top3} metric={metric} /> : null}

          <div className="card overflow-hidden p-0">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
              <h2 className="text-sm font-semibold text-slate-900">完整榜单</h2>
              <span className="text-[11px] text-slate-400">共 {entries.length} 人</span>
            </div>
            <div className="divide-y divide-slate-100">
              {entries.map((row) => (
                <RankRow
                  key={row.user_id}
                  row={row}
                  metric={metric}
                  peak={peak}
                  friendState={friendStates[row.user_id]}
                  onAddFriend={handleAddFriend}
                  adding={pending === row.user_id}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function LeaderboardPage() {
  return (
    <RequireAuth>
      <AppShell>
        <Board />
      </AppShell>
    </RequireAuth>
  );
}
