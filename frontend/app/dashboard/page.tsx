"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { DailyTaskCard } from "@/components/DailyTaskCard";
import { Heatmap } from "@/components/Heatmap";
import { PetCard } from "@/components/PetCard";
import { QuestBoard } from "@/components/QuestBoard";
import {
  EmptyState,
  LevelBadge,
  ProgressBar,
  ScenarioCard,
  SectionHeader,
  Spinner,
} from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { socialApi, type Heatmap as Heat } from "@/lib/social";
import type { Dashboard } from "@/lib/types";

function greetingFor(hour: number): string {
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function DashboardContent() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [heat, setHeat] = useState<Heat | null>(null);
  const [error, setError] = useState("");
  const [greeting, setGreeting] = useState("");

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));

    socialApi
      .heatmap(120)
      .then(setHeat)
      .catch(() => setHeat(null));
  }, []);

  useEffect(() => {
    const tick = () => setGreeting(greetingFor(new Date().getHours()));
    tick();
    const timer = setInterval(tick, 60_000);
    return () => clearInterval(timer);
  }, []);

  if (error) return <EmptyState text={error} />;
  if (!data) return <Spinner />;

  return (
    <div className="space-y-8">
      <section className="card flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-3">
          <h1 className="text-xl font-semibold text-slate-900">
            {greeting || data.greeting}, {data.username} 👋
          </h1>
          <div className="flex flex-wrap items-center gap-2">
            <span className="chip-brand">🔥 连续打卡 {data.streak} 天</span>
            <span className="chip-slate">⭐ {data.xp} XP</span>
            <LevelBadge level={data.level} name={data.level_name} />
          </div>
        </div>

        <div className="w-full space-y-2 sm:w-64">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Lv.{data.level}</span>
            <span>还需 {data.xp_to_next} XP</span>
          </div>
          <ProgressBar value={data.level_progress} />
          <Link href="/scenarios" className="btn-primary mt-2 w-full">
            Continue Learning
          </Link>
        </div>
      </section>

      {heat ? (
        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="card space-y-4 p-5">
            <SectionHeader
              title="学习记录"
              action={
                <Link href="/leaderboard" className="text-xs text-brand-600">
                  排行榜
                </Link>
              }
            />
            <Heatmap
              cells={heat.cells}
              weeks={18}
              currentStreak={heat.current_streak}
              longestStreak={heat.longest_streak}
              activeDays={heat.total_active_days}
            />
          </div>

          <PetCard />
        </section>
      ) : null}

      <DailyTaskCard />

      <section>
        <SectionHeader title="Today's Mission" />
        {data.today_mission ? (
          <Link
            href={`/scenarios/${data.today_mission.id}`}
            className="card flex items-center gap-5 p-6 transition hover:border-brand-300 hover:shadow-lg"
          >
            <span className="text-4xl">{data.today_mission.icon}</span>
            <div className="flex-1">
              <p className="text-lg font-semibold text-slate-900">
                {data.today_mission.title}
              </p>
              <p className="text-sm text-slate-500">
                {data.today_mission.title_zh} · {data.today_mission.ai_role}
              </p>
              <div className="mt-2 flex gap-2">
                <span className="chip-slate">
                  {data.today_mission.estimated_minutes} min
                </span>
                <span className="chip-slate">{data.today_mission.level}</span>
              </div>
            </div>
            <span className="btn-primary">Start</span>
          </Link>
        ) : (
          <EmptyState text="全部场景已完成" />
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="lg:col-span-2 space-y-6">
          <div>
            <SectionHeader title="Recommended" />
            <div className="grid gap-4 sm:grid-cols-2">
              {data.recommended_scenarios.slice(0, 4).map((scenario) => (
                <ScenarioCard
                  key={scenario.id}
                  id={scenario.id}
                  icon={scenario.icon}
                  title={scenario.title}
                  titleZh={scenario.title_zh}
                  level={scenario.level}
                  minutes={scenario.estimated_minutes}
                  role={scenario.ai_role}
                />
              ))}
            </div>
          </div>

        </section>

        <section className="space-y-4">
          <QuestBoard />

          {data.review_due_count > 0 ? (
            <Link
              href="/vocabulary"
              className="card block p-4 transition hover:border-brand-300"
            >
              <p className="text-sm font-medium text-slate-900">
                今日待复习 {data.review_due_count} 个单词
              </p>
            </Link>
          ) : null}

          {data.recommended_article ? (
            <Link
              href={`/reading/article/${data.recommended_article.id}`}
              className="card block p-4 transition hover:border-brand-300"
            >
              <p className="text-xs text-slate-400">
                {data.recommended_article.category} ·{" "}
                {data.recommended_article.read_minutes} min
              </p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                {data.recommended_article.title}
              </p>
            </Link>
          ) : null}
        </section>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <AppShell>
        <DashboardContent />
      </AppShell>
    </RequireAuth>
  );
}
